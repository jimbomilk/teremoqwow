# QoS CHECK 3 — Integración del track MSF `catalog` (contrato para developer)

**Fecha**: 2026-10-11
**Estado**: 📐 Contrato definido, sin implementar. `schemas/` NO se toca.
**Relacionado**: [qos-pts-sync-gate.md](qos-pts-sync-gate.md), [docs/contracts.md](../../../docs/contracts.md) (§ MSF), `schemas/moq/msf/v1/`.

## 1. Estado real (hechos verificados en el repo)

- `qos/scripts/integration-test.sh` publica la media con `ffmpeg … | moqdev/moq:0.12.7 import ts` en
  `anon/live1` (`BROADCAST`). **Ese proceso es el único dueño de `anon/live1`**; su catálogo es el
  Hang `catalog.json` generado por `moq import`.
- `ProducerSession` (`comercial/producer-cli/src/producer-session.js`) publica `catalog.json` (Hang v2)
  y `catalog` (MSF draft-01) pero **no ingiere** el media de `moq import`. No puede sustituirlo hoy.
- `qos/lib/telemetry-publisher.mjs` crea hoy el broadcast `BROADCAST` (`createBroadcast`) para su track
  `telemetry`: es un segundo productor sobre el mismo path que `moq import`. **No hay evidencia de que
  el relay soporte dos productores del mismo broadcast**; este contrato elimina esa ambigüedad en el
  camino nuevo (no cambia el legacy mientras el flag esté `off`).
- `verify-pts-sync.sh` y `telemetry-consumer.mjs` no leen `catalog`: la telemetría se descubre por
  nombre fijo `telemetry`.

## 2. Decisión: broadcast hermano de metadatos + feature flag

Estrategia incremental elegida: **broadcast hermano `${BROADCAST}-meta` + flag `QOS_MSF_CATALOG`**.

Descartadas (con motivo):

| Opción | Motivo del descarte |
|---|---|
| Mismo broadcast, dos productores | Sin evidencia de soporte en relay; reintroduce dos dueños. **Prohibido** hasta que exista evidencia E2E explícita. |
| Solo path producer-cli | `ProducerSession` no ingiere el media de `moq import`; CHECK 3 no tendría vídeo. Queda como fase futura (§8). |
| Sidecar de ficheros (metadata en disco) | No ejercita el track `catalog` por el relay: no valida lo que se quiere validar. |

### Propiedad de broadcasts (invariante)

| Broadcast | Único dueño | Tracks |
|---|---|---|
| `BROADCAST` (`anon/live1`) | `moq import ts` (sin cambios) | media + Hang `catalog.json` |
| `QOS_META_BROADCAST` (`anon/live1-meta`) | **un** proceso sidecar QoS | `catalog` (MSF draft-01) + `telemetry` |

Reglas: `QOS_META_BROADCAST` **debe diferir** de `BROADCAST` y no puede estar anidado bajo él.
Si es igual o está anidado → `CATALOG_ERROR` (`reason=meta_broadcast_conflict`) antes de conectar.
La comparación es **por segmentos de path**, no por prefijo textual: se normalizan barras inicial/final y se
comparan segmentos (sensible a mayúsculas). Con `BROADCAST=anon/live1`:

| `QOS_META_BROADCAST` | Resultado |
|---|---|
| `anon/live1` | conflicto (igual) |
| `/anon/live1/` | conflicto (igual tras normalizar) |
| `anon/live1/meta` | conflicto (anidado: `BROADCAST` es prefijo por segmentos) |
| `anon/live1-meta` (default) | válido |
| `anon/live10-meta`, `anon/live10` | válido (prefijo textual, pero no por segmentos) |

El patrón público `anon/**` ya cubre `anon/live1-meta`
(conectar a la raíz `/`, como en `qos-pts-sync-gate.md`).

## 3. Variables de entorno

