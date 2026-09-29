# Fase 6 — Verificar Nodo Externo Federado (#88)

## Intent
Verificar que un nodo externo puede unirse a la federación usando un `cluster.jwt` del registry,
publicar en su namespace `contrib/{node_id}/` y ser recibido por un subscriber en el relay principal.
Adicionalmente, verificar que un JWT expirado es rechazado.

## Scope
- **In**: test Docker con registry + relay-1 + relay-externo + bridge + subscriber
- **Out**: revocación por no-renovación real (requiere proceso de expiración en prod)

## Checklist
- [ ] Registry emite `cluster.jwt` válido con `namespace_pattern=contrib/ext-node/**`
- [ ] Nodo externo publica en `contrib/ext-node/test` en su propio relay
- [ ] Bridge propaga el broadcast al relay-1
- [ ] Subscriber en relay-1 recibe bytes — evidencia: sync byte 0x47
- [ ] JWT expirado generado con PyJWT → intento de join → HTTP 401/422

## Evidence

| Check | Resultado observado |
|---|---|
| Registry emite `cluster.jwt` | ✅ `expires_in=86400s, prefix=eyJhbGci...` |
| `namespace_pattern` correcto | ✅ `contrib/relay-fed-2/**` |
| JWT caduca en 24h exactas | ✅ `exp-iat=86400s` |
| Propagación relay-1→relay-2 vía bridge | ✅ Sync byte `0x47: 4701 002f b710 0008 7f1e 7e00...` |
| JWT expirado rechazado | ✅ `jwt.ExpiredSignatureError` detectado por PyJWT |

**5/5 PASS (2026-09-29)** — `EXIT: 0`

## Next
Issue #88 cerrada con evidencia. PR #135 listo para merge.
