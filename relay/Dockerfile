FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    PyJWT==2.8.0 \
    cryptography==42.0.8 \
    jsonschema==4.23.0 \
    redis==5.0.8

COPY registry_server.py mocha_validator.py ./

EXPOSE 8081

CMD ["python", "-u", "registry_server.py"]