| Variable | Default | Significado |
|---|---|---|
| `QOS_MSF_CATALOG` | `off` | `off` \| `optional` \| `required`. |
| `QOS_META_BROADCAST` | `${BROADCAST}-meta` | Broadcast hermano del sidecar. |
| `QOS_CATALOG_TIMEOUT_SEC` | `10` | Espera máxima al primer objeto del track `catalog`. |
| `QOS_MEDIA_VIDEO_TRACK` / `QOS_MEDIA_AUDIO_TRACK` | `0.avc3` / `1.aac` | Nombres declarados en el catálogo MSF para la media de `BROADCAST`. |
| (existentes) `BROADCAST`, `MOQ_URL`, `WINDOW_SEC`, `THRESHOLD_MS`, `MIN_SAMPLES` | — | Sin cambios. |

Valor de `QOS_MSF_CATALOG` fuera del conjunto → exit 1 inmediato (`CATALOG_ERROR`, `reason=invalid_config`);
nunca se interpreta como `off`.

## 4. REQUIRED / OPTIONAL

- `off` (default): comportamiento actual **byte a byte** (publicador/consumidor sobre `BROADCAST`, nombre
  fijo `telemetry`). Es el modo de CI de `main` hasta cumplir la aceptación de §7.
- `optional`: se intenta el camino MSF. Catálogo **ausente** (timeout, sin announce) → se degrada al camino
  legacy con warning `[PTS-SYNC] WARN: catalog absent, legacy telemetry`, y `catalog_status=ABSENT` en el
  reporte auxiliar. Catálogo **presente pero inválido** → `CATALOG_ERROR` (no se degrada: un catálogo roto
  es un defecto, no una ausencia). Esto incluye un catálogo válido sin track `role=telemetry`
  (`no_telemetry_track`): el catálogo existe pero incumple el contrato, así que no hay degradación.
- `required`: catálogo ausente **o** inválido → `CATALOG_ERROR`. Sin degradación.

El flag solo gobierna el descubrimiento/validación; la comparación PTS (umbral 50 ms, `MIN_SAMPLES`) es la
de `qos-pts-sync-gate.md`.

## 5. Comportamiento del sidecar y del consumidor (rutas)

**Sidecar (publicador)** — `qos/lib/telemetry-publisher.mjs`, nuevos args `--meta-broadcast <path>` y
`--msf-catalog` (o módulo nuevo `qos/lib/msf-sidecar.mjs` que lo reutilice):

1. Crea **solo** `QOS_META_BROADCAST` (nunca `BROADCAST`) con tracks `catalog` y `telemetry`.
2. Publica un snapshot MSF draft-01 en `catalog` que cumple `schemas/moq/msf/v1/teremoqwow-profile.json`:
   - video/audio: `namespace=BROADCAST`, nombres de `QOS_MEDIA_*_TRACK`, `teremoqwow.container=legacy`;
   - telemetry: `namespace=QOS_META_BROADCAST`, `name=telemetry`, `role=telemetry`,
     `packaging=x-teremoqwow-json`, `timescale=90000`.
   - Reutilizar `comercial/producer-cli/src/msf-builder.js`. Si su API no admite namespaces distintos por
     track, extender el **builder** (no el schema: `track.namespace` ya es por track).
3. Publica el catálogo **antes** del primer evento de telemetría.

**Consumidor** — `qos/lib/telemetry-consumer.mjs`, nuevo `--catalog-mode off|optional|required`
y `--meta-broadcast`:

1. Suscribe `QOS_META_BROADCAST/catalog`, espera ≤ `QOS_CATALOG_TIMEOUT_SEC`.
2. Valida (§6). Descubre el track de telemetría **desde el catálogo** (`role=telemetry`), sin nombre
   hardcodeado, y lo consume en `track.namespace`.
3. Verifica contra la media real: lee el Hang `catalog.json` de `BROADCAST` y comprueba que los tracks
   video/audio declarados en el MSF existen.

