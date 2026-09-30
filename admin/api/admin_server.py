"""
Portal de Administrador — #147 (Fase 8-K)
Backend API FastAPI-compatible via Flask.
Requiere JWT RS256 con claim role=admin|superadmin.

Módulos: auth/roles, broadcasts, federación, DRM/rights,
         monetización, QoS, seguridad, feature flags.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Optional

import jwt
from flask import Flask, Response, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

ADMIN_ROLES = {"admin", "superadmin"}
OPERATOR_ROLES = {"admin", "superadmin", "operator"}
ANALYST_ROLES = {"admin", "superadmin", "operator", "analyst"}

# ── Auth ───────────────────────────────────────────────────────────────────────

def _load_public_key() -> str:
    path = os.environ.get("JWT_RS256_PUBLIC_KEY_PATH", "")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read()
    priv_path = os.environ.get("JWT_RS256_PRIVATE_KEY_PATH", "")
    if priv_path and os.path.exists(priv_path):
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, load_pem_private_key,
        )
        with open(priv_path, "rb") as f:
            priv = load_pem_private_key(f.read(), password=None)
        return priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    raise RuntimeError("JWT_RS256_PUBLIC_KEY_PATH no configurado")


def _require_role(*allowed_roles: str):
    """Devuelve (claims, None) o (None, error_response)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, (jsonify({"error": "Autenticación requerida"}), 401)
    try:
        claims = jwt.decode(auth[7:], _load_public_key(), algorithms=["RS256"])
    except Exception:
        return None, (jsonify({"error": "Token inválido o expirado"}), 401)
    if claims.get("role") not in allowed_roles:
        return None, (jsonify({"error": f"Requiere rol: {sorted(allowed_roles)}"}), 403)
    return claims, None


# ── Auditoría ─────────────────────────────────────────────────────────────────

_audit_log: list[dict] = []  # En prod: ClickHouse tabla audit_events


def _audit(claims: dict, action: str, detail: str = "") -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": claims.get("email", claims.get("sub", "?")),
        "role": claims.get("role"),
        "action": action,
        "detail": detail,
        "ip": request.remote_addr,
    }
    _audit_log.append(entry)
    logger.info("AUDIT %s %s %s", entry["actor"], action, detail)


# ── ClickHouse helper ─────────────────────────────────────────────────────────

def _ch_query(sql: str) -> list[dict]:
    base = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    db = os.environ.get("CLICKHOUSE_DB", "teremoqwow")
    params = urllib.parse.urlencode({"query": sql, "database": db, "default_format": "JSONEachRow"})
    try:
        with urllib.request.urlopen(f"{base}/?{params}", timeout=5) as r:
            return [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
    except Exception as exc:
        logger.warning("admin: ClickHouse: %s", exc)
        return []


# ── Redis helper ──────────────────────────────────────────────────────────────

_redis_client = None

def _redis():
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "")
        if url:
            try:
                import redis as _r
                c = _r.Redis.from_url(url, decode_responses=True)
                c.ping()
                _redis_client = c
            except Exception as exc:
                logger.warning("admin: Redis: %s", exc)
    return _redis_client


# ── MÓDULO: Broadcasts ─────────────────────────────────────────────────────────

# Estado en memoria (en prod: leer del relay API / ClickHouse)
_broadcasts: dict[str, dict] = {
    "anon/live1": {
        "id": "anon/live1",
        "status": "active",
        "bitrate_kbps": 8140,
        "viewers": 0,
        "uptime_s": 0,
        "encoder": "ffmpeg-testsrc2",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "killed": False,
    }
}


@app.route("/admin/broadcasts", methods=["GET"])
def list_broadcasts():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(list(_broadcasts.values())), 200


@app.route("/admin/broadcasts/kill", methods=["POST"])
def kill_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    broadcast_id = (request.get_json(silent=True) or {}).get("broadcast_id") or request.args.get("id", "")
    bcast_key = urllib.parse.unquote(broadcast_id)
    if bcast_key not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    _broadcasts[bcast_key]["status"] = "killed"
    _broadcasts[bcast_key]["killed"] = True
    _audit(claims, "kill_broadcast", bcast_key)
    # En prod: llamar a moq-relay API DELETE /broadcasts/{id}
    logger.info("admin: broadcast %s killed por %s", bcast_key, claims.get("email"))
    return jsonify({"status": "killed", "broadcast": bcast_key}), 200


