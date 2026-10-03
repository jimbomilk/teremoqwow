FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask==3.0.3 \
    flask-cors==4.0.1 \
    gunicorn==22.0.0 \
    PyJWT==2.8.0 \
    cryptography==42.0.8 \
    jsonschema==4.23.0 \
    redis==5.0.8 \
    prometheus-client==0.20.0

COPY webhook_handler.py geo_middleware.py rights.py ./

EXPOSE 9000

# /health endpoint se añade en webhook_handler.py
CMD ["gunicorn", "--bind", "0.0.0.0:9000", "--workers", "2", "--timeout", "30", "webhook_handler:app"]