`verify-pts-sync.sh` orquesta: con `off` no cambia nada; con `optional|required` arranca sidecar, consumidor,
y el exporter de media sigue sobre `BROADCAST` (`export ts`, sin cambios).

## 6. Validación del catálogo → `CATALOG_ERROR`

Cualquiera de estas condiciones, con `reason` en el log y en `catalog-status.json`:

| `reason` | Condición |
|---|---|
| `invalid_config` | Valor de flag inválido. |
| `meta_broadcast_conflict` | `QOS_META_BROADCAST` igual a `BROADCAST` o anidado bajo él (frontera de path, ver §2). |
| `absent` | Sin objeto en `QOS_CATALOG_TIMEOUT_SEC` (solo error en `required`; WARN+legacy en `optional`). |
| `malformed_json` | Objeto no parseable. |
| `schema_invalid` | No valida `teremoqwow-profile.json` (`version != "draft-01"` incluido). |
| `reserved_name` | Un track de contenido se llama `catalog`. |
| `duplicate_track` | `(namespace,name)` repetido (no expresable en JSON Schema, lo comprueba el consumidor). |
| `no_telemetry_track` | El catálogo (válido por schema) no declara ningún track `role=telemetry`. Error en `optional` y `required`; nunca `NO_DATA`. |
| `media_mismatch` | video/audio declarados no existen en el Hang `catalog.json` de `BROADCAST`, o este no existe. |
| `telemetry_unreachable` | El track `role=telemetry` está declarado pero no se puede suscribir (error de transporte/announce/track info). Si se suscribe y entrega < `MIN_SAMPLES` eventos, es `NO_DATA`, no este error. |

Validación con ajv sobre `schemas/moq/msf/v1/` (ya vendoreado en `comercial/producer-cli/artifacts/` y en
`schemas/`); **no** copiar el schema a `qos/`: leerlo desde `schemas/`.

## 7. Veredictos y exit codes

Orden de evaluación: config → catálogo → muestras → desviación.

| Veredicto | Condición | Exit |
|---|---|---|
| `PASS` | Catálogo OK (o `off`, o `optional`+`ABSENT` con degradación) y `samples ≥ MIN_SAMPLES` y `avg ≤ umbral` | 0 |
| `FAIL` | Catálogo OK y `samples ≥ MIN_SAMPLES` y `avg > umbral` | 1 |
| `NO_DATA` | Catálogo OK, track `role=telemetry` **declarado y alcanzable** (suscripción establecida), y `samples < MIN_SAMPLES` (incluye 0 eventos) | 1 |
| `CATALOG_ERROR` | Cualquier fila de §6 que no degrade | 1 |

Un `CATALOG_ERROR` **nunca** se reporta como `FAIL` ni `NO_DATA`, y nunca produce `pass=true`. Todos los
no-PASS siguen siendo rojo. Frontera: catálogo **sin** track de telemetría declarado → `CATALOG_ERROR`
(`no_telemetry_track`); track declarado pero inalcanzable → `CATALOG_ERROR` (`telemetry_unreachable`);
track declarado y alcanzable con pocas/cero muestras → `NO_DATA`.

Reporte: `pts-sync-report.json` mantiene su schema intacto (`pass=false` en todo no-PASS). El detalle va en
un fichero auxiliar **junto al reporte** `catalog-status.json`
(`{status: OK|ABSENT|ERROR, reason, mode, meta_broadcast, tracks:[…]}`), sin schema formal por ahora
(si se necesita en CI, nuevo contrato en `schemas/sync/v1/` y vuelve al Arquitecto). El resumen de
`integration-test.sh` imprime el veredicto textual (`PASS|FAIL|NO_DATA|CATALOG_ERROR`).

## 8. Aceptación (TDD y E2E)

**Unit/mutantes** (bash/py, sin relay; deben poder fallar y pasar):

