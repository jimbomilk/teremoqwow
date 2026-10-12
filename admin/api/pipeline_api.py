"""
Pipeline API (#214) — acceso a Redis, historial, validación de bodies y rutas.

admin_server.py solo registra el Blueprint (`create_blueprint`); aquí vive toda la lógica.
SIN Docker ni subprocess (admin-api no tiene ni debe tener el socket de Docker).
No existe ninguna ruta HTTP que escriba observaciones: solo la CLI pipeline_ingest.py
(con acceso a Redis) las escribe.

Claves Redis:
  pipeline:signal:<signal>:latest   última observación (la escribe pipeline_ingest)
  pipeline:state:v1                 estado persistido (last_transition_at / last_green_at)
  pipeline:history                  lista acotada a 1000 eventos, el más reciente primero
  pipeline:phase:<phase>:human      verificación humana
  pipeline:lock:*                   locks cortos (SET NX EX) contra carreras entre workers

Orden de validación en POST/DELETE: auth (401/403) → phase (404) → body (400) →
Redis (503) → estado (409).
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from flask import Blueprint, jsonify, request

import pipeline_state as ps

logger = logging.getLogger(__name__)

STATE_KEY = "pipeline:state:v1"
HISTORY_KEY = "pipeline:history"
LOCK_STATE_KEY = "pipeline:lock:state"
LOCK_HUMAN_PREFIX = "pipeline:lock:human:"
OBS_KEY = "pipeline:signal:{}:latest"
HUMAN_KEY = "pipeline:phase:{}:human"

HISTORY_MAX = 1000
LIMIT_DEFAULT = 100
LIMIT_MAX = 500
NOTE_MAX = 500
BODY_MAX_BYTES = 8192
LOCK_TTL_SECONDS = 10
LOCK_RETRIES = 3
LOCK_RETRY_SLEEP = 0.05


def _now() -> datetime:
    """Reloj del servidor (los tests lo sustituyen)."""
    return datetime.now(timezone.utc)


# ── Errores ───────────────────────────────────────────────────────────────────

class RedisUnavailable(Exception):
    """Redis ausente o fallando: la API responde 503 con details.status=UNKNOWN."""


class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        super().__init__(message)
        self.http_status, self.code, self.message = http_status, code, message


@contextmanager
def _redis_guard():
    """Cualquier excepción accediendo a Redis → RedisUnavailable (nunca un 500)."""
    try:
        yield
    except (ApiError, RedisUnavailable):
        raise
    except Exception as exc:  # noqa: BLE001 — redis.*, OSError, mocks…
        logger.warning("pipeline: Redis falló: %r", exc)
        raise RedisUnavailable(str(exc)) from exc


def _acquire(r, key: str) -> Optional[str]:
    token = uuid.uuid4().hex
    return token if r.set(key, token, nx=True, ex=LOCK_TTL_SECONDS) else None


def _release(r, key: str, token: Optional[str]) -> None:
    if not token:
        return
    try:  # best effort: el lock expira solo (EX); un fallo aquí no invalida lo ya escrito
        if r.get(key) == token:
            r.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline: no se pudo liberar %s: %r", key, exc)


# ── Lectura ───────────────────────────────────────────────────────────────────

def _loads(raw: Any) -> Any:
    if not isinstance(raw, (str, bytes)):
        return None
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None


def _valid_text(v: Any, limit: int = NOTE_MAX) -> bool:
    return isinstance(v, str) and len(v) <= limit


def clean_human(raw: Any) -> dict:
    """Registro humano de Redis → objeto conforme a humanVerification. Lo corrupto es NOT_VERIFIED."""
    d = _loads(raw)
    if not isinstance(d, dict):
        return {"status": "NOT_VERIFIED"}
    if d.get("status") == "VERIFIED":
        by, at = d.get("verified_by"), d.get("verified_at")
        if not (isinstance(by, str) and by and ps.parse_rfc3339(at)):
            return {"status": "NOT_VERIFIED"}
        out = {"status": "VERIFIED", "verified_by": by, "verified_at": at}
        if _valid_text(d.get("note")) and d["note"]:
            out["note"] = d["note"]
        return out
    out = {"status": "NOT_VERIFIED"}
    by, at = d.get("last_revoked_by"), d.get("last_revoked_at")
    if d.get("status") == "NOT_VERIFIED" and isinstance(by, str) and by and ps.parse_rfc3339(at):
        out.update(last_revoked_by=by, last_revoked_at=at)
    return out


def get_snapshot(r, now: datetime) -> dict:
    """Evalúa observaciones + estado persistido y devuelve el snapshot (pipeline-snapshot.json).

    Persiste el nuevo estado y los eventos TRANSITION de forma atómica (MULTI/EXEC) bajo un
    lock corto; si otro worker ya está evaluando, devuelve la evaluación sin persistir.
    """
    with _redis_guard():
        token = _acquire(r, LOCK_STATE_KEY)
        try:
            signals = sorted(ps.VALID_SIGNALS)
            raw_obs = r.mget([OBS_KEY.format(s) for s in signals])
            observations = {s: _loads(v) for s, v in zip(signals, raw_obs) if v is not None}
            persisted = _loads(r.get(STATE_KEY))
            raw_humans = r.mget([HUMAN_KEY.format(p) for p in ps.PHASE_ORDER])
            humans = {p: clean_human(v) for p, v in zip(ps.PHASE_ORDER, raw_humans)}

            snapshot, new_state, events = ps.build_snapshot(observations, humans, persisted, now)

            if token:
                pipe = r.pipeline(transaction=True)
                pipe.set(STATE_KEY, json.dumps(new_state))
                if events:
                    pipe.lpush(HISTORY_KEY, *[json.dumps(e) for e in events])
                    pipe.ltrim(HISTORY_KEY, 0, HISTORY_MAX - 1)
                pipe.execute()
            return snapshot
        finally:
            _release(r, LOCK_STATE_KEY, token)


# ── Historial ─────────────────────────────────────────────────────────────────

_DIGITS = re.compile(r"^[0-9]{1,6}$")


def parse_history_params(args) -> tuple[Optional[str], Optional[datetime], int]:
    phase = args.get("phase")
    if phase is not None and phase not in ps.PHASES:
        raise ApiError(400, "VALIDATION_ERROR", "phase must be one of ingest|relay|player")
    since_raw = args.get("since")
    since = None
    if since_raw is not None:
        since = ps.parse_rfc3339(since_raw)
        if since is None:
            raise ApiError(400, "VALIDATION_ERROR", "since must be an RFC 3339 date-time with timezone")
    limit_raw = args.get("limit")
    limit = LIMIT_DEFAULT
    if limit_raw is not None:
        if not _DIGITS.match(limit_raw) or not (1 <= int(limit_raw) <= LIMIT_MAX):
            raise ApiError(400, "VALIDATION_ERROR", f"limit must be an integer between 1 and {LIMIT_MAX}")
        limit = int(limit_raw)
    return phase, since, limit


def _clean_event(raw: Any) -> Optional[dict]:
    d = _loads(raw)
    if not isinstance(d, dict):
        return None
    etype, phase = d.get("type"), d.get("phase")
    # isinstance(str) antes de `in`: un phase list/dict (no hashable) no debe lanzar TypeError
    if not isinstance(etype, str) or etype not in ("TRANSITION", "HUMAN_VERIFIED", "HUMAN_REVOKED"):
        return None
    if not isinstance(phase, str) or phase not in ps.PHASES:
        return None
    if ps.parse_rfc3339(d.get("at")) is None:
        return None
    out = {"type": d["type"], "phase": d["phase"], "at": d["at"]}
    for k in ("from_status", "to_status"):
        if d.get(k) in ps.TRANSPORT_STATUSES:
            out[k] = d[k]
    if isinstance(d.get("reason"), str):
        out["reason"] = d["reason"]
    if isinstance(d.get("actor"), str):
        out["actor"] = d["actor"]
    if _valid_text(d.get("note")):
        out["note"] = d["note"]
    return out


def get_history(r, phase: Optional[str], since: Optional[datetime], limit: int) -> dict:
    with _redis_guard():
        raw = r.lrange(HISTORY_KEY, 0, HISTORY_MAX - 1)
    events: list[dict] = []
    for item in raw:
        e = _clean_event(item)
        if e is None or (phase and e["phase"] != phase):
            continue
        if since and ps.parse_rfc3339(e["at"]) < since:
            continue
        events.append(e)
        if len(events) >= limit:
            break
    return {"events": events, "limit": limit, "retention_max_events": HISTORY_MAX}


# ── Verificación humana ───────────────────────────────────────────────────────

def parse_command_body(raw: bytes, field: str) -> Optional[str]:
    """Cuerpo de verify (`note`) / revoke (`reason`). Cualquier otra cosa → 400."""
    if len(raw) > BODY_MAX_BYTES:
        raise ApiError(400, "VALIDATION_ERROR", f"body exceeds {BODY_MAX_BYTES} bytes")
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise ApiError(400, "VALIDATION_ERROR", "body must be valid JSON") from None
    if not isinstance(data, dict):
        raise ApiError(400, "VALIDATION_ERROR", "body must be a JSON object")
    extra = sorted(set(data) - {field})
    if extra:
        raise ApiError(400, "VALIDATION_ERROR", f"only '{field}' is allowed; got: {', '.join(map(str, extra))}")
    value = data.get(field)
    if field in data and not _valid_text(value):
        raise ApiError(400, "VALIDATION_ERROR", f"{field} must be a string of at most {NOTE_MAX} characters")
    return value or None


def _human_locked(r, phase: str, action: Callable[[], dict]) -> dict:
    key = LOCK_HUMAN_PREFIX + phase
    token = None
    with _redis_guard():
        for _ in range(LOCK_RETRIES):
            token = _acquire(r, key)
            if token:
                break
            time.sleep(LOCK_RETRY_SLEEP)
        if not token:
            raise ApiError(409, "OPERATION_IN_PROGRESS", f"another operation on phase {phase} is in progress")
        try:
            return action()
        finally:
            _release(r, key, token)


def _commit(r, phase: str, human: dict, event: dict) -> None:
    pipe = r.pipeline(transaction=True)
    pipe.set(HUMAN_KEY.format(phase), json.dumps(human))
    pipe.lpush(HISTORY_KEY, json.dumps(event))
    pipe.ltrim(HISTORY_KEY, 0, HISTORY_MAX - 1)
    pipe.execute()


def verify(r, phase: str, actor: str, note: Optional[str], now: datetime) -> dict:
    at = ps.to_iso(now)

    def action() -> dict:
        if clean_human(r.get(HUMAN_KEY.format(phase)))["status"] == "VERIFIED":
            raise ApiError(409, "ALREADY_VERIFIED", f"phase {phase} is already verified")
        human = {"status": "VERIFIED", "verified_by": actor, "verified_at": at}
        event = {"type": "HUMAN_VERIFIED", "phase": phase, "at": at, "actor": actor}
        if note:
            human["note"] = event["note"] = note
        _commit(r, phase, human, event)
        return human

    return _human_locked(r, phase, action)


def revoke(r, phase: str, actor: str, reason: Optional[str], now: datetime) -> dict:
    at = ps.to_iso(now)

    def action() -> dict:
        if clean_human(r.get(HUMAN_KEY.format(phase)))["status"] != "VERIFIED":
            raise ApiError(409, "NOT_VERIFIED", f"phase {phase} is not verified")
        human = {"status": "NOT_VERIFIED", "last_revoked_by": actor, "last_revoked_at": at}
        event = {"type": "HUMAN_REVOKED", "phase": phase, "at": at, "actor": actor}
        if reason:
            event["reason"] = reason
        _commit(r, phase, human, event)
        return human

    return _human_locked(r, phase, action)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _error(http_status: int, code: str, message: str, details: Optional[dict] = None):
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return jsonify(body), http_status


def create_blueprint(
    require_role: Callable,
    audit: Callable,
    get_redis: Callable,
    analyst_roles,
    operator_roles,
) -> Blueprint:
    """Rutas finas. Auth/auditoría/Redis se inyectan desde admin_server (sin import circular)."""
    bp = Blueprint("pipeline", __name__)

    def redis_or_raise():
        with _redis_guard():
            r = get_redis()
        if r is None:
            raise RedisUnavailable("Redis not configured")
        return r

    def handle(roles, fn: Callable[[dict], Any]):
        claims, err = require_role(*roles)
        if err:
            resp, status = err
            msg = (resp.get_json(silent=True) or {}).get("error", "unauthorized")
            return _error(status, "UNAUTHORIZED" if status == 401 else "FORBIDDEN", str(msg))
        try:
            return fn(claims)
        except ApiError as e:
            return _error(e.http_status, e.code, e.message)
        except RedisUnavailable:
            return _error(503, "REDIS_UNAVAILABLE", "Pipeline state unavailable (Redis)", {"status": "UNKNOWN"})
        except Exception:  # noqa: BLE001
            logger.exception("pipeline: error inesperado")
            return _error(500, "INTERNAL_ERROR", "Unexpected error")

    def actor_of(claims: dict) -> str:
        return claims.get("email") or claims.get("sub") or "?"

    def check_phase(phase: str) -> None:
        if phase not in ps.PHASES:
            raise ApiError(404, "PHASE_NOT_FOUND", "unknown phase")

    @bp.get("/admin/pipeline/status")
    def pipeline_status():
        return handle(analyst_roles, lambda claims: (jsonify(get_snapshot(redis_or_raise(), _now())), 200))

    @bp.get("/admin/pipeline/history")
    def pipeline_history():
        def run(claims):
            phase, since, limit = parse_history_params(request.args)
            return jsonify(get_history(redis_or_raise(), phase, since, limit)), 200
        return handle(analyst_roles, run)

    @bp.post("/admin/pipeline/phases/<phase>/verification")
    def pipeline_verify(phase: str):
        def run(claims):
            check_phase(phase)
            note = parse_command_body(request.stream.read(BODY_MAX_BYTES + 1), "note")
            actor = actor_of(claims)
            human = verify(redis_or_raise(), phase, actor, note, _now())
            audit({**claims, "email": actor}, "VERIFY_PIPELINE_PHASE", f"phase={phase}")
            return jsonify({"phase": phase, "human": human}), 201
        return handle(operator_roles, run)

    @bp.delete("/admin/pipeline/phases/<phase>/verification")
    def pipeline_revoke(phase: str):
        def run(claims):
            check_phase(phase)
            reason = parse_command_body(request.stream.read(BODY_MAX_BYTES + 1), "reason")
            actor = actor_of(claims)
            human = revoke(redis_or_raise(), phase, actor, reason, _now())
            audit({**claims, "email": actor}, "REVOKE_PIPELINE_PHASE_VERIFICATION", f"phase={phase}")
            return jsonify({"phase": phase, "human": human}), 200
        return handle(operator_roles, run)

    return bp
