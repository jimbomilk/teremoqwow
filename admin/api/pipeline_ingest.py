#!/usr/bin/env python3
"""
Pipeline Ingest CLI (#214)

Lee observaciones JSON-lines de stdin, las valida contra schemas/admin/v1/pipeline-observation.json
y las escribe en Redis. Es la ÚNICA vía de escritura de observaciones (no hay endpoint HTTP).
VALIDA pero NO INTERPRETA: solo transporta hechos de llegada de datos; nunca calidad audiovisual.

Uso:  REDIS_URL=redis://... python pipeline_ingest.py < observaciones.jsonl

Códigos de salida (exit):
  0  todas las líneas válidas y guardadas
  1  alguna línea inválida (se informa en stderr con su nº de línea); las válidas SÍ se guardan
  2  Redis no disponible (sin REDIS_URL, no conecta o cae durante la escritura). Tiene prioridad
     sobre 1: no se puede afirmar que se guardó nada. No existe modo "validar sin persistir".
  3  error interno inesperado

Claves: pipeline:signal:<signal>:latest (última) y pipeline:signal:<signal>:history (≤1000).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pipeline_state import VALID_SIGNALS, parse_rfc3339

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INVALID_INPUT = 1
EXIT_REDIS_UNAVAILABLE = 2
EXIT_INTERNAL = 3

VALID_RESULTS = {"PASS", "FAIL", "UNKNOWN"}
REASON_MIN_LENGTH = 1
REASON_MAX_LENGTH = 300
FUTURE_THRESHOLD_SECONDS = 60
SIGNAL_HISTORY_MAX = 1000

ALLOWED_FIELDS = {"signal", "result", "observed_at", "reason", "metrics"}
METRIC_LIMITS = {  # campo: (mínimo, máximo|None)
    "bytes": (0, None), "objects": (0, None), "window_seconds": (1, 3600), "http_status": (100, 599),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Redis ─────────────────────────────────────────────────────────────────────

_redis_client = None


def _redis():
    """Cliente Redis o None si no hay REDIS_URL / no conecta."""
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "")
        if url:
            try:
                import redis as _r
                c = _r.Redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
                c.ping()
                _redis_client = c
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis connection failed: %s", exc)
    return _redis_client


# ── Validación (espejo del schema; el test la compara con jsonschema) ─────────

def _as_int(v: Any) -> Optional[int]:
    """Entero según JSON Schema: int (no bool) o float integral. Si no, None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _validate_observation(obs: Any, now: Optional[datetime] = None) -> tuple[bool, str]:
    if now is None:
        now = _now()
    if not isinstance(obs, dict):
        return False, "observation must be a JSON object"

    for key in ("signal", "result", "observed_at", "reason"):
        if key not in obs:
            return False, f"Missing required field: {key}"
    for key in obs:
        if key not in ALLOWED_FIELDS:
            return False, f"Extra field not allowed: {key}"

    if not isinstance(obs["signal"], str) or obs["signal"] not in VALID_SIGNALS:
        return False, "signal not in enum"
    if not isinstance(obs["result"], str) or obs["result"] not in VALID_RESULTS:
        return False, "result not in enum"

    observed_at = parse_rfc3339(obs["observed_at"])
    if observed_at is None:
        return False, "observed_at must be an RFC 3339 date-time with timezone"
    delta = (observed_at - now).total_seconds()
    if delta > FUTURE_THRESHOLD_SECONDS:
        return False, f"observed_at is {delta:.0f}s in the future (max {FUTURE_THRESHOLD_SECONDS}s)"

    reason = obs["reason"]
    if not isinstance(reason, str):
        return False, "reason must be string"
    if not (REASON_MIN_LENGTH <= len(reason) <= REASON_MAX_LENGTH):
        return False, f"reason length must be {REASON_MIN_LENGTH}..{REASON_MAX_LENGTH}"

    if "metrics" in obs:
        metrics = obs["metrics"]
        if not isinstance(metrics, dict):
            return False, "metrics must be object"
        for key, value in metrics.items():
            if key not in METRIC_LIMITS:
                return False, f"metrics: extra field {key}"
            lo, hi = METRIC_LIMITS[key]
            n = _as_int(value)
            if n is None or n < lo or (hi is not None and n > hi):
                return False, f"metrics.{key} must be an integer >= {lo}" + (f" and <= {hi}" if hi else "")
    return True, ""


def _normalize(obs: dict) -> dict:
    """Float integral → int en metrics (así se persiste siempre un entero)."""
    if isinstance(obs.get("metrics"), dict):
        obs = {**obs, "metrics": {k: _as_int(v) for k, v in obs["metrics"].items()}}
    return obs


# ── Escritura ─────────────────────────────────────────────────────────────────

class RedisWriteError(Exception):
    pass


def _write_to_redis(obs: dict, redis_client: Any) -> None:
    signal = obs["signal"]
    value = json.dumps(obs)
    try:
        pipe = redis_client.pipeline(transaction=True)
        pipe.set(f"pipeline:signal:{signal}:latest", value)
        pipe.lpush(f"pipeline:signal:{signal}:history", value)
        pipe.ltrim(f"pipeline:signal:{signal}:history", 0, SIGNAL_HISTORY_MAX - 1)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        raise RedisWriteError(str(exc)) from exc


def main() -> int:
    now = _now()
    redis_client = _redis()
    if redis_client is None:
        logger.error("Redis not available: nothing can be persisted (exit %d)", EXIT_REDIS_UNAVAILABLE)
        return EXIT_REDIS_UNAVAILABLE

    invalid = 0
    stored = 0
    try:
        for line_no, line in enumerate(sys.stdin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obs = json.loads(line)
            except (ValueError, RecursionError) as exc:
                print(f"Line {line_no}: Invalid JSON: {exc}", file=sys.stderr)
                invalid += 1
                continue
            ok, msg = _validate_observation(obs, now)
            if not ok:
                print(f"Line {line_no}: Validation error: {msg}", file=sys.stderr)
                invalid += 1
                continue
            try:
                _write_to_redis(_normalize(obs), redis_client)
            except RedisWriteError as exc:
                logger.error("Redis write failed at line %d: %s", line_no, exc)
                return EXIT_REDIS_UNAVAILABLE
            stored += 1
    except KeyboardInterrupt:
        return EXIT_INTERNAL
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error")
        return EXIT_INTERNAL

    if invalid:
        logger.error("%d invalid line(s); %d stored", invalid, stored)
        return EXIT_INVALID_INPUT
    logger.info("Stored %d observation(s)", stored)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
