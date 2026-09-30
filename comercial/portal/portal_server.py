"""
Portal cliente — #142 (Fase 8-G)
GET  /account/usage        — métricas de uso desde ClickHouse
GET  /account/invoices     — facturas desde Stripe API
GET  /account/api-keys     — API keys del cliente
POST /account/api-keys     — crear nueva key
DEL  /account/api-keys/:id — revocar key
GET  /account/subscription — plan actual y límites
POST /account/portal-session — crear sesión Stripe Customer Portal

Autenticación: Bearer JWT RS256 emitido por auth_server.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from typing import Optional

import jwt
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins='*')  # dev only

# ── Auth helper ────────────────────────────────────────────────────────────────

def _load_public_key() -> str:
    path = os.environ.get("JWT_RS256_PUBLIC_KEY_PATH", "")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    # Extraer de clave privada en dev
    priv_path = os.environ.get("JWT_RS256_PRIVATE_KEY_PATH", "")
    if priv_path and os.path.exists(priv_path):
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, load_pem_private_key,
        )
        with open(priv_path, "rb") as f:
            priv = load_pem_private_key(f.read(), password=None)
        return priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    raise RuntimeError("Configura JWT_RS256_PUBLIC_KEY_PATH o JWT_RS256_PRIVATE_KEY_PATH")


def _get_current_user() -> Optional[dict]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        return jwt.decode(token, _load_public_key(), algorithms=["RS256"])
    except Exception as exc:
        logger.debug("portal: token inválido: %s", exc)
        return None


def _require_auth():
    """Devuelve (claims, None) o (None, error_response)."""
    user = _get_current_user()
    if not user:
        return None, (jsonify({"error": "Autenticación requerida"}), 401)
    return user, None


# ── ClickHouse ────────────────────────────────────────────────────────────────

def _clickhouse_query(sql: str) -> list[dict]:
    """Ejecuta una query HTTP en ClickHouse y devuelve filas como dicts."""
    import urllib.request, urllib.parse, json as _json
    base = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    db = os.environ.get("CLICKHOUSE_DB", "teremoqwow")
    params = urllib.parse.urlencode({"query": sql, "database": db, "default_format": "JSONEachRow"})
    try:
        with urllib.request.urlopen(f"{base}/?{params}", timeout=5) as r:
            return [_json.loads(line) for line in r.read().decode().splitlines() if line.strip()]
    except Exception as exc:
        logger.warning("portal: ClickHouse error: %s", exc)
        return []


# ── Redis para API keys ───────────────────────────────────────────────────────

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
                logger.warning("portal: Redis no disponible: %s", exc)
    return _redis_client


# API keys en memoria como fallback
_api_keys_store: dict[str, list[dict]] = {}


def _get_api_keys(customer_id: str) -> list[dict]:
    r = _get_redis()
    if r:
        try:
            import json as _json
            raw = r.lrange(f"apikeys:{customer_id}", 0, -1)
            return [_json.loads(x) for x in raw]
        except Exception:
            pass
    return _api_keys_store.get(customer_id, [])


def _save_api_key(customer_id: str, key_meta: dict) -> None:
    import json as _json
    r = _get_redis()
    if r:
        try:
            r.rpush(f"apikeys:{customer_id}", _json.dumps(key_meta))
            return
        except Exception:
            pass
    _api_keys_store.setdefault(customer_id, []).append(key_meta)


def _delete_api_key(customer_id: str, key_id: str) -> bool:
    import json as _json
    r = _get_redis()
    if r:
        try:
            redis_key = f"apikeys:{customer_id}"
            items = [_json.loads(x) for x in r.lrange(redis_key, 0, -1)]
            original_len = len(items)
            items = [x for x in items if x.get("key_id") != key_id]
            if len(items) < original_len:
                r.delete(redis_key)
                for item in items:
                    r.rpush(redis_key, _json.dumps(item))
                return True
            return False
        except Exception:
            pass
    keys = _api_keys_store.get(customer_id, [])
    original_len = len(keys)
    _api_keys_store[customer_id] = [k for k in keys if k.get("key_id") != key_id]
    return len(_api_keys_store[customer_id]) < original_len


# ── Stripe ────────────────────────────────────────────────────────────────────

def _stripe_invoices(customer_id: str) -> list[dict]:
    """Obtiene facturas desde Stripe. Devuelve datos mock si no hay clave real."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key or stripe_key.startswith("sk_test_replace"):
        # Mock para dev
        return [
            {
                "invoice_id": f"in_mock_{i}",
                "amount_due": 2900 * i,
                "currency": "eur",
                "status": "paid" if i < 3 else "open",
                "period_start": f"2026-0{i}-01T00:00:00Z",
                "pdf_url": f"https://stripe.com/invoice/mock_{i}.pdf",
            }
            for i in range(1, 4)
        ]
    try:
        import urllib.request, urllib.parse, json as _json, base64
        auth = base64.b64encode(f"{stripe_key}:".encode()).decode()
        params = urllib.parse.urlencode({"customer": customer_id, "limit": "20"})
        req = urllib.request.Request(
            f"https://api.stripe.com/v1/invoices?{params}",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
        return [
            {
                "invoice_id": inv["id"],
                "amount_due": inv["amount_due"],
                "currency": inv["currency"],
                "status": inv["status"],
                "period_start": inv.get("period_start", ""),
                "pdf_url": inv.get("invoice_pdf", ""),
            }
            for inv in data.get("data", [])
        ]
    except Exception as exc:
        logger.error("portal: Stripe invoices error: %s", exc)
        return []


def _stripe_portal_session(customer_id: str, return_url: str) -> Optional[str]:
    """Crea sesión de Stripe Customer Portal. Devuelve URL."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key or stripe_key.startswith("sk_test_replace"):
        return f"https://billing.stripe.com/mock-portal?customer={customer_id}"
    try:
        import urllib.request, urllib.parse, json as _json, base64
        auth = base64.b64encode(f"{stripe_key}:".encode()).decode()
        body = urllib.parse.urlencode({
            "customer": customer_id,
            "return_url": return_url,
        }).encode()
        req = urllib.request.Request(
            "https://api.stripe.com/v1/billing_portal/sessions",
            data=body,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return _json.loads(r.read()).get("url")
    except Exception as exc:
        logger.error("portal: Stripe portal session error: %s", exc)
        return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.route("/account/usage", methods=["GET"])
def get_usage() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err

    customer_id = user.get("sub", "")
    # Consulta ClickHouse: agregados de telemetría de los últimos 30 días
    rows = _clickhouse_query(f"""
        SELECT
            toStartOfMonth(toDateTime(timestamp_pts / 1000)) AS period_start,
            count() AS total_requests,
            countIf(payload LIKE '%error%') AS error_requests,
            quantile(0.95)(toFloat64(timestamp_pts)) AS p95_latency_raw
        FROM teremoqwow.telemetry_events
        WHERE namespace LIKE '%{customer_id}%'
          AND toDateTime(timestamp_pts / 1000) >= now() - INTERVAL 30 DAY
        GROUP BY period_start
        ORDER BY period_start DESC
        LIMIT 1
    """)

    if rows:
        row = rows[0]
        return jsonify({
            "period_start": str(row.get("period_start", "")),
            "period_end": "",
            "total_requests": int(row.get("total_requests", 0)),
            "error_requests": int(row.get("error_requests", 0)),
            "p95_latency_ms": 0.0,  # ClickHouse devuelve epoch, no latencia directa
        }), 200

    # Sin datos: devolver estructura vacía (período actual)
    return jsonify({
        "period_start": time.strftime("%Y-%m-01T00:00:00Z"),
        "period_end": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_requests": 0,
        "error_requests": 0,
        "p95_latency_ms": 0.0,
    }), 200


@app.route("/account/invoices", methods=["GET"])
def get_invoices() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    return jsonify(_stripe_invoices(user.get("sub", ""))), 200


@app.route("/account/api-keys", methods=["GET"])
def list_api_keys() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    keys = _get_api_keys(user["sub"])
    # No devolver el valor real de la key, solo el prefijo
    safe = [{**k, "key_value": k.get("key_value", "")[:8] + "..."} for k in keys]
    return jsonify(safe), 200


@app.route("/account/api-keys", methods=["POST"])
def create_api_key() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    label = body.get("label", "default")[:64]
    scopes = body.get("scopes", ["stream:read"])
    key_value = f"tk_{secrets.token_urlsafe(32)}"
    key_meta = {
        "key_id": str(uuid.uuid4()),
        "label": label,
        "key_value": key_value,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_used_at": None,
        "scopes": scopes,
    }
    _save_api_key(user["sub"], key_meta)
    logger.info("portal: nueva API key para %s label=%s", user.get("email"), label)
    return jsonify(key_meta), 201  # única vez que se devuelve el valor completo


@app.route("/account/api-keys/<key_id>", methods=["DELETE"])
def delete_api_key(key_id: str) -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    if _delete_api_key(user["sub"], key_id):
        return jsonify({"status": "revoked", "key_id": key_id}), 200
    return jsonify({"error": "key no encontrada"}), 404


@app.route("/account/subscription", methods=["GET"])
def get_subscription() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    # Mock plan — en prod: consultar Stripe subscriptions
    return jsonify({
        "plan": user.get("plan", "free"),
        "status": "active",
        "current_period_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 30 * 86400)),
        "limits": {
            "max_broadcasts": 3 if user.get("plan") == "dev" else 1,
            "max_viewers_per_broadcast": 10000,
            "max_plays": 100,
        },
    }), 200


@app.route("/account/portal-session", methods=["POST"])
def create_portal_session() -> tuple[Response, int]:
    user, err = _require_auth()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    return_url = body.get("return_url", "http://localhost:5173/account")
    url = _stripe_portal_session(user.get("sub", ""), return_url)
    if not url:
        return jsonify({"error": "No se pudo crear sesión Stripe"}), 502
    return jsonify({"url": url}), 200


@app.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    return jsonify({"service": "portal", "status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORTAL_PORT", "9003"))
    app.run(host="0.0.0.0", port=port)
