# ── API backend ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS api

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.3 \
    gunicorn==22.0.0 \
    PyJWT==2.8.0 \
    cryptography==42.0.8 \
    redis==5.0.8

COPY api/admin_server.py ./admin_server.py

# ── Frontend static (nginx) ────────────────────────────────────────────────────
FROM nginx:alpine AS frontend

COPY src/index.html /usr/share/nginx/html/admin/index.html

# nginx config para SPA: /admin/* → index.html, /admin/api/* → proxy a :9004
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3001
