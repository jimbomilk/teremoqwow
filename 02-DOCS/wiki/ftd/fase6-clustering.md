# Fase 6 — Clustering moq-relay (#86)

## Intent
Verificar que dos instancias de moq-relay:0.15.7 pueden federarse usando `--connect` TCP qmux,
de modo que un subscriber en relay-2 reciba datos publicados en relay-1.

## Scope
- **In**: test Docker con dos relays en la misma red, propagación de catalog y tracks
- **Out**: clustering QUIC (sólo TCP qmux disponible en el entorno WSL2), autenticación JWT entre relays (Fase 7)

## Checklist
- [ ] `test-cluster.sh` corregido con flags reales (`--connect tcp://relay-1:4444` en relay-2 como cliente, no `--cluster-*` que no existe)
- [ ] relay-1 arranca y responde en `/announced/` — evidencia: `curl http://relay-1:8090/announced/`
- [ ] relay-2 se conecta a relay-1 vía TCP qmux — evidencia: logs del relay-2 muestran `connecting peer=tcp://relay-1:4444` y `connected`
- [ ] Publicar en relay-1 y recibir en subscriber conectado a relay-2 — evidencia: `moq export ts` recibe bytes del broadcast

## Evidence

| Check | Resultado observado |
|---|---|
| test-cluster.sh corregido (flags reales) | ✅ `--cluster-*` eliminados; `--connect tcp://relay-1:4444` en relay-2 |
| relay-1 arranca y HTTP activo | ✅ Logs: `listening addr=[::]:8090 kind="http"` |
| relay-2 arranca y HTTP activo | ✅ Logs: `listening addr=[::]:8091 kind="http"` |
| relay-2 se conecta a relay-1 | ❌ `cluster initialized configured=false` — `--connect` no es un flag del relay, es del cliente `moq` |
| Propagación de broadcast relay-1→relay-2 | ❌ No se produce — sin clustering configurado el relay opera standalone |

**Limitación de entorno confirmada (2026-09-29)**:  
`moqdev/moq-relay:0.15.7` no expone clustering vía CLI. La imagen Docker no incluye la configuración de peers. El clustering real requiere compilar `moq-rs` con una configuración Rust que apunte a los peers — no es configurable en runtime en esta versión.

## Next
Para desbloquear el test real de clustering:
- Opción A: compilar `moq-rs` desde fuente con `[cluster.connect]` en `relay.toml` nativo (no el nuestro)
- Opción B: esperar imagen Docker de moq-relay que soporte `--cluster-peer` via CLI
- Opción C: usar dos relays con un `moq` cliente intermediario que re-publique los tracks (bridge manual)

**Issue #86 marcada como deuda técnica** por limitación de la imagen Docker upstream.
