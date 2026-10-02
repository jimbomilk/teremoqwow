"""
RED/GREEN test for C1 — privilege escalation via /auth/register (security audit G1).
Run RED:   python3 -m pytest comercial/auth/test_register_privilege_gate.py -v
Expected RED:  test_anon_cannot_register_admin/_superadmin FAIL (201 instead of 403)
Expected GREEN (post-fix): all tests pass.
"""
from __future__ import annotations

import os
import sys
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Throw-away RSA pair — no real secret material
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()

os.environ["JWT_RS256_PRIVATE_KEY"] = _PRIVATE_PEM
os.environ["AUTH_SEED_USERS"] = ""  # start with empty user store

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth_server  # noqa: E402

import pytest


def _make_token(role: str) -> str:
    import jwt as _jwt

    now = int(time.time())
    return _jwt.encode(
        {
            "sub": "test-id",
            "email": "t@t.com",
            "role": role,
            "plan": "dev",
            "namespace": "**",
            "iat": now,
            "exp": now + 900,
            "jti": "test-jti",
        },
        _PRIVATE_PEM,
        algorithm="RS256",
    )


@pytest.fixture(autouse=True)
def clear_users():
    auth_server._users.clear()
    auth_server._anon_rate_buckets.clear()
    yield
    auth_server._users.clear()
    auth_server._anon_rate_buckets.clear()


@pytest.fixture()
def client():
    auth_server.app.config["TESTING"] = True
    with auth_server.app.test_client() as c:
        yield c


# ── Gate: anon CANNOT claim privileged roles ──────────────────────────────────

def test_anon_cannot_register_admin(client):
    """Unauthenticated POST /auth/register with role=admin must return 403."""
    resp = client.post(
        "/auth/register",
        json={"email": "evil@t.com", "password": "secret", "role": "admin"},
    )
    assert resp.status_code == 403, (
        f"Expected 403, got {resp.status_code}. "
        "Privilege escalation via /auth/register is open!"
    )


def test_anon_cannot_register_superadmin(client):
    """Unauthenticated POST /auth/register with role=superadmin must return 403."""
    resp = client.post(
        "/auth/register",
        json={"email": "evil2@t.com", "password": "secret", "role": "superadmin"},
    )
    assert resp.status_code == 403


def test_invalid_token_cannot_register_admin(client):
    """Request with a tampered/invalid Bearer token must still return 403."""
    resp = client.post(
        "/auth/register",
        json={"email": "evil3@t.com", "password": "secret", "role": "admin"},
        headers={"Authorization": "Bearer notavalidtoken"},
    )
    assert resp.status_code == 403


# ── Gate: anon CAN register with unprivileged roles ───────────────────────────

def test_anon_can_register_viewer(client):
    resp = client.post(
        "/auth/register",
        json={"email": "viewer@t.com", "password": "secret", "role": "viewer"},
    )
    assert resp.status_code == 201


def test_anon_can_register_broadcaster(client):
    resp = client.post(
        "/auth/register",
        json={"email": "bc@t.com", "password": "secret", "role": "broadcaster"},
    )
    assert resp.status_code == 201


def test_anon_register_default_role(client):
    """No role field → defaults to viewer → 201."""
    resp = client.post(
        "/auth/register",
        json={"email": "default@t.com", "password": "secret"},
    )
    assert resp.status_code == 201


# ── Gate: admin-authenticated user CAN assign privileged roles ────────────────

def test_admin_can_register_admin(client):
    token = _make_token("admin")
    resp = client.post(
        "/auth/register",
        json={"email": "newadmin@t.com", "password": "secret", "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


def test_superadmin_can_register_admin(client):
    token = _make_token("superadmin")
    resp = client.post(
        "/auth/register",
        json={"email": "newadmin2@t.com", "password": "secret", "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


def test_broadcaster_token_cannot_register_admin(client):
    """A valid token with a non-privileged role must not be able to assign admin."""
    token = _make_token("broadcaster")
    resp = client.post(
        "/auth/register",
        json={"email": "sneaky@t.com", "password": "secret", "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

# ── E1-T1: Anonymous token endpoint ──────────────────────────────────────────

def test_anon_token_returns_jwt(client):
    """POST /auth/token-anonymous → 200, response contains decodable JWT."""
    resp = client.post("/auth/token-anonymous")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == auth_server.ANON_TOKEN_TTL
    # JWT must be decodable
    import jwt as _jwt
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key
    priv = load_pem_private_key(_PRIVATE_PEM.encode(), password=None)
    pub = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    decoded = _jwt.decode(data["access_token"], pub, algorithms=["RS256"])
    assert decoded["role"] == "viewer"


def test_anon_token_claims(client):
    """JWT from /auth/token-anonymous has role=viewer and anon=True."""
    resp = client.post("/auth/token-anonymous")
    assert resp.status_code == 200
    token = resp.get_json()["access_token"]
    import jwt as _jwt
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key
    priv = load_pem_private_key(_PRIVATE_PEM.encode(), password=None)
    pub = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    claims = _jwt.decode(token, pub, algorithms=["RS256"])
    assert claims["role"] == "viewer"
    assert claims["anon"] is True


def test_anon_cannot_use_admin_endpoint(client):
    """Anon viewer JWT must be rejected (403) on a privileged-role endpoint."""
    resp = client.post("/auth/token-anonymous")
    assert resp.status_code == 200
    token = resp.get_json()["access_token"]
    # /auth/register with role=admin requires PRIVILEGED_ROLES → 403 for viewer
    resp2 = client.post(
        "/auth/register",
        json={"email": "evil_anon@t.com", "password": "secret", "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 403


def test_anon_rate_limit(client):
    """11th request to /auth/token-anonymous from same IP must return 429."""
    for i in range(10):
        r = client.post("/auth/token-anonymous")
        assert r.status_code == 200, f"request {i+1} should be allowed"
    r11 = client.post("/auth/token-anonymous")
    assert r11.status_code == 429