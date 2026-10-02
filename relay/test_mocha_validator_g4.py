#!/usr/bin/env python3
"""
Tests G4/H7: jwt.decode() debe validar issuer explícitamente.

RED antes del fix: jwt.decode() sin issuer= acepta tokens con iss arbitrario
siempre que la firma sea válida con la clave pública registrada.

GREEN después del fix: issuer=self._issuer + options={"require": ["iss", "exp"]}
→ token con iss incorrecto o sin iss → MochaValidationError.
"""
import time
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import jwt

from mocha_validator import MochaValidator, MochaValidationError


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()
    return private_key, public_key


def _encode(private_key, payload: dict) -> str:
    return jwt.encode(payload, private_key, algorithm="RS256")


PRIVATE_KEY, PUBLIC_KEY = _make_keypair()
OTHER_PRIVATE_KEY, _ = _make_keypair()  # diferente clave privada

VALID_ISSUER = "https://auth.teremoqwow.dev"
VALID_PAYLOAD = {
    "iss": VALID_ISSUER,
    "exp": int(time.time()) + 3600,
    "node_id": "node-test-01",
    "region": "eu-west-1",
    "namespace_pattern": f"contrib/node-test-01/**",
}


def make_validator() -> MochaValidator:
    from cryptography.hazmat.primitives import serialization
    pem = PUBLIC_KEY.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return MochaValidator(public_key=pem, issuer=VALID_ISSUER)


# ── Tests RED→GREEN ────────────────────────────────────────────────────────────

def test_valid_token_accepted():
    """Token con iss correcto, exp válido y node_id → debe aceptarse."""
    validator = make_validator()
    token = _encode(PRIVATE_KEY, VALID_PAYLOAD)
    identity = validator.validate(token)
    assert identity.node_id == "node-test-01"
    assert identity.issuer == VALID_ISSUER


def test_wrong_issuer_rejected():
    """Token con iss diferente al configurado → MochaValidationError (H7)."""
    validator = make_validator()
    payload = {**VALID_PAYLOAD, "iss": "https://evil.example.com"}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError, match="inválido|issuer|iss"):
        validator.validate(token)


def test_missing_iss_rejected():
    """Token sin claim iss → MochaValidationError (require: iss)."""
    validator = make_validator()
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "iss"}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError):
        validator.validate(token)


def test_missing_exp_rejected():
    """Token sin claim exp → MochaValidationError (require: exp)."""
    validator = make_validator()
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "exp"}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError):
        validator.validate(token)


def test_expired_token_rejected():
    """Token expirado → MochaValidationError."""
    validator = make_validator()
    payload = {**VALID_PAYLOAD, "exp": int(time.time()) - 10}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError, match="expirado|inválido"):
        validator.validate(token)


def test_wrong_signature_rejected():
    """Token firmado con clave diferente → MochaValidationError."""
    validator = make_validator()
    token = _encode(OTHER_PRIVATE_KEY, VALID_PAYLOAD)
    with pytest.raises(MochaValidationError):
        validator.validate(token)


def test_token_without_node_id_rejected():
    """Token sin node_id ni sub → MochaValidationError."""
    validator = make_validator()
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k not in ("node_id",)}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError, match="node_id"):
        validator.validate(token)


def test_external_node_wrong_namespace_rejected():
    """Nodo externo (iss != issuer) con namespace incorrecto → MochaValidationError.

    Nota: con el fix H7, un token de iss externo es rechazado por PyJWT antes
    de llegar a _enforce_namespace_policy. Este test confirma que la cadena
    de validación completa rechaza el token.
    """
    validator = make_validator()
    payload = {**VALID_PAYLOAD, "iss": "https://partner.example.com", "namespace_pattern": "live/**"}
    token = _encode(PRIVATE_KEY, payload)
    with pytest.raises(MochaValidationError):
        validator.validate(token)


def test_no_public_key_raises():
    """Sin clave pública configurada → MochaValidationError inmediata."""
    validator = MochaValidator(public_key=None, issuer=VALID_ISSUER)
    # Asegurarse de que MOCHA_PUBLIC_KEY no esté en el entorno
    import os
    os.environ.pop("MOCHA_PUBLIC_KEY", None)
    with pytest.raises(MochaValidationError, match="MOCHA_PUBLIC_KEY"):
        validator.validate("fake.token.here")
