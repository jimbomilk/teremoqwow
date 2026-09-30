"""
Stripe Billing webhook handler — #79
POST /v1/stripe/webhook (billing:8084)

Seguridad:
  - Verifica Stripe-Signature con HMAC-SHA256 antes de procesar cualquier payload.
  - Protección contra replay attacks (ventana 5 min).
  - JWT firmado exclusivamente con RS256 (nunca HS256).
  - No logueamos PII del payload.

Variables de entorno requeridas:
  STRIPE_WEBHOOK_SECRET       — secreto del webhook Stripe (whsec_...)
  JWT_RS256_PRIVATE_KEY_PATH  — path al fichero PEM con clave privada RSA (2048+ bits)
  MOQ_DEFAULT_NAMESPACE       — namespace MoQ por defecto (e.g. broadcasts/live1)
  JWT_TTL_SECONDS             — TTL del JWT en segundos (default: 86400)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import jwt  # PyJWT >= 2.0
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Métricas Prometheus — opcionales (no bloquean si prometheus_client no está instalado)
try:
    from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
    _WEBHOOK_REQUESTS = Counter("billing_webhook_requests_total", "Stripe webhook requests", ["status"])
    _DRM_LICENSES     = Counter("billing_drm_licenses_issued_total", "DRM licenses issued")
    _GEO_BLOCKED      = Counter("billing_geo_blocked_total", "Requests geo-blocked", ["country"])
    _PROMETHEUS_OK    = True
except ImportError:
    _PROMETHEUS_OK    = False

# Ventana anti-replay: rechazar eventos con timestamp > 5 min de antigüedad
_STRIPE_MAX_REPLAY_SEC = 300

# Idempotencia: set de event.id ya procesados (en prod: Redis con TTL 24h)
_processed_events: set[str] = set()

# Estado de suscripciones activas (en prod: PostgreSQL)
# sub_id -> {"customer_id": str, "active": bool}
_subscriptions: dict[str, dict] = {}

# Caché de clave privada RSA (cargada una sola vez)
_private_key_cache: Optional[bytes] = None


def _load_rsa_private_key() -> bytes:
    global _private_key_cache
    if _private_key_cache is None:
        key_path = os.environ["JWT_RS256_PRIVATE_KEY_PATH"]
        with open(key_path, "rb") as fh:
            _private_key_cache = fh.read()
    return _private_key_cache


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """
    Verifica Stripe-Signature con HMAC-SHA256 según la especificación Stripe.
    Incluye protección contra replay attacks (ventana 5 min).
    Retorna False ante cualquier anomalía; nunca lanza excepción.
    """
    try:
        parts: dict[str, str] = {}
        for segment in sig_header.split(","):
            k, _, v = segment.strip().partition("=")
            if k:
                parts[k] = v

        timestamp_str = parts.get("t", "")
        v1_sig = parts.get("v1", "")
        if not timestamp_str or not v1_sig:
            return False

        # Protección replay attack
        if abs(int(time.time()) - int(timestamp_str)) > _STRIPE_MAX_REPLAY_SEC:
            logger.warning("stripe_replay_rejected age_sec=%d", abs(int(time.time()) - int(timestamp_str)))
            return False

        signed_payload = timestamp_str.encode() + b"." + payload
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1_sig)
    except Exception:
        return False


def _emit_access_token(customer_id: str, subscription_id: str, namespace: str) -> str:
    """Emite JWT RS256 con claims AccessTokenClaims (schemas/drm/v1/access-token.json)."""
    now = int(time.time())
    claims = {
        "sub": customer_id,
        "namespace": namespace,
        "scopes": ["stream:read", "drm:license"],
        "content_ids": [],
        "availability_windows": [],
        "blocked_regions": [],
        "stripe_subscription_id": subscription_id,
        "iat": now,
        "exp": now + int(os.environ.get("JWT_TTL_SECONDS", "86400")),
    }
    return jwt.encode(claims, _load_rsa_private_key(), algorithm="RS256")


@app.route("/v1/stripe/webhook", methods=["POST"])
def stripe_webhook() -> tuple[Response, int] | Response:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET no configurado")
        return Response("Servidor no configurado", status=500)

    sig_header = request.headers.get("Stripe-Signature", "")
    if not sig_header:
        return Response("Missing Stripe-Signature", status=400)

    raw_body = request.get_data()
    if not _verify_stripe_signature(raw_body, sig_header, secret):
        return Response("Invalid signature", status=400)

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response("Invalid JSON", status=400)

    event_id: str = event.get("id", "")
    event_type: str = event.get("type", "")

    if not event_id:
        return Response("Missing event id", status=400)

    # Idempotencia: mismo event.id → responder 200 sin reemitir token
    if event_id in _processed_events:
        return jsonify({"status": "already_processed"}), 200

    obj: dict = event.get("data", {}).get("object", {})
    namespace = os.environ.get("MOQ_DEFAULT_NAMESPACE", "broadcasts/live1")

    if event_type in ("checkout.session.completed", "invoice.paid"):
        customer_id: str = obj.get("customer", "")
        subscription_id: str = obj.get("subscription", "")
        if not customer_id:
            return Response("Missing customer in event", status=422)

        token = _emit_access_token(customer_id, subscription_id, namespace)
        _subscriptions[subscription_id] = {"customer_id": customer_id, "active": True}
        _processed_events.add(event_id)
        # No logueamos el token ni datos PII del objeto Stripe
        logger.info("access_token_issued event_id=%s type=%s", event_id, event_type)
        return jsonify({"status": "ok", "token": token}), 200

    if event_type == "customer.subscription.deleted":
        subscription_id = obj.get("id", "")
        if subscription_id in _subscriptions:
            _subscriptions[subscription_id]["active"] = False
        _processed_events.add(event_id)
        logger.info("subscription_revoked event_id=%s", event_id)
        return jsonify({"status": "revoked"}), 200

    _processed_events.add(event_id)
    return jsonify({"status": "ignored"}), 200


@app.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    return jsonify({"status": "ok", "service": "billing"}), 200


@app.route("/metrics", methods=["GET"])
def metrics() -> tuple[Response, int]:
    if not _PROMETHEUS_OK:
        return Response("# prometheus_client no disponible\n", mimetype="text/plain"), 200
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8084)
