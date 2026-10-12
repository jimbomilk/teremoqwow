"""
Utilidades compartidas por los tests de Pipeline (#214). No contiene tests.

- Registry jsonschema con TODOS los schemas de schemas/admin/v1 y schemas/common/v1
  (resueltos por $id, sin red).
- Format checker `date-time` estricto (RFC 3339 con zona): jsonschema solo valida
  formatos si hay `rfc3339-validator`, que aquí no está instalado; sin esto
  `format: date-time` sería decorativo.
- Cliente Flask con Redis falso y JWT RS256 real.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("JWT_RS256_PUBLIC_KEY_PATH", "")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
API_DIR = HERE / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import jwt as pyjwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402
from referencing import Registry, Resource  # noqa: E402
from referencing.jsonschema import DRAFT202012  # noqa: E402

SCHEMA_DIRS = [REPO / "schemas" / "admin" / "v1", REPO / "schemas" / "common" / "v1"]
BASE = "https://teremoqwow.dev/schemas"
OBSERVATION_ID = f"{BASE}/admin/v1/pipeline-observation.json"
SNAPSHOT_ID = f"{BASE}/admin/v1/pipeline-snapshot.json"
HISTORY_ID = f"{BASE}/admin/v1/pipeline-history.json"
COMMAND_ID = f"{BASE}/admin/v1/pipeline-verification-command.json"
ERROR_ID = f"{BASE}/common/v1/error.json"

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)

_format_checker = FormatChecker()


@_format_checker.checks("date-time")
def _is_date_time(value):
    if not isinstance(value, str):
        return True  # el formato solo aplica a strings
    if not _RFC3339.match(value):
        return False
    try:
        datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def load_schemas() -> dict[str, dict]:
    out = {}
    for d in SCHEMA_DIRS:
        for p in sorted(d.glob("*.json")):
            doc = json.loads(p.read_text())
            out[doc["$id"]] = doc
    return out


def build_registry() -> Registry:
    reg = Registry()
    for sid, doc in load_schemas().items():
        reg = reg.with_resource(sid, Resource.from_contents(doc, default_specification=DRAFT202012))
    return reg


_REGISTRY = build_registry()
_SCHEMAS = load_schemas()


def validator(schema_id: str) -> Draft202012Validator:
    return Draft202012Validator(
        _SCHEMAS[schema_id], registry=_REGISTRY, format_checker=_format_checker
    )


def schema_errors(schema_id: str, instance) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in validator(schema_id).iter_errors(instance)]


# ── JWT / app ─────────────────────────────────────────────────────────────────

_KEYS = None


def keypair():
    global _KEYS
    if _KEYS is None:
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv = k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        pub = k.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        _KEYS = (priv, pub)
    return _KEYS


_TOKENS: dict = {}


def token(role: str, email: str | None = "ops@teremoqwow.dev", sub: str = "user-123") -> str:
    key = (role, email, sub)  # firmar RS256 cuesta ~120 ms aquí: se cachea
    if key not in _TOKENS:
        payload = {"sub": sub, "role": role, "exp": int(time.time()) + 3600}
        if email is not None:
            payload["email"] = email
        _TOKENS[key] = pyjwt.encode(payload, keypair()[0], algorithm="RS256")
    return _TOKENS[key]


def auth(role: str = "operator", **kw) -> dict:
    return {"Authorization": f"Bearer {token(role, **kw)}"}


def make_client(monkeypatch, redis):
    """Cliente Flask de admin_server con `redis` (o None = sin Redis) y clave pública de test.

    Todo se parchea con monkeypatch → se restaura al terminar cada test.
    """
    import admin_server

    admin_server.app.config["TESTING"] = True
    monkeypatch.setattr(admin_server, "_redis", lambda: redis)
    monkeypatch.setattr(admin_server, "_load_public_key", lambda: keypair()[1])
    monkeypatch.setattr(admin_server, "_audit_log", [])
    return admin_server.app.test_client()


# ── Observaciones ─────────────────────────────────────────────────────────────

ALL_SIGNALS = [
    "ingest.video", "ingest.audio", "ingest.data",
    "relay.public", "relay.announce", "relay.catalog", "relay.tracks",
    "player.http", "player.subscribe",
]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def observation(signal: str, result: str, at: datetime, reason: str = "test", metrics=None) -> dict:
    o = {"signal": signal, "result": result, "observed_at": iso(at), "reason": reason}
    if metrics is not None:
        o["metrics"] = metrics
    return o


def seed(r, obs: dict) -> None:
    """Inyecta una observación en Redis tal y como lo hace pipeline_ingest."""
    r.seed(f"pipeline:signal:{obs['signal']}:latest", json.dumps(obs))


def seed_all(r, at: datetime, results: dict[str, str] | None = None, default: str = "PASS") -> None:
    results = results or {}
    for s in ALL_SIGNALS:
        seed(r, observation(s, results.get(s, default), at, reason=f"{s} {results.get(s, default)}"))


T0 = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def plus(seconds: float, base: datetime = T0) -> datetime:
    return base + timedelta(seconds=seconds)
