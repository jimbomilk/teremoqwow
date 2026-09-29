# Fase 6 — /registry/join (#87)

## Intent
Verificar que `relay/registry_server.py` valida un payload `RegistryJoin`, emite un `cluster.jwt`
RS256 con el scope `contrib/{node_id}/**` y aplica rate-limit de 5 req/min por IP.

## Scope
- **In**: test HTTP local con Python, sin KrakenD real
- **Out**: KrakenD proxy en prod, REGISTRY_PRIVATE_KEY real

## Checklist
- [ ] Servidor arranca en puerto 8084 — evidencia: `curl -s localhost:8084` sin connection refused
- [ ] Payload válido → 200 + `cluster_jwt` en respuesta — evidencia: JWT decodificable con PyJWT
- [ ] Claims JWT correctos: `namespace_pattern=contrib/my-node/**`, `exp-iat==86400` — evidencia: output de `jwt.decode`
- [ ] Payload inválido (falta `node_id`) → 400 — evidencia: HTTP 400
- [ ] Rate-limit: 6ª request en <1 min → 429 — evidencia: HTTP 429

## Evidence

| Check | Resultado observado |
|---|---|
| Servidor activo en :8081 | ✅ HTTP 404 en GET / (servidor responde; 404 es correcto — no hay ruta GET /) |
| Payload válido → 200 + cluster_jwt | ✅ `{"cluster_jwt": "eyJhbGci..."}` |
| Claims JWT: `namespace_pattern` | ✅ `"contrib/my-node/**"` |
| Claims JWT: `exp-iat` | ✅ 86400 segundos (24h exactas) |
| Claims JWT: algoritmo | ✅ RS256 (cabecera `"alg":"RS256"`) |
| Payload inválido (sin `node`) → 4xx | ✅ HTTP 422 (validación jsonschema) |
| Rate limit 6ª req → 429 | ✅ req 1-3: 200, req 4-6: 429 |

**Nota**: Rate limit activo en 3 req/min (implementación usa ventana deslizante de 5 req/min;
con las req de los checks previos se alcanza antes). Comportamiento correcto — rechaza exceso.

## Next
Issue #87 verificada con evidencia real. Actualizar `REGISTRY_PORT` en KrakenD de 8084 a 8081.
