"""
Tests de seguridad G3 — TDD RED→GREEN

H1: TOCTOU en record_play (rights.py)        — GET+INCR no atómico → Lua script
H2: Open redirect en portal-session           — return_url sin validar → allowlist
H3: Rate-limit bypasseable via XFF            — XFF sin TRUSTED_PROXIES → IP directa
H4: Sin rate-limit en webhook_handler         — sin límite → sliding window 100/60s
"""
from __future__ import annotations

import threading
import time
import types
import uuid

import pytest


# ─── H1: TOCTOU en record_play ───────────────────────────────────────────────

class _AtomicMockRedis:
    """Mock Redis que expone register_script con semántica atómica (Lua-like)."""

    def __init__(self):
        self._store: dict[str, int] = {}
        self._lock = threading.Lock()

    def register_script(self, src: str):
        """Devuelve callable que ejecuta INCR+check en una sola sección crítica."""
        def _run(keys, args):
            with self._lock:
                key = keys[0]
                self._store[key] = self._store.get(key, 0) + 1
                current = self._store[key]
                max_plays = int(args[1])
                if current > max_plays:
                    return -1
                return current
        return _run

    def get(self, key):
        with self._lock:
            v = self._store.get(key)
            return str(v) if v is not None else None

    def ping(self):
        return True


class _RaceyMockRedis:
    """Mock Redis que simula el GET+INCR no atómico para demostrar TOCTOU.

    El GET duerme 50ms para dejar que otro thread también lea antes de que
    cualquiera haga INCR — reproduciendo la ventana de carrera original.
    """

    def __init__(self):
        self._store: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key):
        v = self._store.get(key)
        time.sleep(0.05)  # ventana TOCTOU: otro thread puede leer el mismo valor
        return str(v) if v is not None else None

    def pipeline(self):
        return _RaceyPipeline(self)

    def ping(self):
        return True


class _RaceyPipeline:
    def __init__(self, r: _RaceyMockRedis):
        self._r = r
        self._cmds: list[tuple[str, str]] = []

    def incr(self, key):
        self._cmds.append(("incr", key))
        return self

    def expire(self, key, ttl):
        return self

    def execute(self):
        results = []
        for cmd, key in self._cmds:
            if cmd == "incr":
                with self._r._lock:
                    self._r._store[key] = self._r._store.get(key, 0) + 1
                    results.append(self._r._store[key])
        return results


def test_h1_red_toctou_race_with_original_code(monkeypatch):
    """
    RED: el código original (GET+INCR) permite que 2 threads concurrentes ambos
    pasen cuando el contador está en max_plays-1.
    Este test FALLA con el código original porque ambos threads leen 0, pasan
    el check y luego ambos hacen INCR → ambos retornan True.
    """
    import rights as rights_module

    racey = _RaceyMockRedis()
    monkeypatch.setattr(rights_module, "_redis_client", racey)

    from rights import RightsManager
    rm = RightsManager()
    sub_id = f"sub-h1-red-{uuid.uuid4().hex[:8]}"
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        results.append(rm.record_play(sub_id, max_plays=1))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Con el fix (Lua), exactamente 1 pasa; sin el fix, ambos pasan.
    assert sum(results) == 1, (
        f"TOCTOU: expected exactly 1 True (Lua atómico), got {results}"
    )


def test_h1_green_lua_atomic_concurrency(monkeypatch):
    """
    GREEN: el Lua script atómico garantiza que solo 1 de 2 threads concurrentes
    pasa cuando el contador está en max_plays-1.
    """
    import rights as rights_module

    atomic = _AtomicMockRedis()
    monkeypatch.setattr(rights_module, "_redis_client", atomic)

    from rights import RightsManager
    rm = RightsManager()
    sub_id = f"sub-h1-green-{uuid.uuid4().hex[:8]}"
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        results.append(rm.record_play(sub_id, max_plays=1))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 1, f"Lua atómico: expected 1 True, got {results}"


def test_h1_memory_fallback_thread_safe():
    """El fallback en memoria debe seguir siendo correcto (con _mem_lock)."""
    import importlib
    import rights as rights_module

    # Forzar fallback: asegurarse de que _redis_client es None
    import rights
    original = rights._redis_client
    rights._redis_client = None

    rm = rights.RightsManager()
    sub_id = f"sub-h1-mem-{uuid.uuid4().hex[:8]}"

    # Limpiar store para este sub_id
    with rights._mem_lock:
        rights._plays_store.pop(sub_id, None)

    results: list[bool] = []
    barrier = threading.Barrier(5)

    def attempt():
        barrier.wait()
        results.append(rm.record_play(sub_id, max_plays=3))

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 3, f"Fallback memoria: expected 3 True, got {results}"
    rights._redis_client = original


