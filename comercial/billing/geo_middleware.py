"""
Geo-blocking y ventanas de disponibilidad — #82
Valida claims JWT (blocked_regions, availability_windows) antes de autorizar la licencia DRM.
Importar en el servicio DRM (drm:8085) o en cualquier middleware que reciba X-Country-Code.

KrakenD inyecta el header X-Country-Code usando el módulo GeoIP antes de reenviar al backend.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _parse_dt(s: str) -> datetime:
    """Parsea una cadena RFC 3339 / ISO 8601 a datetime con tzinfo UTC si falta."""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fallback: reemplazar Z final por +00:00 (Python < 3.11)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_geo_access(country_code: str, claims: dict) -> tuple[bool, int]:
    """
    Valida si el acceso está permitido según los claims del JWT ya verificado.

    Args:
        country_code: Código ISO 3166-1 alpha-2 extraído del header X-Country-Code.
                      Debe ser inyectado por KrakenD, nunca tomado del cliente directamente.
        claims:       Dict de claims del JWT ya decodificado y verificado con RS256.

    Returns:
        (True, 200)  si el acceso está permitido.
        (False, 403) si la región está bloqueada o fuera de ventana de disponibilidad.
    """
    # 1. Geobloqueo por región
    blocked_regions: list[str] = claims.get("blocked_regions") or []
    if country_code and country_code.upper() in {r.upper() for r in blocked_regions}:
        logger.info("geo_blocked country=%s", country_code)
        return False, 403

    # 2. Ventanas de disponibilidad: si existen, debe haber al menos una activa ahora
    windows: list[dict] = claims.get("availability_windows") or []
    if windows:
        now = datetime.now(timezone.utc)
        in_window = any(
            _parse_dt(w["start_time"]) <= now <= _parse_dt(w["end_time"])
            for w in windows
        )
        if not in_window:
            logger.info("outside_availability_window country=%s", country_code)
            return False, 403

    return True, 200
