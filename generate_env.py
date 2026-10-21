"""Create one-off local demo secrets. Never commit .env to Git."""
import base64
import os
import secrets
from pathlib import Path

p = Path(__file__).parent / '.env'
if p.exists():
    raise SystemExit('Refusing to overwrite existing .env')
fernet_key = base64.urlsafe_b64encode(os.urandom(32)).decode('ascii')
api_token = secrets.token_urlsafe(32)
with p.open('x') as f:
    f.write(f'FERNET_KEY={fernet_key}\nAPP_TOKEN={api_token}\n')
os.chmod(p, 0o600)
print('Created .env (0600). Keep it private; APP_TOKEN is needed to operate the UI.')
