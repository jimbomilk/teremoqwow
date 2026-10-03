"""Tests E4-T3/T4: API del motor de overlays."""
import json
import os
import sys
import time
import uuid

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("JWT_RS256_PUBLIC_KEY_PATH", "")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

import admin_server as srv  # noqa: E402

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization


@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(65537, 2048, default_backend())
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


@pytest.fixture(autouse=True)
def clear_state():
    srv._broadcasts.clear()
    srv._redis_client = None
    srv._audit_log.clear()
    yield
    srv._broadcasts.clear()
    srv._redis_client = None


def _make_token(role, priv_pem):
    import jwt
    return jwt.encode(
        {"sub": "test", "email": "test@t.com", "role": role, "exp": int(time.time()) + 3600},
        priv_pem,
        algorithm="RS256",
    )


@pytest.fixture
def client(rsa_keypair):
    srv.app.config["TESTING"] = True
    priv, pub = rsa_keypair
    with patch.object(srv, "_load_public_key", return_value=pub), \
         patch.object(srv, "_load_private_key", return_value=priv):
        with srv.app.test_client() as c:
            c._priv = priv
            c._pub = pub
            yield c


def _auth(client, role="operator"):
    return {"Authorization": f"Bearer {_make_token(role, client._priv)}"}


def test_list_templates_returns_12(client):
    r = client.get("/admin/overlays/templates", headers=_auth(client, "analyst"))
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 12


def test_get_template_metadata(client):
    r = client.get("/admin/overlays/templates/scoreboard-sport", headers=_auth(client, "analyst"))
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == "scoreboard-sport"
    assert "vars" in data


def test_get_template_unknown_returns_404(client):
    r = client.get("/admin/overlays/templates/nonexistent", headers=_auth(client, "analyst"))
    assert r.status_code == 404


def test_publish_overlay_creates_entry(client):
    with patch.object(srv, "_redis", return_value=None):
        r = client.post(
            "/admin/overlays/publish",
            headers=_auth(client, "operator"),
            json={
                "broadcast_id": "anon/live1",
                "template_id": "logo-corner",
                "zone": "top-right",
                "duration_ms": 5000,
                "animation": "fade",
                "data": {"image_url": "https://example.com/logo.png"},
            },
        )
    assert r.status_code == 200
    data = r.get_json()
    assert "overlay_id" in data
    assert data["status"] == "active"


def test_publish_overlay_unknown_template_returns_404(client):
    with patch.object(srv, "_redis", return_value=None):
        r = client.post(
            "/admin/overlays/publish",
            headers=_auth(client, "operator"),
            json={
                "broadcast_id": "anon/live1",
                "template_id": "nonexistent",
                "zone": "top-right",
                "duration_ms": 5000,
                "data": {},
            },
        )
    assert r.status_code == 404


def test_publish_overlay_requires_operator(client):
    r = client.post(
        "/admin/overlays/publish",
        headers=_auth(client, "analyst"),
        json={
            "broadcast_id": "anon/live1",
            "template_id": "logo-corner",
            "zone": "top-right",
            "duration_ms": 0,
            "data": {},
        },
    )
    assert r.status_code == 403


def test_active_overlays_empty_no_redis(client):
    with patch.object(srv, "_redis", return_value=None):
        r = client.get("/admin/overlays/active", headers=_auth(client, "analyst"))
    assert r.status_code == 200
    assert r.get_json() == []


def test_unpublish_overlay(client):
    mock_redis = MagicMock()
    mock_redis.keys.return_value = []
    with patch.object(srv, "_redis", return_value=mock_redis):
        r = client.post(
            "/admin/overlays/unpublish",
            headers=_auth(client, "operator"),
            json={"overlay_id": str(uuid.uuid4()), "broadcast_id": "anon/live1"},
        )
    assert r.status_code == 200


def test_clear_all_overlays(client):
    mock_redis = MagicMock()
    mock_redis.keys.return_value = []
    with patch.object(srv, "_redis", return_value=mock_redis):
        r = client.post(
            "/admin/overlays/clear-all",
            headers=_auth(client, "operator"),
            json={"broadcast_id": "anon/live1"},
        )
    assert r.status_code == 200


def test_generate_llm_stub_returns_candidate(client):
    r = client.post(
        "/admin/overlays/generate-llm",
        headers=_auth(client, "operator"),
        json={
            "prompt": "Muestra el logo de Nike en la esquina superior derecha",
            "zone_hint": "top-right",
            "broadcast_id": "anon/live1",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "pending_review"
    assert "candidate" in data
    assert data["candidate"]["template_id"] == "logo-corner"


def test_generate_llm_empty_prompt(client):
    r = client.post(
        "/admin/overlays/generate-llm",
        headers=_auth(client, "operator"),
        json={"prompt": "", "zone_hint": "bottom-bar"},
    )
    assert r.status_code == 400


def test_generate_llm_html_in_prompt_rejected(client):
    r = client.post(
        "/admin/overlays/generate-llm",
        headers=_auth(client, "operator"),
        json={"prompt": "<script>alert(1)</script>", "zone_hint": "bottom-bar"},
    )
    assert r.status_code == 400


def test_generate_llm_prompt_too_long(client):
    r = client.post(
        "/admin/overlays/generate-llm",
        headers=_auth(client, "operator"),
        json={"prompt": "x" * 501},
    )
    assert r.status_code == 400


def test_overlay_history_empty(client):
    mock_redis = MagicMock()
    mock_redis.lrange.return_value = []
    with patch.object(srv, "_redis", return_value=mock_redis):
        r = client.get("/admin/overlays/history", headers=_auth(client, "analyst"))
    assert r.status_code == 200
    assert r.get_json() == []


def test_get_template_path_traversal_rejected(client):
    r = client.get("/admin/overlays/templates/../../etc", headers=_auth(client, "analyst"))
    assert r.status_code == 404


def test_publish_path_traversal_rejected(client):
    with patch.object(srv, "_redis", return_value=None):
        r = client.post(
            "/admin/overlays/publish",
            headers=_auth(client, "operator"),
            json={"broadcast_id": "anon/live1", "template_id": "../../etc", "zone": "top-right", "duration_ms": 0, "data": {}},
        )
    assert r.status_code == 404
