#!/usr/bin/env python3
"""
mocha_validator.py — issue #90 (stub)
Validador de tokens MOCHA que mapea permisos a namespaces MoQT.
Stub estructural; la implementación real requiere el SDK MOCHA definitivo.
"""
import fnmatch
import logging
import os
import time
from dataclasses import dataclass

import jwt  # PyJWT >= 2.0

logger = logging.getLogger(__name__)

# Namespaces prohibidos para nodos federados externos
_EXTERNAL_DENY_PREFIXES = ("anon/", "live/", "admin/")


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    region: str
    namespace_pattern: str
    issuer: str
    expires_at: int


class MochaValidationError(Exception):
    pass


class MochaValidator:
    """
    Valida tokens MOCHA y resuelve el namespace MoQT permitido para el nodo.
    Carga la clave pública desde MOCHA_PUBLIC_KEY (PEM) o MOCHA_JWKS_URI.
    """

    def __init__(self, public_key: str | None = None, issuer: str | None = None):
        self._public_key = public_key or os.environ.get("MOCHA_PUBLIC_KEY")
        self._issuer = issuer or os.environ.get(
            "MOCHA_ISSUER", "https://auth.teremoqwow.dev"
        )

    def validate(self, token: str) -> NodeIdentity:
        """
        Valida el token MOCHA y devuelve la identidad del nodo.
        Lanza MochaValidationError si el token es inválido, expirado o
        si el namespace_pattern no cumple la política de mínimo privilegio.
        """
        if not self._public_key:
            raise MochaValidationError("MOCHA_PUBLIC_KEY no configurada")

        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={"require": ["iss", "exp"], "verify_exp": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise MochaValidationError("Token MOCHA expirado") from exc
        except jwt.InvalidTokenError as exc:
            raise MochaValidationError(f"Token MOCHA inválido: {exc}") from exc

        node_id = claims.get("node_id") or claims.get("sub")
        region = claims.get("region", "unknown")
        namespace_pattern = claims.get("namespace_pattern", "")
        issuer = claims.get("iss", "")
        exp = int(claims.get("exp", 0))

        if not node_id:
            raise MochaValidationError("Token sin node_id")

        self._enforce_namespace_policy(node_id, namespace_pattern, issuer)

        # Loguear solo el prefijo del token — nunca el token completo
        logger.info(
            "MOCHA token válido node=%s region=%s ns=%s prefix=%s...",
            node_id, region, namespace_pattern, token[:8],
        )
        return NodeIdentity(
            node_id=node_id,
            region=region,
            namespace_pattern=namespace_pattern,
            issuer=issuer,
            expires_at=exp,
        )

    def _enforce_namespace_policy(
        self, node_id: str, namespace_pattern: str, issuer: str
    ) -> None:
        """Aplica política de mínimo privilegio: contrib/{node_id}/** para externos."""
        is_internal = issuer == self._issuer

        if not is_internal:
            expected = f"contrib/{node_id}/**"
            if namespace_pattern != expected:
                raise MochaValidationError(
                    f"namespace_pattern '{namespace_pattern}' no permitido para nodo externo "
                    f"(esperado: '{expected}')"
                )
            for denied in _EXTERNAL_DENY_PREFIXES:
                if namespace_pattern.startswith(denied):
                    raise MochaValidationError(
                        f"namespace_pattern '{namespace_pattern}' denegado para nodo externo"
                    )

    def is_namespace_allowed(self, identity: NodeIdentity, namespace: str) -> bool:
        """Comprueba si el namespace concreto está dentro del patrón permitido."""
        return fnmatch.fnmatchcase(namespace, identity.namespace_pattern)

    def ttl_remaining(self, identity: NodeIdentity) -> int:
        """Segundos restantes hasta que el token expire. Negativo si ya caducó."""
        return identity.expires_at - int(time.time())
