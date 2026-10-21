"""Single-operator Luma remote-browser demo with in-page authentication.

No HTTP Basic Auth. A short-lived, HttpOnly, Secure, SameSite=Strict cookie
is issued after the operator supplies APP_TOKEN inside the app page.
Nginx auth_request validates it before serving noVNC or upgrading WebSockets.

IMPORTANT: this is NOT a multi-user system. There is one shared Chromium.
"""
import asyncio
import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

from session_store import (
    STATE_FILE, delete_local_state, filter_luma_state,
    is_luma_host, load_encrypted, save_encrypted,
)

LOGIN_URL = 'https://luma.com/signin?next=%2Fhome'
HOME_URL = 'https://luma.com/home'
CHROMIUM = '/usr/bin/chromium'
COOKIE_NAME = 'luma_demo_session'
SESSION_TTL_SECONDS = 8 * 60 * 60
logger = logging.getLogger('luma-demo')
logging.basicConfig(level=logging.INFO)


async def fresh_context(browser):
    context = await browser.new_context(
        viewport={'width': 1320, 'height': 700}, locale='en-US',
    )
    page = await context.new_page()
    await page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=60000)
    return context, page


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get('APP_TOKEN') or not os.environ.get('FERNET_KEY'):
        raise RuntimeError('APP_TOKEN and FERNET_KEY are required.')
    from cryptography.fernet import Fernet
    Fernet(os.environ['FERNET_KEY'].encode())
    app.state.lock = asyncio.Lock()
    app.state.pw = await async_playwright().start()
    app.state.browser = await app.state.pw.chromium.launch(
        executable_path=CHROMIUM, headless=False,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1360,760'],
    )
    try:
        app.state.context, app.state.page = await fresh_context(app.state.browser)
        logger.info('Luma sign-in page is ready in the virtual browser.')
    except Exception:
        logger.exception('Could not open Luma sign-in page; check network connectivity.')
        app.state.context = await app.state.browser.new_context()
        app.state.page = await app.state.context.new_page()
    try:
        yield
    finally:
        await app.state.browser.close()
        await app.state.pw.stop()


app = FastAPI(title='Luma remote sign-in demo', lifespan=lifespan)
# One Uvicorn process, in-memory sessions. Restart logs operators out.
app.state.admin_sessions = {}


class LoginRequest(BaseModel):
    token: str


def ensure_same_origin(request: Request):
    """Reject cross-site POSTs even if a browser disregards SameSite."""
    origin = request.headers.get('origin', '')
    host = request.headers.get('host', '')
    parsed = urlsplit(origin)
    if not origin or not host or parsed.scheme not in ('https', 'http') or parsed.netloc.lower() != host.lower():
        raise HTTPException(status_code=403, detail='Request origin not allowed.')


def valid_session(request: Request) -> bool:
    sid = request.cookies.get(COOKIE_NAME, '')
    if not sid or len(sid) > 256:
        return False
    digest = hashlib.sha256(sid.encode('ascii', 'ignore')).hexdigest()
    expires = app.state.admin_sessions.get(digest, 0)
    if not expires:
        return False
    if expires <= time.monotonic():
        app.state.admin_sessions.pop(digest, None)
        return False
    return True


def require_session(request: Request):
    if not valid_session(request):
        # IMPORTANT: no WWW-Authenticate header => no browser Basic Auth popup.
        raise HTTPException(status_code=401, detail='请先在本页面输入 APP_TOKEN 解锁。')


@app.get('/')
async def index():
    return FileResponse(Path(__file__).parent / 'static' / 'index.html')


@app.get('/health')
async def health():
    return {'status': 'up'}


@app.get('/api/me')
async def me(request: Request):
    return {'authenticated': valid_session(request)}


@app.post('/api/login')
async def login(body: LoginRequest, request: Request, response: Response):
    ensure_same_origin(request)
    expected = os.environ.get('APP_TOKEN', '')
    if not expected or not secrets.compare_digest(body.token, expected):
        await asyncio.sleep(0.3)
        raise HTTPException(status_code=401, detail='APP_TOKEN 不正确。')
    session_id = secrets.token_urlsafe(32)
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    app.state.admin_sessions[digest] = time.monotonic() + SESSION_TTL_SECONDS
    # Only available over HTTPS (boat.dev provides TLS at the public endpoint).
    response.set_cookie(
        key=COOKIE_NAME, value=session_id, max_age=SESSION_TTL_SECONDS,
        httponly=True, secure=True, samesite='strict', path='/',
    )
    return {'authenticated': True, 'expires_in_seconds': SESSION_TTL_SECONDS}


