# ── API backend ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS api

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.3 \
    flask-cors==4.0.1 \
    gunicorn==22.0.0 \
    PyJWT==2.8.0 \
    cryptography==42.0.8 \
    redis==5.0.8

COPY api/admin_server.py ./admin_server.py

EXPOSE 9004
CMD ["gunicorn", "--bind", "0.0.0.0:9004", "--workers", "2", "--timeout", "60", "admin_server:app"]

# ── Frontend static (nginx) ────────────────────────────────────────────────────
FROM nginx:alpine AS frontend

COPY src/index.html /usr/share/nginx/html/admin/index.html
COPY src/admin.css  /usr/share/nginx/html/admin/admin.css
COPY src/js/        /usr/share/nginx/html/admin/js/

# nginx config para SPA: /admin/* → index.html, /admin/api/* → proxy a :9004
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3001
