#!/bin/sh
set -eu

# Headed Linux Chromium renders into the virtual desktop.
Xvfb :99 -screen 0 1366x768x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 2
# VNC backend is accessible only within the container.
x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -nopw -quiet >/tmp/x11vnc.log 2>&1 &
# noVNC bridges browser WebSockets to VNC. Host-level bind is loopback only.
websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
exec uvicorn app:app --host 0.0.0.0 --port 8000 --no-access-log