@app.post('/api/logout')
async def logout(request: Request, response: Response):
    ensure_same_origin(request)
    sid = request.cookies.get(COOKIE_NAME, '')
    if sid:
        digest = hashlib.sha256(sid.encode('ascii', 'ignore')).hexdigest()
        app.state.admin_sessions.pop(digest, None)
    response.delete_cookie(key=COOKIE_NAME, path='/', secure=True, httponly=True, samesite='strict')
    return {'authenticated': False}


@app.get('/internal/auth-check')
async def auth_check(request: Request):
    if not valid_session(request):
        raise HTTPException(status_code=401, detail='Unauthorized')
    return Response(status_code=204)


@app.get('/api/status', dependencies=[Depends(require_session)])
async def status():
    page = app.state.page
    url = page.url
    try:
        title = await page.title()
    except Exception:
        title = '(page still loading)'
    try:
        cookies = await app.state.context.cookies('https://luma.com')
        count = sum(is_luma_host(c.get('domain')) for c in cookies)
    except Exception:
        count = 0
    return {
        'browser_url': url,
        'page_title': title,
        'luma_cookie_count': count,
        'saved_session_exists': STATE_FILE.exists(),
        'note': 'Cookie count and URL cannot on their own prove authentication.',
    }


@app.post('/api/save', dependencies=[Depends(require_session)])
async def save_state(request: Request):
    ensure_same_origin(request)
    async with app.state.lock:
        page_url = app.state.page.url
        url = urlsplit(page_url)
        if not is_luma_host(url.hostname) or url.path.startswith('/signin'):
            raise HTTPException(
                status_code=400,
                detail='Please finish signing in and return to a Luma page before saving.',
            )
        raw_state = await app.state.context.storage_state(indexed_db=True)
        filtered = filter_luma_state(raw_state)
        if not filtered['cookies']:
            raise HTTPException(status_code=400, detail='No Luma cookies found. Check login status.')
        save_encrypted(filtered)
        return {
            'saved': True,
            'luma_cookie_count': len(filtered['cookies']),
            'luma_origin_count': len(filtered['origins']),
            'message': 'Encrypted state saved locally. Check with /api/verify or worker.py.',
        }


async def run_probe(browser):
    """A smoke test; not definitive evidence of Luma authentication."""
    state = load_encrypted()
    context = await browser.new_context(storage_state=state)
    try:
        page = await context.new_page()
        response = await page.goto(HOME_URL, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(1500)
        url = page.url
        sign_in_link = page.get_by_role('link', name='Sign In', exact=True)
        count = await sign_in_link.count()
        visible = bool(count) and await sign_in_link.first.is_visible()
        login_redirect = urlsplit(url).path.startswith('/signin')
        return {
            'opened_url': url,
            'title': await page.title(),
            'http_status': response.status if response else None,
            'sign_in_link_visible': visible,
            'result': (
                'Probably not signed in (redirected to sign-in page)' if login_redirect else
                'Sign-in link visible; login not confirmed' if visible else
                'No sign-in link found; appears signed in, verify manually'
            ),
            'important': 'The public /home page may be accessible without signing in. This is only a heuristic.',
        }
    finally:
        await context.close()


@app.post('/api/verify', dependencies=[Depends(require_session)])
async def verify_state(request: Request):
    ensure_same_origin(request)
    if not STATE_FILE.exists():
        raise HTTPException(status_code=404, detail='No encrypted session saved yet.')
    async with app.state.lock:
        try:
            return await run_probe(app.state.browser)
        except Exception:
            logger.exception('Verification failed (secrets omitted).')
            raise HTTPException(status_code=502, detail='Verification failed. Check server logs.')


@app.post('/api/disconnect', dependencies=[Depends(require_session)])
async def disconnect(request: Request):
    ensure_same_origin(request)
    async with app.state.lock:
        delete_local_state()
        await app.state.context.close()
        try:
            app.state.context, app.state.page = await fresh_context(app.state.browser)
        except Exception:
            logger.exception('Sign-in page failed to reopen.')
            app.state.context = await app.state.browser.new_context()
            app.state.page = await app.state.context.new_page()
        return {
            'deleted_local_session': True,
            'message': 'Local state deleted and demo browser cleared. This does NOT revoke the Luma-side session.',
        }
