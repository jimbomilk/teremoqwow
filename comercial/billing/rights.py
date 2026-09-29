"""
Frequency Rights Management — #83
Contador max_plays por suscripción. Thread-safe.

En producción: sustituir _plays_store por Redis con INCR + TTL igual al período de suscripción.
Ejemplo Redis: INCR plays:{sub_id}  /  EXPIRE plays:{sub_id} <billing_cycle_seconds>
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# En prod: cliente Redis inyectado via DI (e.g. redis.Redis.from_url(os.environ["REDIS_URL"]))
_plays_store: dict[str, int] = {}
_lock = threading.Lock()


class RightsManager:
    """Controla cuántas reproducciones ha consumido cada suscripción en el período actual."""

    def record_play(self, subscription_id: str, max_plays: int) -> bool:
        """
        Registra una reproducción para la suscripción dada.

        Returns:
            True  si la reproducción está dentro del límite permitido.
            False si se ha superado max_plays → responder HTTP 403 al cliente.
        """
        with _lock:
            current = _plays_store.get(subscription_id, 0)
            if current >= max_plays:
                logger.info(
                    "max_plays_exceeded sub=%s plays=%d limit=%d",
                    subscription_id, current, max_plays,
                )
                return False
            _plays_store[subscription_id] = current + 1
            return True

    def get_play_count(self, subscription_id: str) -> int:
        with _lock:
            return _plays_store.get(subscription_id, 0)

    def reset(self, subscription_id: str) -> None:
        """Reinicia el contador — llamar en renovación de ciclo de facturación."""
        with _lock:
            _plays_store.pop(subscription_id, None)


# Instancia singleton — en prod: inyectar un RightsManager respaldado por Redis
_rights_manager = RightsManager()


def get_rights_manager() -> RightsManager:
    return _rights_manager