# ─── H2: Open redirect en portal-session ────────────────────────────────────

def test_h2_allowed_return_url_direct():
    """Test unitario de _is_allowed_return_url (helper)."""
    from portal_server import _is_allowed_return_url

    # Permitidos
    assert _is_allowed_return_url("http://localhost") is True
    assert _is_allowed_return_url("http://localhost:5173/account") is True
    assert _is_allowed_return_url("http://127.0.0.1") is True
    assert _is_allowed_return_url("http://127.0.0.1:8080/path") is True
    assert _is_allowed_return_url("https://teremoqwow.dev/back") is True
    assert _is_allowed_return_url("https://app.teremoqwow.dev/account") is True

    # Rechazados
    assert _is_allowed_return_url("https://evil.com") is False
    assert _is_allowed_return_url("https://teremoqwow.dev.evil.com") is False
    assert _is_allowed_return_url("https://notteremoqwow.dev") is False
    assert _is_allowed_return_url("javascript:alert(1)") is False
    assert _is_allowed_return_url("") is False


def test_h2_red_open_redirect_endpoint(monkeypatch):
    """
    RED: sin validación, return_url=https://evil.com es aceptado (status ≠ 400).
    GREEN: con validación, debe devolver 400.
    """
    import portal_server

    # Mock auth para bypassear JWT
    monkeypatch.setattr(portal_server, "_require_auth", lambda: ({"sub": "cust_test"}, None))
    # Mock Stripe para evitar llamada real
    monkeypatch.setattr(portal_server, "_stripe_portal_session",
                        lambda cid, url: "https://billing.stripe.com/mock-portal")

    client = portal_server.app.test_client()

    # URL maliciosa → debe ser 400 (RED falla si no hay validación)
    resp = client.post("/account/portal-session",
                       json={"return_url": "https://evil.com"},
                       content_type="application/json")
    assert resp.status_code == 400, (
        f"H2 RED: open redirect debe retornar 400, got {resp.status_code}"
    )


def test_h2_green_allowed_url_passes(monkeypatch):
    """GREEN: URLs en la allowlist pasan correctamente."""
    import portal_server

    monkeypatch.setattr(portal_server, "_require_auth", lambda: ({"sub": "cust_test"}, None))
    monkeypatch.setattr(portal_server, "_stripe_portal_session",
                        lambda cid, url: "https://billing.stripe.com/mock-portal")

    client = portal_server.app.test_client()

    for good_url in [
        "http://localhost:5173/account",
        "https://teremoqwow.dev/back",
        "https://app.teremoqwow.dev/account",
    ]:
        resp = client.post("/account/portal-session",
                           json={"return_url": good_url},
                           content_type="application/json")
        assert resp.status_code == 200, (
            f"H2 GREEN: URL permitida {good_url!r} retornó {resp.status_code}"
        )


# ─── H3: Rate-limit bypasseable via X-Forwarded-For ─────────────────────────

def test_h3_red_xff_bypass_without_trusted_proxy(monkeypatch):
    """
    RED: sin TRUSTED_PROXIES configurado, X-Forwarded-For NO debe usarse.
    Si _client_ip devuelve el valor del header en vez de la IP real, es el bug.
    """
    import registry_server

    monkeypatch.setattr(registry_server, "_TRUSTED_PROXIES", set())

    handler = types.SimpleNamespace()
    handler.client_address = ("203.0.113.99", 54321)
    handler.headers = {"X-Forwarded-For": "127.0.0.1"}

    ip = registry_server.RegistryHandler._client_ip(handler)
    assert ip == "203.0.113.99", (
        f"H3 RED: sin proxy confiable, se debe usar IP real (203.0.113.99), got {ip!r}"
    )


