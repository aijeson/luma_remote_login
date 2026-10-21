"""Independent headless worker that reuses the encrypted state.

Run with: docker compose exec -T app python worker.py
No cookies, passwords, email codes, or private page contents are printed.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from session_store import STATE_FILE, load_encrypted


async def main():
    if not STATE_FILE.exists():
        print('No saved session found. First sign in and click Save authorization.')
        return
    state = load_encrypted()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path='/usr/bin/chromium',
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        try:
            context = await browser.new_context(storage_state=state)
            page = await context.new_page()
            response = await page.goto('https://luma.com/home', wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(1500)
            sign_in = page.get_by_role('link', name='Sign In', exact=True)
            count = await sign_in.count()
            sign_in_visible = bool(count) and await sign_in.first.is_visible()
            url = page.url
            print(json.dumps({
                'visited_url': url,
                'title': await page.title(),
                'http_status': response.status if response else None,
                'redirected_to_signin': urlsplit(url).path.startswith('/signin'),
                'sign_in_link_visible': sign_in_visible,
                'note': 'This is a connectivity/session smoke test, not definitive auth proof.'
            }, ensure_ascii=False, indent=2))
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
