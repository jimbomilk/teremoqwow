# Fase 1 — track de datos sintéticos permanente (#206)

## Intent

Completar la Fase 1 (ingesta) con un track de datos permanente que emita ~1 Hz en el
broadcast HERMANO `anon/live1-meta` y que el observador Pipeline mida de verdad
(`ingest.data`). La Fase 1 solo es OK cuando vídeo, audio Y data están frescos.
La máquina afirma únicamente llegada de datos/transporte; nunca calidad audiovisual.

## Scope

- In: schema `schemas/media/v1/meta-heartbeat.json`; servicio permanente
  `meta-publisher` (Node, `@moq/net` fijado, imagen propia con lockfile) en
  `docker-compose.prod.yml`; modo `observe` del mismo ejecutable; integración en
  `scripts/pipeline-collector.sh`/`pipeline_obs.py`; diagnóstico en `prod-diagnostics`;
  paso de build/restart en `deploy.yml`; fix del scheduling de `pipeline-observe` (#220).
- Out: segundo productor en `anon/live1` (prohibido); ruleset/QoS; DRM; overlays;
  monetización; calidad automática A/V; seguridad (→ #195); schemas/README.md y
  `validate-schemas.sh` (con cambios locales ajenos, no se tocan).

## Contrato (decidido por el Arquitecto)

- Broadcast `anon/live1-meta`, track `heartbeat`. Un único dueño: el servicio
  `meta-publisher`. Nadie más publica ahí (ni admin-api ni docker run ad hoc).
- Un grupo MoQ por evento, un frame por grupo, cuerpo = JSON UTF-8 conforme a
  `meta-heartbeat.json`: `v`=1, `boot_id` (16 hex por ejecución), `seq` (+1 estricto,
  reinicia a 0 con nuevo `boot_id`), `emitted_at` (reloj servidor, ms), `source_id`
  opcional (`anon/live1`).
- Cadencia objetivo 1 Hz (timer corregido por deriva, no `setInterval` acumulativo).
- Transporte: red interna `teremoqwow-prod` hacia `moq-relay` (puerto web 8090 /
  fallback permitido por `@moq/net` en Node; el developer debe confirmarlo
  empíricamente contra `moqdev/moq-relay:0.15.7` aislado, sin tocar el stack local).
- Reconexión: bucle con backoff 1 s→5 s; si la conexión cae se re-publica sin salir;
  si falla irrecuperablemente sale !=0 y `restart: unless-stopped` reinicia.
  Objetivo de recuperación <15 s tras reinicio del relay o del servicio.
  - **Enmienda 2026-10-18 (decisión H2, opción B):** el bucle de reconexión es
    finito — `MAX_RECONNECT_ATTEMPTS` (env, entero >0; default 30) intentos
    consecutivos fallidos. Agotados, log a stderr y `process.exit(1)`; Docker
    reinicia el servicio (boot_id nuevo, seq reinicia — ya cubierto por contrato).
    Éxito al conectar resetea el contador. Esto hace testeable la mutación H2
    (`if (false && closedState)`) con un test determinista y acotado en el tiempo:
    cerrar la conexión durante la espera del timer y afirmar que se agotan los
    intentos y el proceso sale !=0 (no hang infinito). En producción, 30 intentos
    × backoff ≤5 s ≈ hasta ~2,5 min sin relay antes de reinicio externo —
    coherente con `restart: unless-stopped`.
    - **Corrección 2026-10-18 (MEDIUM-1 de ambos refuters):** la frase anterior
      decía "éxito al conectar resetea el contador". La semántica correcta y
      testeable es **éxito al iniciar publicación (primer frame escrito)**, no al
      conectar. Con reset-on-connect literal el contador nunca alcanzaría el
      máximo en un relay con *flapping* (conecta y cierra antes del primer frame),
      el bucle volvería a ser infinito y la mutación H2 sería otra vez
      no-testeable. El código (`publisher.mjs`, reset tras `publishHeartbeatAsGroup`
      exitoso) ya implementa esta lectura; queda fijada aquí para que ningún
      cambio futuro "corrija" el código hacia la lectura literal.
    - **Alcance de "intentos consecutivos fallidos" (HIGH-1 de refuter-tests):**
      cuenta **ambos** caminos de fallo — conexión perdida durante la publicación
      y error de `connect()` (relay caído/`ECONNREFUSED` al arrancar). Los dos
      deben agotar el contador y terminar en `exit(1)`; ningún camino puede
      buclear indefinidamente.
- Health: el publicador escribe marca temporal tras cada frame escrito; healthcheck
  Docker falla si la marca tiene >5 s.
- Observación: modo `observe --window 20` suscribe `heartbeat` durante la ventana y
  emite JSON `{connected, objects, bytes, first_seq, last_seq, boot_ids, monotonic}`.
  `ingest.data` = PASS si conectó, `objects>=10` en 20 s (≈50% de 1 Hz, tolerancia
  a arranque/jitter) y `seq` monótono por boot_id; FAIL si conectó y `objects<10`
  (reason con objects/bytes); UNKNOWN si no pudo conectar/medir. La frescura la
  prueba que los objetos llegan DENTRO de la ventana. Sin interpretar A/V. Nada
  hardcodeado.

## Checklist

- [x] Schema `meta-heartbeat.json` + `validate-schemas.sh` OK
- [x] Cron de `pipeline-observe` offset (#220) — runs schedule ya se disparan; prod host caído (2026-10-18), sin runs verdes aún
- [x] Tests RED→GREEN (contrato, seq/cadencia, reconexión, propiedad, clasificación) — 85 tests meta-track + 53 tests pipeline verificados por el Arquitecto (2026-10-18)
- [x] Decisión H2 del Arquitecto: **opción B** (reconexión finita `MAX_RECONNECT_ATTEMPTS=30`, exit(1)) — enmienda al contrato arriba
- [x] Implementar enmienda H2 (developer, TDD) + test de mutación H2 determinista — `f5b3c61`, suite 91/91
- [x] Refuters correctness + tests reales (subagentes) sin HIGH/CRITICAL — correctness: APPROVE (2 MEDIUM no bloqueantes); tests: HIGH-1 (camino error-de-connect sin cobertura, mutantes A5/A7 supervivientes) → corregido con escenario `connectfail` (`5a244b7`); **Arquitecto verificó empíricamente que A5 y A7 mueren** (pass 6/fail 1, timeout 5 s) y suite final 92/92 → HIGH cerrado sin nueva ronda (regla del flujo: HIGH de cobertura con mutantes reproducibles). MEDIUM-1 de spec corregido en `35790cd`.
- [x] Fix CI: ruta absoluta hardcodeada en `test-publisher-promise-race-real.mjs` → relativa (`7084574`); job `tests-meta-track` verde en Actions (36 s)
- [x] Host prod restaurado (2026-10-18 ~20:30 UTC); dispatch manual del colector → **Stored 9 observation(s)**, run `39163902160` success
- [ ] PR #222 mergeado + deploy + soak 30 min + recovery + snapshot Pipeline

## Evidence

Ver sección final tras producción.

- Diagnóstico scheduling: 0 runs `schedule` de pipeline-observe desde su llegada a main
  (solo 2 `workflow_dispatch`); señales UNKNOWN por TTL (1200 s) en prod-diagnostics
  38262867118. Fix mergeado en #220 (14:38:56Z).

## Next

Tras el deploy: ≥2 runs schedule consecutivos, soak 30 min de `anon/live1-meta`,
reinicio controlado, Fase 1/2/3 OK y verificación humana intacta; cerrar #206.
