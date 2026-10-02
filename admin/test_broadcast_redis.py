"""
Tests for E1-T2 (broadcast Redis helpers) and E1-T3 (relay_connections viewers).
Run with:
  PYTHONPATH="admin/api:relay:comercial/portal:${PYTHONPATH:-}" python3 -m pytest admin/test_broadcast_redis.py -v
"""
from __future__ import annotations

import os
import sys

# Ensure admin_server is importable without real JWT keys
os.environ.setdefault("JWT_RS256_PUBLIC_KEY_PATH", "")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

import admin_server  # noqa: E402

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def clear_broadcasts():
    admin_server._broadcasts.clear()
    admin_server._redis_client = None
    yield
    admin_server._broadcasts.clear()
    admin_server._redis_client = None


@pytest.fixture()
def client():
    admin_server.app.config["TESTING"] = True
    with admin_server.app.test_client() as c:
        yield c


# ── E1-T2: Redis helpers ──────────────────────────────────────────────────────

def test_bcast_set_and_get():
    """_bcast_set then _bcast_get returns identical data."""
    data = {"id": "test/stream1", "status": "active", "viewers": 0}
    admin_server._bcast_set("test/stream1", data)
    got = admin_server._bcast_get("test/stream1")
    assert got is not None
    assert got["id"] == "test/stream1"
    assert got["status"] == "active"


def test_bcast_list_returns_all():
    """After setting 2 broadcasts, _bcast_list returns both."""
    admin_server._bcast_set("a/one", {"id": "a/one", "status": "active", "viewers": 0})
    admin_server._bcast_set("b/two", {"id": "b/two", "status": "active", "viewers": 0})
    result = admin_server._bcast_list()
    ids = {item["id"] for item in result}
    assert "a/one" in ids
    assert "b/two" in ids
    assert len(result) == 2


def test_bcast_delete_removes():
    """_bcast_delete removes the entry; subsequent _bcast_get returns None."""
    admin_server._bcast_set("del/test", {"id": "del/test", "status": "active", "viewers": 0})
    assert admin_server._bcast_get("del/test") is not None
    admin_server._bcast_delete("del/test")
    assert admin_server._bcast_get("del/test") is None


def test_bcast_fallback_no_redis(monkeypatch):
    """Without Redis, helpers work from memory and raise no exceptions."""
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setattr(admin_server, "_redis_client", None)

    data = {"id": "fallback/test", "status": "active", "viewers": 5}
    admin_server._bcast_set("fallback/test", data)
    got = admin_server._bcast_get("fallback/test")
    assert got is not None
    assert got["viewers"] == 5

    items = admin_server._bcast_list()
    assert any(i["id"] == "fallback/test" for i in items)

    admin_server._bcast_delete("fallback/test")
    assert admin_server._bcast_get("fallback/test") is None


# ── E1-T3: relay_connections ──────────────────────────────────────────────────

def test_relay_connections_mock(client):
    """Mock /announced with 2 lines → relay_connections returns count: 2, online: True."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"anon/live1\nanon/live2"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        r = client.get("/admin/relay/connections")
    data = r.get_json()
    assert data["online"] is True
    assert data["count"] == 2
    assert len(data["broadcasts"]) == 2


def test_relay_connections_offline(client):
    """When relay is unreachable, response has online: False and no exception."""
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        r = client.get("/admin/relay/connections")
    assert r.status_code == 200
    data = r.get_json()
    assert data["online"] is False
    assert data["count"] == 0
