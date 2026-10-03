"""
Tests Sprint 3 — E2-T1 (Quick Test, issue #168) + E2-T4 (Stop/Kill UX, issue #169).
Run with:
  PYTHONPATH="admin/api:relay:comercial/portal:${PYTHONPATH:-}" python3 -m pytest admin/test_quick_test.py -v --tb=short
"""
from __future__ import annotations

import os
import sys
import time
from unittest.mock import patch

os.environ.setdefault("JWT_RS256_PUBLIC_KEY_PATH", "")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

import admin_server  # noqa: E402

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt as pyjwt


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _make_token(private_pem: str, role: str, email: str = "test@teremoqwow.dev") -> str:
    payload = {"sub": email, "email": email, "role": role, "exp": int(time.time()) + 3600}
    return pyjwt.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture(autouse=True)
def clear_state():
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


# ── E2-T1: Quick Test ─────────────────────────────────────────────────────────

def test_quick_test_creates_broadcast(client, rsa_keypair):
    """POST /admin/broadcasts/quick-test → 200, broadcast_id y status active."""
    private_pem, public_pem = rsa_keypair
    token = _make_token(private_pem, "operator")
    with patch.object(admin_server, "_load_public_key", return_value=public_pem):
        r = client.post(
            "/admin/broadcasts/quick-test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
    assert r.status_code == 200
    data = r.get_json()
    assert "broadcast_id" in data
    assert data["status"] == "active"
    assert data["broadcast_id"].startswith("anon/test-")
    bcast = admin_server._bcast_get(data["broadcast_id"])
    assert bcast is not None
    assert bcast["status"] == "active"


def test_quick_test_limit_409(client, rsa_keypair):
    """Con 3 streams activos → POST /admin/broadcasts/quick-test → 409."""
    private_pem, public_pem = rsa_keypair
    token = _make_token(private_pem, "operator")
    for i in range(3):
        admin_server._bcast_set(f"anon/existing-{i}", {"id": f"anon/existing-{i}", "status": "active", "viewers": 0})
    with patch.object(admin_server, "_load_public_key", return_value=public_pem):
        r = client.post(
            "/admin/broadcasts/quick-test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
    assert r.status_code == 409
    data = r.get_json()
    assert "error" in data


def test_quick_test_requires_operator_role(client, rsa_keypair):
    """JWT con rol viewer → 403."""
    private_pem, public_pem = rsa_keypair
    token = _make_token(private_pem, "viewer")
    with patch.object(admin_server, "_load_public_key", return_value=public_pem):
        r = client.post(
            "/admin/broadcasts/quick-test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
    assert r.status_code == 403


# ── E2-T4: Stop/Kill status ───────────────────────────────────────────────────

def test_stop_inject_sets_stopped_status(client, rsa_keypair):
    """POST /admin/broadcasts/stop-inject → status 'stopped'."""
    private_pem, public_pem = rsa_keypair
    token = _make_token(private_pem, "operator")
    admin_server._bcast_set("anon/live1", {"id": "anon/live1", "status": "active", "viewers": 0})
    with patch.object(admin_server, "_load_public_key", return_value=public_pem):
        r = client.post(
            "/admin/broadcasts/stop-inject",
            headers={"Authorization": f"Bearer {token}"},
            json={"broadcast_id": "anon/live1"},
        )
    assert r.status_code == 200
    bcast = admin_server._bcast_get("anon/live1")
    assert bcast is not None
    assert bcast["status"] == "stopped"


def test_kill_sets_killed_status(client, rsa_keypair):
    """POST /admin/broadcasts/kill → status 'killed' y killed=True."""
    private_pem, public_pem = rsa_keypair
    token = _make_token(private_pem, "operator")
    admin_server._bcast_set("anon/live1", {"id": "anon/live1", "status": "active", "viewers": 0, "killed": False})
    with patch.object(admin_server, "_load_public_key", return_value=public_pem):
        r = client.post(
            "/admin/broadcasts/kill",
            headers={"Authorization": f"Bearer {token}"},
            json={"broadcast_id": "anon/live1"},
        )
    assert r.status_code == 200
    bcast = admin_server._bcast_get("anon/live1")
    assert bcast is not None
    assert bcast["status"] == "killed"
    assert bcast["killed"] is True
