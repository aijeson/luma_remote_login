#!/bin/sh
set -eu

: "${APP_TOKEN:?APP_TOKEN is required}"
: "${FERNET_KEY:?FERNET_KEY is required}"

# All three internal endpoints stay loopback-only. Do NOT publish 5900/6080/8001.
Xvfb :99 -screen 0 1366x768x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 2
x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -nopw -quiet >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
nginx -t -c /app/nginx.conf
nginx -c /app/nginx.conf -g 'daemon off;' &
exec uvicorn app:app --host 127.0.0.1 --port 8001 --no-access-log
