"""
Frequency Rights Management — #83
Contador max_plays por suscripción respaldado por Redis.
TTL = 30 días por defecto (configurable via RIGHTS_TTL_DAYS).
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# TTL en días para el contador por suscripción (se renueva en cada INCR)
_RIGHTS_TTL = int(os.environ.get("RIGHTS_TTL_DAYS", "30")) * 86400

_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                redis_url = os.environ.get("REDIS_URL", "")
                if redis_url:
                    try:
                        import redis
                        _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
                        _redis_client.ping()
                        logger.info("rights: conectado a Redis %s", redis_url)
                    except Exception as exc:
                        logger.warning("rights: Redis no disponible (%s), usando memoria", exc)
                        _redis_client = None
    return _redis_client


# Fallback en memoria cuando Redis no está disponible
_plays_store: dict[str, int] = {}
_mem_lock = threading.Lock()


_LUA_RECORD_PLAY = """
local current = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
if tonumber(ARGV[2]) and current > tonumber(ARGV[2]) then return -1 end
return current
"""


class RightsManager:
    """Controla cuántas reproducciones ha consumido cada suscripción."""

    def record_play(self, subscription_id: str, max_plays: int) -> bool:
        key = f"rights:{subscription_id}:plays"
        r = _get_redis()
        if r is not None:
            try:
                script = r.register_script(_LUA_RECORD_PLAY)
                result = script(keys=[key], args=[_RIGHTS_TTL, max_plays])
                if result == -1:
                    logger.info("max_plays_exceeded sub=%s limit=%d",
                                subscription_id, max_plays)
                    return False
                return True
            except Exception as exc:
                logger.error("rights: Redis error en record_play: %s", exc)
        # fallback memoria
        with _mem_lock:
            current = _plays_store.get(subscription_id, 0)
            if current >= max_plays:
                return False
            _plays_store[subscription_id] = current + 1
            return True

    def get_play_count(self, subscription_id: str) -> int:
        key = f"rights:{subscription_id}:plays"
        r = _get_redis()
        if r is not None:
            try:
                return int(r.get(key) or 0)
            except Exception:
                pass
        with _mem_lock:
            return _plays_store.get(subscription_id, 0)

    def reset(self, subscription_id: str) -> None:
        """Reinicia el contador — llamar en renovación de ciclo de facturación."""
        key = f"rights:{subscription_id}:plays"
        r = _get_redis()
        if r is not None:
            try:
                r.delete(key)
                return
            except Exception:
                pass
        with _mem_lock:
            _plays_store.pop(subscription_id, None)


_rights_manager = RightsManager()


def get_rights_manager() -> RightsManager:
    return _rights_manager
