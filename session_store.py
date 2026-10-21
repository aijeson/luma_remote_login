"""Only persist Luma-scoped Playwright state, encrypted with Fernet.

Never log or return the decrypted browser state to an API client.
"""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

DATA_DIR = Path('/data')
STATE_FILE = DATA_DIR / 'luma-session.enc'


def is_luma_host(hostname: str | None) -> bool:
    host = (hostname or '').lower().strip('.')
    return host == 'luma.com' or host.endswith('.luma.com')


def _cipher() -> Fernet:
    return Fernet(os.environ['FERNET_KEY'].encode())


def filter_luma_state(state: dict) -> dict:
    cookies = [
        c for c in state.get('cookies', [])
        if is_luma_host(c.get('domain', ''))
    ]
    origins = [
        o for o in state.get('origins', [])
        if is_luma_host(urlsplit(o.get('origin', '')).hostname)
    ]
    return {'cookies': cookies, 'origins': origins}


def save_encrypted(state: dict) -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    ciphertext = _cipher().encrypt(json.dumps(state, ensure_ascii=False).encode())
    fd, temp_path = tempfile.mkstemp(prefix='.luma-tmp-', dir=DATA_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(ciphertext)
        os.replace(temp_path, STATE_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_encrypted() -> dict:
    return json.loads(_cipher().decrypt(STATE_FILE.read_bytes()))


def delete_local_state() -> None:
    STATE_FILE.unlink(missing_ok=True)