1. `off` → ni se lee el flag MSF ni se arranca sidecar (regresión: salida idéntica a hoy).
2. Una prueba por cada `reason` de §6 → `CATALOG_ERROR`, exit 1, `pass=false`.
3. `optional`+ausente → degrada y puede dar PASS; `required`+ausente → `CATALOG_ERROR`.
4. Mutantes: catálogo con track telemetry declarado y alcanzable + 0 eventos (y + `MIN_SAMPLES-1`) → `NO_DATA`
   (no `CATALOG_ERROR`); catálogo sin track `role=telemetry` → `CATALOG_ERROR no_telemetry_track` (no `NO_DATA`);
   track declarado pero no suscribible → `CATALOG_ERROR telemetry_unreachable`; desviación > umbral → `FAIL`.
5. Mutante: telemetría publicada con nombre ≠ `telemetry` y declarada en el catálogo → debe descubrirse (PASS);
   si el consumidor tuviera el nombre hardcodeado, el test falla.
6. Mutantes de `meta_broadcast_conflict`: `QOS_META_BROADCAST` = `BROADCAST`, `/anon/live1/` y `anon/live1/meta` →
   `CATALOG_ERROR` sin llegar a publicar; `anon/live1-meta` y `anon/live10-meta` → aceptados (un comparador
   por prefijo textual haría fallar el segundo caso).

**E2E contra relay local** (extensión de la verificación nativa de `qos-pts-sync-gate.md`):

| # | Escenario | Esperado |
|---|---|---|
| E1 | `off` | CHECK 3 idéntico al actual |
| E2 | `required` + `moq import` en `anon/live1` + sidecar en `anon/live1-meta` | `PASS`; el relay no registra `unauthorized` ni `duplicate/conflict` en `anon/live1`; `moq import` sigue vivo toda la ventana |
| E3 | `required`, sidecar no arrancado | `CATALOG_ERROR reason=absent` |
| E4 | `optional`, sidecar no arrancado | `PASS` por camino legacy + WARN |
| E5 | `required`, catálogo con `video` inexistente en `BROADCAST` | `CATALOG_ERROR reason=media_mismatch` |
| E6 | `required`, catálogo con `telemetry` declarado, sidecar suscribible pero sin eventos | `NO_DATA` |
| E8 | `required`, catálogo válido sin track `role=telemetry` | `CATALOG_ERROR reason=no_telemetry_track` |
| E9 | `optional`, catálogo válido sin track `role=telemetry` | `CATALOG_ERROR reason=no_telemetry_track` (sin degradar) |
| E10 | `required`, `QOS_META_BROADCAST=anon/live10-meta` | Sin conflicto; `PASS` |
| E11 | `required`, `QOS_META_BROADCAST=anon/live1/meta` | `CATALOG_ERROR reason=meta_broadcast_conflict` |
| E7 | CHECK 1, 2 y 4 de `integration-test.sh` | Sin regresión con `required` activo |

**Promoción de `off` a `optional`/`required` por defecto**: solo tras E1–E11 verdes en CI en ≥ 3 ejecuciones
consecutivas. Hasta entonces el default es `off`.

## 9. Fuera de alcance / diferido

- Un único dueño con `ProducerSession` ingiriendo la media (fusionar `anon/live1` y `-meta`): requiere que
  `ProducerSession` ingiera el TS y evidencia E2E; entonces `QOS_META_BROADCAST` se retira. No antes.
- Migración del legacy telemetry (hoy en `BROADCAST`, ver §1) mientras el flag es `off`: se mantiene; queda en
  backlog como riesgo de doble productor para la auditoría de seguridad/robustez final.
- Los adaptadores reales siguen sin `pts_90khz` (ver `qos-pts-sync-gate.md`).
- Delta updates del catálogo, `packaging=loc`: fuera de alcance (ver `docs/contracts.md`).
- Ruta de rollback: `QOS_MSF_CATALOG=off`.