@app.route("/admin/broadcasts/config", methods=["PATCH"])
def patch_broadcast():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    bcast_key = body.get("broadcast_id", "")
    if bcast_key not in _broadcasts:
        return jsonify({"error": "broadcast no encontrado"}), 404
    for field in ("bitrate_kbps", "gop_frames", "encoder"):
        if field in body:
            _broadcasts[bcast_key][field] = body[field]
    _audit(claims, "patch_broadcast", f"{bcast_key} {body}")
    return jsonify(_broadcasts[bcast_key]), 200


# ── MÓDULO: Federación ─────────────────────────────────────────────────────────

_pending_nodes: list[dict] = []  # nodos pendientes de aprobación


@app.route("/admin/federation/nodes", methods=["GET"])
def list_nodes():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify({"active": [], "pending": _pending_nodes}), 200


@app.route("/admin/federation/nodes/<node_id>/approve", methods=["POST"])
def approve_node(node_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    _pending_nodes[:] = [n for n in _pending_nodes if n.get("id") != node_id]
    _audit(claims, "approve_node", node_id)
    return jsonify({"status": "approved", "node_id": node_id}), 200


@app.route("/admin/federation/nodes/<node_id>/revoke", methods=["POST"])
def revoke_node(node_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            r.delete(f"federation:jwt:{node_id}")
        except Exception:
            pass
    _audit(claims, "revoke_node", node_id)
    return jsonify({"status": "revoked", "node_id": node_id}), 200


# ── MÓDULO: DRM / Rights ──────────────────────────────────────────────────────

@app.route("/admin/drm/subscriptions", methods=["GET"])
def list_subscriptions():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    r = _redis()
    subs = []
    if r:
        try:
            keys = r.keys("rights:*:plays")
            for key in keys[:50]:  # cap 50
                sub_id = key.split(":")[1]
                plays = int(r.get(key) or 0)
                subs.append({"subscription_id": sub_id, "plays_used": plays})
        except Exception:
            pass
    return jsonify(subs), 200


@app.route("/admin/drm/subscriptions/<sub_id>/reset", methods=["POST"])
def reset_subscription(sub_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            r.delete(f"rights:{sub_id}:plays")
        except Exception:
            pass
    _audit(claims, "reset_max_plays", sub_id)
    return jsonify({"status": "reset", "subscription_id": sub_id}), 200


@app.route("/admin/drm/subscriptions/<sub_id>/revoke", methods=["POST"])
def revoke_subscription_jwt(sub_id: str):
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    if r:
        try:
            # Invalidar tokens activos de este cliente
            r.set(f"revoked:sub:{sub_id}", "1", ex=86400 * 30)
        except Exception:
            pass
    _audit(claims, "revoke_jwt", sub_id)
    return jsonify({"status": "revoked", "subscription_id": sub_id}), 200


# ── MÓDULO: Monetización ──────────────────────────────────────────────────────

@app.route("/admin/monetization/stats", methods=["GET"])
def monetization_stats():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key or stripe_key.startswith("sk_test_replace"):
        return jsonify({
            "mrr_eur": 2900,
            "active_subscriptions": 3,
            "churn_rate_pct": 5.2,
            "dunning_count": 1,
            "source": "mock",
        }), 200
    try:
        import base64
        auth_hdr = base64.b64encode(f"{stripe_key}:".encode()).decode()
        req = urllib.request.Request(
            "https://api.stripe.com/v1/subscriptions?status=active&limit=100",
            headers={"Authorization": f"Basic {auth_hdr}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        return jsonify({
            "active_subscriptions": len(data.get("data", [])),
            "source": "stripe",
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/admin/monetization/events", methods=["GET"])
def stripe_events():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    # Mock de últimos eventos Stripe
    return jsonify([
        {"id": f"evt_mock_{i}", "type": "invoice.paid", "created": int(time.time()) - i * 3600,
         "data": {"object": {"amount_paid": 2900, "currency": "eur"}}}
        for i in range(1, 6)
    ]), 200


# ── MÓDULO: QoS ───────────────────────────────────────────────────────────────

@app.route("/admin/qos/alerts", methods=["GET"])
def qos_alerts():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    prom_url = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    try:
        with urllib.request.urlopen(f"{prom_url}/api/v1/alerts", timeout=5) as resp:
            data = json.loads(resp.read())
        alerts = data.get("data", {}).get("alerts", [])
        return jsonify({"alerts": alerts, "count": len(alerts)}), 200
    except Exception as exc:
        logger.warning("admin: Prometheus: %s", exc)
        return jsonify({"alerts": [], "count": 0, "error": str(exc)}), 200


@app.route("/admin/qos/latency", methods=["GET"])
def qos_latency():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    rows = _ch_query("""
        SELECT
            namespace,
            quantile(0.95)(toFloat64(timestamp_pts)) AS p95,
            count() AS samples
        FROM teremoqwow.telemetry_events
        WHERE toDateTime(timestamp_pts / 1000) >= now() - INTERVAL 15 MINUTE
        GROUP BY namespace
    """)
    return jsonify(rows if rows else [{"namespace": "anon/live1", "p95": 0, "samples": 0}]), 200


# ── MÓDULO: Seguridad ─────────────────────────────────────────────────────────

@app.route("/admin/security/rate-limit-hits", methods=["GET"])
def rate_limit_hits():
    claims, err = _require_role(*OPERATOR_ROLES)
    if err: return err
    r = _redis()
    hits = []
    if r:
        try:
            keys = r.keys("rl:*")
            for key in keys[:50]:
                ip = key.replace("rl:", "")
                count = int(r.get(key) or 0)
                ttl = r.ttl(key)
                hits.append({"ip": ip, "requests": count, "ttl_s": ttl})
        except Exception:
            pass
    hits.sort(key=lambda x: x.get("requests", 0), reverse=True)
    return jsonify(hits), 200


@app.route("/admin/security/rotate-secret", methods=["POST"])
def rotate_secret():
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    body = request.get_json(silent=True) or {}
    secret_type = body.get("type", "")
    if secret_type not in ("webhook", "jwt"):
        return jsonify({"error": "type debe ser 'webhook' o 'jwt'"}), 400
    new_secret = secrets.token_hex(32)
    _audit(claims, f"rotate_secret:{secret_type}", "redacted")
    return jsonify({
        "type": secret_type,
        "new_secret_preview": new_secret[:8] + "...",
        "action": "Actualiza la variable de entorno correspondiente y reinicia el servicio",
        "env_var": "WEBHOOK_SECRET" if secret_type == "webhook" else "JWT_RS256_PRIVATE_KEY_PATH",
    }), 200


# ── MÓDULO: Feature Flags ─────────────────────────────────────────────────────

_feature_flags: dict[str, bool] = {
    "ssai_enabled": False,
    "drm_soft_mode": False,
    "geo_blocking_global": True,
    "maintenance_mode": False,
}


@app.route("/admin/flags", methods=["GET"])
def get_flags():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify(_feature_flags), 200


@app.route("/admin/flags/<flag>", methods=["PATCH"])
def set_flag(flag: str):
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    if flag not in _feature_flags:
        return jsonify({"error": f"flag desconocido: {flag}"}), 404
    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify({"error": "campo 'enabled' requerido"}), 400
    _feature_flags[flag] = bool(body["enabled"])
    _audit(claims, f"set_flag:{flag}", str(body["enabled"]))
    return jsonify({flag: _feature_flags[flag]}), 200


# ── MÓDULO: Auditoría ─────────────────────────────────────────────────────────

@app.route("/admin/audit", methods=["GET"])
def get_audit_log():
    claims, err = _require_role(*ADMIN_ROLES)
    if err: return err
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify(_audit_log[-limit:][::-1]), 200


# ── Health ─────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "admin-api", "status": "ok"}), 200


@app.route("/admin/me", methods=["GET"])
def admin_me():
    claims, err = _require_role(*ANALYST_ROLES)
    if err: return err
    return jsonify({k: claims[k] for k in ("sub", "email", "role") if k in claims}), 200


if __name__ == "__main__":
    port = int(os.environ.get("ADMIN_API_PORT", "9004"))
    app.run(host="0.0.0.0", port=port)
