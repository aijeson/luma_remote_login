"""Offline tests; do not launch Chromium. Run: pytest -q tests/test_auth.py"""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault('APP_TOKEN', 'sample-test-token')
os.environ.setdefault('FERNET_KEY', 'A' * 43 + '=')

from fastapi.testclient import TestClient
from app import app


def test_login_auth_logout_flow():
    headers = {'Origin': 'https://demo.example.com', 'Host': 'demo.example.com'}
    client = TestClient(app, base_url='https://demo.example.com')
    assert client.get('/api/me').json() == {'authenticated': False}
    assert client.get('/internal/auth-check').status_code == 401
    assert client.get('/api/status').status_code == 401
    assert client.post('/api/login', json={'token': 'bad'}, headers=headers).status_code == 401
    r = client.post('/api/login', json={'token': os.environ['APP_TOKEN']}, headers=headers)
    assert r.status_code == 200
    assert 'httponly' in r.headers['set-cookie'].lower()
    assert 'secure' in r.headers['set-cookie'].lower()
    assert 'samesite=strict' in r.headers['set-cookie'].lower()
    assert client.get('/api/me').json() == {'authenticated': True}
    assert client.get('/internal/auth-check').status_code == 204
    assert client.post('/api/logout', headers=headers).status_code == 200
    assert client.get('/internal/auth-check').status_code == 401


def test_cross_origin_denied():
    client = TestClient(app, base_url='https://demo.example.com')
    r = client.post('/api/login', json={'token': os.environ['APP_TOKEN']}, headers={'Origin': 'https://evil.example.com'})
    assert r.status_code == 403


def test_nginx_has_auth_for_novnc_and_no_basic():
    nginx = (Path(__file__).parent.parent / 'nginx.conf').read_text()
    assert 'auth_basic' not in nginx
    assert 'location /novnc/' in nginx and 'auth_request /_auth' in nginx
    html = (Path(__file__).parent.parent / 'static/index.html').read_text()
    assert 'path=novnc%2Fwebsockify' in html
