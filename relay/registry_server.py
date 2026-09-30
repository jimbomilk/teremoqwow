#!/usr/bin/env python3
"""
Registry server — issue #87.
Endpoint: POST /v1/registry/join
Emite cluster JWTs RS256 para nodos federados.
"""
import json
import logging
import os
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import jsonschema
import jwt  # PyJWT >= 2.0

# Redis para rate-limit distribuido (opcional — fallback a memoria)
_redis: Optional[object] = None

def _get_redis():
    global _redis
    if _redis is None:
        url = os.environ.get("REDIS_URL", "")
        if url:
            try:
                import redis as _redis_lib
                client = _redis_lib.Redis.from_url(url, decode_responses=True)
                client.ping()
                _redis = client
                logger.info("registry: conectado a Redis %s", url)
            except Exception as exc:
                logger.warning("registry: Redis no disponible (%s), usando memoria", exc)
    return _redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SCHEMA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "schemas", "registry", "v1")
)
JWT_TTL = 86400  # 24 h
_RATE_LIMIT = 5
_RATE_WINDOW = 60  # segundos


def _load_schema(name: str) -> dict:
    with open(os.path.join(_SCHEMA_DIR, name)) as fh:
        return json.load(fh)


_JOIN_SCHEMA = _load_schema("registry-join.json")
_NODE_SCHEMA = _load_schema("node.json")

# Resolver que mapea URIs teremoqwow.dev a los ficheros locales
_SCHEMA_STORE = {
    "https://teremoqwow.dev/schemas/registry/v1/registry-join.json": _JOIN_SCHEMA,
    "https://teremoqwow.dev/schemas/registry/v1/node.json": _NODE_SCHEMA,
}
_RESOLVER = jsonschema.RefResolver(
    base_uri=f"https://teremoqwow.dev/schemas/registry/v1/registry-join.json",
    referrer=_JOIN_SCHEMA,
    store=_SCHEMA_STORE,
)

# rate limiter en memoria (fallback cuando Redis no está disponible)
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    r = _get_redis()
    if r is not None:
        try:
            key = f"rl:{ip}"
            count = r.incr(key)
            if count == 1:
                r.expire(key, _RATE_WINDOW)
            return count <= _RATE_LIMIT
        except Exception as exc:
            logger.warning("registry: rate-limit Redis error: %s", exc)
    # fallback memoria
    now = time.monotonic()
    _rate_buckets[ip] = [t for t in _rate_buckets[ip] if now - t < _RATE_WINDOW]
    if len(_rate_buckets[ip]) >= _RATE_LIMIT:
        return False
    _rate_buckets[ip].append(now)
    return True


def _load_private_key() -> str:
    # Acepta clave inline (REGISTRY_PRIVATE_KEY) o path a fichero PEM
    key = os.environ.get("REGISTRY_PRIVATE_KEY")
    if key:
        return key
    path = os.environ.get("REGISTRY_PRIVATE_KEY_PATH")
    if path:
        with open(path) as f:
            return f.read()
    raise RuntimeError("Define REGISTRY_PRIVATE_KEY o REGISTRY_PRIVATE_KEY_PATH")


def _issue_cluster_jwt(node_id: str, region: str) -> str:
    now = int(time.time())
    claims = {
        "sub": node_id,
        "node_id": node_id,
        "region": region,
        "namespace_pattern": f"contrib/{node_id}/**",
        "iat": now,
        "exp": now + JWT_TTL,
    }
    token = jwt.encode(claims, _load_private_key(), algorithm="RS256")
    # token nunca se loguea completo — solo los primeros 8 chars son seguros para debug
    return token


class RegistryHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # redirige al logger estándar
        logger.debug(fmt, *args)

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _client_ip(self) -> str:
        # Respeta X-Forwarded-For cuando KrakenD actúa como proxy
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/registry/join":
            self._send_json(404, {"error": "not_found"})
            return

        ip = self._client_ip()
        if not _check_rate_limit(ip):
            logger.warning("Rate limit excedido ip=%s", ip)
            self._send_json(429, {"error": "rate_limit_exceeded", "retry_after": _RATE_WINDOW})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        try:
            jsonschema.validate(body, _JOIN_SCHEMA, resolver=_RESOLVER)
        except jsonschema.ValidationError as exc:
            self._send_json(422, {"error": "schema_violation", "detail": exc.message})
            return

        node = body["node"]
        node_id: str = node["id"]
        region: str = node["region"]

        try:
            cluster_jwt = _issue_cluster_jwt(node_id, region)
        except RuntimeError as exc:
            logger.error("Error emitiendo JWT: %s", exc)
            self._send_json(500, {"error": "jwt_error"})
            return

        # Loguear solo los primeros 8 chars del token (nunca el token completo)
        logger.info(
            "cluster.jwt emitido node=%s region=%s prefix=%s... exp_in=%ds",
            node_id, region, cluster_jwt[:8], JWT_TTL,
        )
        self._send_json(200, {"cluster_jwt": cluster_jwt, "expires_in": JWT_TTL})


if __name__ == "__main__":
    port = int(os.environ.get("REGISTRY_PORT", "8081"))
    server = HTTPServer(("", port), RegistryHandler)
    logger.info("Registry server escuchando en :%d", port)
    server.serve_forever()
