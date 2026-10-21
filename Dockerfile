FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium xvfb x11vnc novnc websockify nginx apache2-utils \
    ca-certificates fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py worker.py session_store.py entrypoint.sh ./
COPY static/ ./static/
COPY nginx.conf ./nginx.conf
RUN chmod +x /app/entrypoint.sh && mkdir -p /data

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
