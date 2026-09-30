FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.3 \
    gunicorn==22.0.0 \
    PyJWT==2.8.0 \
    cryptography==42.0.8 \
    redis==5.0.8

COPY auth_server.py .

EXPOSE 9002

CMD ["gunicorn", "--bind", "0.0.0.0:9002", "--workers", "2", "--timeout", "30", "auth_server:app"]
