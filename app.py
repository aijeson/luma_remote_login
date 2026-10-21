"""Single-operator demo. Do NOT expose ports directly to the internet."""
import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright

from session_store import (
    STATE_FILE, delete_local_state, filter_luma_state,
    is_luma_host, load_encrypted, save_encrypted,
)

LOGIN_URL = 'https://luma.com/signin?next=%2Fhome'
HOME_URL = 'https://luma.com/home'
CHROMIUM = '/usr/bin/chromium'
logger = logging.getLogger('luma-demo')
logging.basicConfig(level=logging.INFO)


async def fresh_context(browser):
    context = await browser.new_context(
        viewport={'width': 1320, 'height': 700},
        locale='en-US',
    )
    page = await context.new_page()
    await page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=60000)
    return context, page


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get('APP_TOKEN') or not os.environ.get('FERNET_KEY'):
        raise RuntimeError('APP_TOKEN and FERNET_KEY are both required.')
    # Validate key early; do not show the key in logs.
    from cryptography.fernet import Fernet
    Fernet(os.environ['FERNET_KEY'].encode())
    app.state.lock = asyncio.Lock()
    app.state.pw = await async_playwright().start()
    app.state.browser = await app.state.pw.chromium.launch(
        executable_path=CHROMIUM,
        headless=False,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1360,760'],
    )
    try:
        app.state.context, app.state.page = await fresh_context(app.state.browser)
        logger.info('Luma sign-in page is ready in the virtual browser.')
    except Exception:
        logger.exception('Could not open Luma sign-in page; check network connectivity.')
        # Let /health and /api/status still work and report failure.
        app.state.context = await app.state.browser.new_context()
        app.state.page = await app.state.context.new_page()
    try:
        yield
    finally:
        await app.state.browser.close()
        await app.state.pw.stop()


app = FastAPI(title='Luma remote sign-in demo', lifespan=lifespan)


def require_token(x_admin_token: str = Header(default='')):
    expected = os.environ.get('APP_TOKEN', '')
    if not expected or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail='APP_TOKEN is missing or incorrect')


@app.get('/')
async def index():
    return FileResponse(Path(__file__).parent / 'static' / 'index.html')


@app.get('/health')
async def health():
    return {'status': 'up'}


@app.get('/api/status', dependencies=[Depends(require_token)])
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
        'note': 'Cookie count and URL cannot on their own prove authentication.'
    }


@app.post('/api/save', dependencies=[Depends(require_token)])
async def save_state():
    async with app.state.lock:
        page_url = app.state.page.url
        url = urlsplit(page_url)
        if not is_luma_host(url.hostname) or url.path.startswith('/signin'):
            raise HTTPException(
                status_code=400,
                detail='Please finish signing in and return to a Luma page before saving.'
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
            'message': 'Encrypted state saved locally. Check with /api/verify or worker.py.'
        }


async def run_probe(browser):
    """A heuristic, not an assertion that protected data is accessible."""
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
                'Probably not signed in (redirected to sign-in page)'
                if login_redirect else
                'Sign-in link visible; login not confirmed'
                if visible else
                'No sign-in link found; appears signed in, verify manually'
            ),
            'important': 'The public /home page may be accessible without signing in. This is only a heuristic.'
        }
    finally:
        await context.close()


@app.post('/api/verify', dependencies=[Depends(require_token)])
async def verify_state():
    if not STATE_FILE.exists():
        raise HTTPException(status_code=404, detail='No encrypted session saved yet.')
    async with app.state.lock:
        try:
            return await run_probe(app.state.browser)
        except Exception:
            logger.exception('Verification failed (secrets omitted).')
            raise HTTPException(status_code=502, detail='Verification failed. Check server logs.')


@app.post('/api/disconnect', dependencies=[Depends(require_token)])
async def disconnect():
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
            'message': 'Local state deleted and demo browser cleared. This does NOT revoke the Luma-side session.'
        }