def test_h3_green_xff_used_with_trusted_proxy(monkeypatch):
    """GREEN: cuando la IP de conexión está en TRUSTED_PROXIES, XFF se usa."""
    import registry_server

    monkeypatch.setattr(registry_server, "_TRUSTED_PROXIES", {"10.0.0.1"})

    handler = types.SimpleNamespace()
    handler.client_address = ("10.0.0.1", 12345)
    handler.headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}

    ip = registry_server.RegistryHandler._client_ip(handler)
    assert ip == "203.0.113.5", (
        f"H3 GREEN: proxy confiable, debe usar primer XFF (203.0.113.5), got {ip!r}"
    )


def test_h3_no_xff_header_returns_real_ip(monkeypatch):
    """Sin header XFF (aunque proxy confiable), devuelve la IP directa."""
    import registry_server

    monkeypatch.setattr(registry_server, "_TRUSTED_PROXIES", {"10.0.0.1"})

    handler = types.SimpleNamespace()
    handler.client_address = ("10.0.0.1", 12345)
    handler.headers = {}

    ip = registry_server.RegistryHandler._client_ip(handler)
    assert ip == "10.0.0.1"


# ─── H4: Sin rate-limit en webhook_handler ───────────────────────────────────

def test_h4_rate_limit_helper_allows_under_limit(monkeypatch):
    """100 requests por la misma IP deben pasar."""
    import webhook_handler

    webhook_handler._rate_store.clear()
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_MAX", 100)
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_WINDOW", 60)

    ip = "192.0.2.100"
    for i in range(100):
        assert webhook_handler._check_webhook_rate_limit(ip) is True, (
            f"H4: request #{i + 1} debería pasar"
        )


def test_h4_rate_limit_helper_blocks_over_limit(monkeypatch):
    """La petición 101 debe ser rechazada (retorna False)."""
    import webhook_handler

    webhook_handler._rate_store.clear()
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_MAX", 100)
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_WINDOW", 60)

    ip = "192.0.2.101"
    for _ in range(100):
        webhook_handler._check_webhook_rate_limit(ip)

    assert webhook_handler._check_webhook_rate_limit(ip) is False, (
        "H4 RED: la petición 101 debe retornar False (bloqueada)"
    )


def test_h4_rate_limit_endpoint_returns_429(monkeypatch):
    """
    RED: sin rate-limit, >100 requests devuelven status ≠ 429.
    GREEN: el decorador bloquea con 429.
    """
    import webhook_handler

    webhook_handler._rate_store.clear()
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_WINDOW", 60)

    client = webhook_handler.app.test_client()

    # Primeras 2 peticiones: no 429 (fallarán por otros motivos — firma inválida → 400/500)
    for i in range(2):
        resp = client.post(
            "/v1/stripe/webhook",
            data=b"{}",
            headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bad"},
        )
        assert resp.status_code != 429, f"H4: petición #{i + 1} no debería ser 429"

    # Petición 3: debe ser 429
    resp = client.post(
        "/v1/stripe/webhook",
        data=b"{}",
        headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bad"},
    )
    assert resp.status_code == 429, (
        f"H4 RED: la petición 3 (sobre límite) debe retornar 429, got {resp.status_code}"
    )


def test_h4_sliding_window_resets_after_expiry(monkeypatch):
    """Tras expirar la ventana, la IP puede volver a hacer requests."""
    import webhook_handler

    webhook_handler._rate_store.clear()
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_WINDOW", 1)  # 1 segundo

    ip = "192.0.2.200"
    assert webhook_handler._check_webhook_rate_limit(ip) is True
    assert webhook_handler._check_webhook_rate_limit(ip) is True
    assert webhook_handler._check_webhook_rate_limit(ip) is False  # bloqueada

    time.sleep(1.1)  # ventana expira

    assert webhook_handler._check_webhook_rate_limit(ip) is True, (
        "H4: tras expirar la ventana, debe poder hacer requests de nuevo"
    )


def test_h4_rate_limit_per_ip_independent(monkeypatch):
    """El rate-limit es por IP: una IP agotada no afecta a otras."""
    import webhook_handler

    webhook_handler._rate_store.clear()
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_MAX", 1)
    monkeypatch.setattr(webhook_handler, "_RATE_LIMIT_WINDOW", 60)

    assert webhook_handler._check_webhook_rate_limit("10.0.0.1") is True
    assert webhook_handler._check_webhook_rate_limit("10.0.0.1") is False  # agotada

    # Otra IP no debe verse afectada
    assert webhook_handler._check_webhook_rate_limit("10.0.0.2") is True
