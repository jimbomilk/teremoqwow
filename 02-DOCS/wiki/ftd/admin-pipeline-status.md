# Admin — vista Pipeline con semáforos por fase (#214)

## Intent

Dar al operador una vista "Pipeline" en el admin de producción con 3 fases
(1 Ingesta vídeo/audio/data, 2 MoQ + relay, 3 Player + visualización). Cada fase
muestra DOS estados que nunca se mezclan:

- **Transporte automático** (`OK`/`DEGRADED`/`DOWN`/`BLOCKED`/`UNKNOWN`): solo afirma
  llegada de datos / disponibilidad de transporte.
- **Verificación humana audiovisual** (`VERIFIED`/`NOT_VERIFIED`): solo la fija una
  persona desde el admin. **La máquina nunca infiere calidad de vídeo/audio** (ni frames,
  códec, fps, ffprobe, navegador headless ni métricas semejantes). Decisión aprobada por
  el usuario.

## Scope

- In: contratos `schemas/admin/v1/pipeline-*.json`; API `GET /admin/pipeline/status`,
  `GET /admin/pipeline/history`, `POST|DELETE /admin/pipeline/phases/<phase>/verification`;
  estado + historial en Redis; CLI de ingesta de observaciones dentro de admin-api
  (`pipeline_ingest.py`, sin Docker); colector en el host de producción
  (`scripts/pipeline-collector.sh`) lanzado por workflow `pipeline-observe.yml` con los
  secrets de deploy; página admin `pipeline.js`.
- Out: track data en `anon/live1-meta` (→ #206, registrado como Next); seguridad (→ #195);
  ruleset/check QoS (task posterior); Docker socket o `docker run` en admin-api (prohibido).

## Contrato (resumen; fuente de verdad: `schemas/admin/v1/`)

- Señales con TTL explícito (segundos, expuesto en el snapshot):
  `ingest.video|audio|data` 1200; `relay.public|announce|catalog|tracks` 1200;
  `player.http|subscribe` 1200. El colector corre cada 10 min → 2 ciclos de margen.
- Estado de señal: `OK` (observación fresca con resultado `PASS`), `DOWN` (fresca, `FAIL`),
  `UNKNOWN` (nunca observada, caducada = `freshness: STALE`, o resultado `UNKNOWN`).
  `STALE` ≠ fallo real: se muestra como "caducada" y la fase sale `UNKNOWN`, no `DOWN`.
- Estado propio de fase (`own_status`): todas OK → `OK`; todas UNKNOWN → `UNKNOWN`;
  ninguna OK y alguna DOWN → `DOWN`; alguna OK y alguna no OK → `DEGRADED`.
- Dependencia: fase N+1 = `BLOCKED` si la N está `DOWN`, `UNKNOWN` o `BLOCKED`
  (`blocked_by` = fase causante; sigue exponiendo `own_status` y señales reales).
  **`DEGRADED` aguas arriba NO bloquea**: los datos fluyen parcialmente y la fase siguiente
  se evalúa con sus propias observaciones; su `reason` anota "aguas arriba degradada".
- Redis caído: GET status → 503 `REDIS_UNAVAILABLE` (envelope `common/v1/error.json`,
  `details.status: "UNKNOWN"`); la UI pinta todo `UNKNOWN`. Nunca verde simulado.
- Humano: operador = `email`/`sub` del JWT; timestamp del servidor; el cuerpo solo admite
  `note` (cualquier otro campo → 400). Revocar deja evento con quién/cuándo/motivo.
- Historial: lista Redis acotada a 1000 eventos (transiciones de fase, verificaciones,
  revocaciones); la API devuelve ≤ 500 (por defecto 100) y filtra por fase/`since`.

## Checklist

- [ ] Schemas + `scripts/validate-schemas.sh`
- [ ] developer: TDD API/estado/TTL/dependencias/persistencia/auth/trazabilidad
- [ ] developer: TDD UI (módulo puro de render sin DOM de vídeo)
- [ ] developer: colector + workflow (sin Docker en admin-api)
- [ ] refuter-correctness + refuter-tests en paralelo
- [ ] PR vinculado al proyecto #3, merge, deploy
- [ ] Verificación en producción (observaciones frescas reales, verificación humana con auth)

## Evidence

_(pendiente)_

## Next

- Track data en `anon/live1-meta` → #206 (no se implementa aquí).
- Ruleset "Protect main" y check "QoS integration": task posterior.
