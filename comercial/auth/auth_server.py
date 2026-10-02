"""
Auth service — #143 (Fase 8-F)
POST /auth/register, /auth/login, /auth/refresh, /auth/logout, GET /auth/me
JWT RS256 con claims {sub, email, role, plan, namespace}.
Sesión: access token (15min) + refresh token en Redis (30d).
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
import uuid
from collections import defaultdict
from typing import Optional

import jwt
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins='*')  # dev only

ACCESS_TTL = int(os.environ.get("ACCESS_TOKEN_TTL", "900"))      # 15 min
REFRESH_TTL = int(os.environ.get("REFRESH_TOKEN_TTL", "2592000"))  # 30 días
ANON_TOKEN_TTL = 14400  # 4 h

_ANON_RATE_LIMIT = int(os.environ.get("ANON_RATE_LIMIT", "10"))
_ANON_RATE_WINDOW = 60  # seconds
_anon_rate_buckets: dict[str, list[float]] = defaultdict(list)

# Roles válidos del sistema
VALID_ROLES = {"viewer", "broadcaster", "admin", "superadmin"}
# Roles que solo un admin/superadmin autenticado puede asignar
PRIVILEGED_ROLES = {"admin", "superadmin"}


# ── Redis ──────────────────────────────────────────────────────────────────────

_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "")
        if url:
            try:
                import redis
                c = redis.Redis.from_url(url, decode_responses=True)
                c.ping()
                _redis_client = c
            except Exception as exc:
                logger.error("auth: Redis no disponible: %s", exc)
    return _redis_client


def _check_anon_rate_limit(ip: str) -> bool:
    """Sliding window 10 req/60 s por IP para /auth/token-anonymous."""
    r = _get_redis()
    if r is not None:
        try:
            key = f"anon_rl:{ip}"
            count = r.incr(key)
            if count == 1:
                r.expire(key, _ANON_RATE_WINDOW)
            return count <= _ANON_RATE_LIMIT
        except Exception:
            pass
    now = time.monotonic()
    _anon_rate_buckets[ip] = [t for t in _anon_rate_buckets[ip] if now - t < _ANON_RATE_WINDOW]
    if len(_anon_rate_buckets[ip]) >= _ANON_RATE_LIMIT:
        return False
    _anon_rate_buckets[ip].append(now)
    return True


# ── Usuarios (ClickHouse / en memoria para dev) ────────────────────────────────
# En prod: tabla ClickHouse o Postgres. Aquí: dict en memoria + seed desde .env.

_users: dict[str, dict] = {}


def _seed_users():
    """Carga usuarios seed desde variables de entorno para desarrollo."""
    seed = os.environ.get("AUTH_SEED_USERS", "")
    # Formato: "email:password:role,email2:password2:role2"
    for entry in seed.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            email, password, role = parts
            _users[email] = {
                "id": str(uuid.uuid4()),
                "email": email,
                "password_hash": _hash_password(password),
                "role": role if role in VALID_ROLES else "viewer",
                "plan": "dev",
                "namespace": "anon/**",
            }
    if not _users:
        # Admin por defecto en dev
        _users["admin@teremoqwow.dev"] = {
            "id": str(uuid.uuid4()),
            "email": "admin@teremoqwow.dev",
            "password_hash": _hash_password("dev-secret"),
            "role": "superadmin",
            "plan": "dev",
            "namespace": "**",
        }
        logger.info("auth: usuario seed admin@teremoqwow.dev creado (dev-secret)")


def _hash_password(password: str) -> str:
    salt = os.environ.get("AUTH_SALT", "teremoqwow-dev-salt")
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _verify_password(email: str, password: str) -> Optional[dict]:
    user = _users.get(email)
    if user and user["password_hash"] == _hash_password(password):
        return user
    return None


# ── JWT ────────────────────────────────────────────────────────────────────────

def _load_private_key() -> str:
    key = os.environ.get("JWT_RS256_PRIVATE_KEY")
    if key:
        return key
    path = os.environ.get("JWT_RS256_PRIVATE_KEY_PATH")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    raise RuntimeError("Define JWT_RS256_PRIVATE_KEY o JWT_RS256_PRIVATE_KEY_PATH")


def _issue_access_token(user: dict) -> str:
    now = int(time.time())
    claims = {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "plan": user["plan"],
        "namespace": user["namespace"],
        "iat": now,
        "exp": now + ACCESS_TTL,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, _load_private_key(), algorithm="RS256")


def _issue_refresh_token(user_id: str) -> str:
    token = secrets.token_urlsafe(48)
    r = _get_redis()
    if r:
        r.setex(f"refresh:{token}", REFRESH_TTL, user_id)
    return token


def _validate_refresh_token(token: str) -> Optional[str]:
    r = _get_redis()
    if r:
        return r.get(f"refresh:{token}")
    return None


def _revoke_refresh_token(token: str) -> None:
    r = _get_redis()
    if r:
        r.delete(f"refresh:{token}")


def _get_bearer_token() -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _verify_access_token(token: str) -> Optional[dict]:
    try:
        path = os.environ.get("JWT_RS256_PUBLIC_KEY_PATH", "")
        if path and os.path.exists(path):
            with open(path) as f:
                pub = f.read()
        else:
            # Extraer clave pública de la privada (solo para dev)
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            priv = load_pem_private_key(_load_private_key().encode(), password=None)
            pub = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        return jwt.decode(token, pub, algorithms=["RS256"])
    except Exception as exc:
        logger.debug("auth: token inválido: %s", exc)
        return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.route("/auth/register", methods=["POST"])
def register() -> tuple[Response, int]:
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    role = body.get("role", "viewer")

    if not email or not password:
        return jsonify({"error": "email y password requeridos"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"rol inválido, usa: {sorted(VALID_ROLES)}"}), 400

    # Gate: solo admin/superadmin autenticado puede asignar roles privilegiados
    if role in PRIVILEGED_ROLES:
        bearer = _get_bearer_token()
        claims = _verify_access_token(bearer) if bearer else None
        if not claims or claims.get("role") not in PRIVILEGED_ROLES:
            return jsonify({"error": "se requiere token de admin para asignar roles privilegiados"}), 403

    if email in _users:
        return jsonify({"error": "email ya registrado"}), 409

    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": _hash_password(password),
        "role": role,
        "plan": "free",
        "namespace": "anon/**",
    }
    _users[email] = user
    logger.info("auth: nuevo usuario %s role=%s", email, role)
    return jsonify({"id": user["id"], "email": email, "role": role}), 201


@app.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int]:
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    user = _verify_password(email, password)
    if not user:
        return jsonify({"error": "credenciales inválidas"}), 401

    access_token = _issue_access_token(user)
    refresh_token = _issue_refresh_token(user["id"])

    resp = jsonify({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TTL,
    })
    # Cookie HttpOnly para sesión web
    resp.set_cookie(
        "refresh_token", refresh_token,
        max_age=REFRESH_TTL, httponly=True, samesite="Strict", secure=False,  # secure=True en prod
    )
    return resp, 200


@app.route("/auth/refresh", methods=["POST"])
def refresh() -> tuple[Response, int]:
    token = request.cookies.get("refresh_token") or (request.get_json(silent=True) or {}).get("refresh_token")
    if not token:
        return jsonify({"error": "refresh_token requerido"}), 400

    user_id = _validate_refresh_token(token)
    if not user_id:
        return jsonify({"error": "refresh_token inválido o expirado"}), 401

    # Buscar usuario por id
    user = next((u for u in _users.values() if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "usuario no encontrado"}), 401

    _revoke_refresh_token(token)  # rotación del refresh token
    new_access = _issue_access_token(user)
    new_refresh = _issue_refresh_token(user["id"])

    resp = jsonify({"access_token": new_access, "token_type": "bearer", "expires_in": ACCESS_TTL})
    resp.set_cookie("refresh_token", new_refresh, max_age=REFRESH_TTL, httponly=True, samesite="Strict", secure=False)
    return resp, 200


@app.route("/auth/logout", methods=["POST"])
def logout() -> tuple[Response, int]:
    token = request.cookies.get("refresh_token")
    if token:
        _revoke_refresh_token(token)
    resp = jsonify({"status": "logged_out"})
    resp.delete_cookie("refresh_token")
    return resp, 200


@app.route("/auth/me", methods=["GET"])
def me() -> tuple[Response, int]:
    token = _get_bearer_token()
    if not token:
        return jsonify({"error": "Authorization header requerido"}), 401
    claims = _verify_access_token(token)
    if not claims:
        return jsonify({"error": "token inválido o expirado"}), 401
    return jsonify({k: claims[k] for k in ("sub", "email", "role", "plan", "namespace") if k in claims}), 200


@app.route("/auth/token-anonymous", methods=["POST"])
def token_anonymous() -> tuple[Response, int]:
    """Emite JWT de corta duración para viewers anónimos (no requiere registro)."""
    ip = request.remote_addr or "0.0.0.0"
    if not _check_anon_rate_limit(ip):
        return jsonify({"error": "rate limit excedido"}), 429
    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "viewer",
        "anon": True,
        "iat": now,
        "exp": now + ANON_TOKEN_TTL,
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(claims, _load_private_key(), algorithm="RS256")
    return jsonify({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ANON_TOKEN_TTL,
    }), 200


@app.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    return jsonify({"service": "auth", "status": "ok"}), 200


# ── Arranque ──────────────────────────────────────────────────────────────────

_seed_users()

if __name__ == "__main__":
    port = int(os.environ.get("AUTH_PORT", "9002"))
    app.run(host="0.0.0.0", port=port)
