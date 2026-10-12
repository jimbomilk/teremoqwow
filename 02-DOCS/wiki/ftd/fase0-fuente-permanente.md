# Fase 0 — Fuente FFmpeg permanente en producción

## Intent

Eliminar las pruebas manuales en wow.teremoq.com: un servicio `source-ffmpeg`
siempre activo publica una señal sintética continua de vídeo+audio por SRT a
`srt-ingest` (streamid `live1`, red interna `teremoqwow-prod`), con la misma
ruta que el emisor real (Larix). Mantiene vivo el pipeline para que un humano
abra el player cuando quiera y lo juzgue. Prerrequisito de las 3 fases visibles
en admin: 1) ingesta vídeo/audio/data, 2) flujo MoQ + relay, 3) player.

## Principio de verificación (cambio de alcance aprobado por el usuario)

- **Automático = flujo de datos/servicio**: SRT conectado y bytes crecientes,
  broadcast anunciado y tracks con objetos/grupos crecientes, track de datos a su
  cadencia, procesos arriba y recuperación (restart/reconnect), endpoints de salud.
- **Humano = calidad audiovisual**: un operador confirma, con fecha, que ve y oye
  bien. No hay verde audiovisual sin esa confirmación ni sustituto automático.
- Eliminado del alcance: fps, frames, continuidad de vídeo, huecos/tono/pip de
  audio, ffprobe/volumedetect, navegador headless (currentTime/frames/stalls).
- Corrección aplicada: se habían escrito tests de contenido (runtime ffmpeg,
  mutantes de contenido), timecode `drawtext` y pip de audio; se BORRARON, se
  simplificó el comando a testsrc2 + sine, y se reescribieron los issues
  #205–#208 con este criterio. Un segundo FTD de evidencia fue eliminado (FTD único).

## Scope

- In: servicio `source-ffmpeg` (testsrc2 + sine simple, H.264/AAC/mpegts),
  restart automático, deploy/runbook, sonda de estado de servicio, contrato
  `schemas/media/v1/source-status.json`, tests de configuración (TDD), issues/PR
  en el proyecto #3 y milestone "Núcleo productivo".
- Base: PR #204 (`feat/srt-ingest-prod`, `srt-ingest`). Esta entrega va apilada
  (PR con base `feat/srt-ingest-prod`); #204 se reutiliza, no se duplica.
- Out: data (→ Fase 1, broadcast hermano `anon/live1-meta`, sin segundo productor
  en `anon/live1`); página admin; seguridad (#195); Docker socket / `docker run`
  desde admin-api.
- Cambios locales ajenos del árbol: no tocados ni commiteados.

## Checklist

- [x] Issues F0/F1/F2/F3 (#205–#208) + milestone, vinculados al proyecto #3.
- [x] Contrato `source-status.json` validado con `scripts/validate-schemas.sh`.
- [x] Tests de configuración escritos antes del servicio (RED observado).
- [x] Servicio `source-ffmpeg` en docker-compose.prod.yml.
- [x] deploy.yml (reinicio tras srt-ingest), runbook, sonda `scripts/probe-source-ffmpeg.sh`.
- [x] refuter-correctness + refuter-tests en paralelo sobre el delta final: sin
      HIGH/CRITICAL (informe del developer; el Arquitecto verificó tests y arranque de ffmpeg).
- [x] PR #209 abierto, vinculado al proyecto #3 y mergeado (9d00b8c).
- [ ] Gate producción (PENDIENTE, no desplegado): `source-ffmpeg` running sin reinicios
      >=10 min, sonda state=running, srt-ingest con SRT recibiendo bytes.
- [ ] Gate humana (PENDIENTE): operador confirma con fecha que ve/oye la fuente.

## Evidence

- `timeout 120 python3 -m pytest scripts/test_source_ffmpeg_prod.py scripts/test_srt_ingest_prod.py -q`
  → 43 passed (27 de source-ffmpeg + 16 de #204).
- `scripts/validate-schemas.sh` → "All schemas valid." (con source-status.json).
- ffmpeg local: el comando (testsrc2+sine→libx264/aac→mpegts, 2 s a fichero) arranca y
  termina rc=0. Solo prueba que el comando es aceptado, no calidad.
- Imagen `jrottenberg/ffmpeg:7.1-alpine`: `docker manifest inspect` OK; `ffmpeg -encoders`
  dentro de la imagen lista `libx264`. Riesgo conocido cerrado.
- **Corrección GOP (regresión vs #133)**: la compose usaba `-g 60 -keyint_min 60` (GOP 2 s
  @30 fps, causa raíz del incumplimiento del SLA 700 ms P95; el subscriber MoQ solo entra
  en IDR). Ahora `-g 30 -keyint_min 30 -sc_threshold 0` (1 s), igual que
  `config/moq-mux/run.sh`. Protegido por 3 tests de configuración nuevos (30/30 pass).
  Refuter-correctness y refuter-tests: 0 hallazgos. Commit fcc1793. Runbook corregido.
- **Despliegue (2026-10-12)**: #204 mergeado (5946f99) y #209 (9d00b8c), ambos con merge
  commit y bypass admin autorizado por el usuario (el ruleset "Protect main" exige 1
  review y el autor no puede auto-aprobarse; el rol admin tiene bypass por diseño).
  Run deploy 38232541252 (#204) y 38232601873 (#209): success. Log del run de #209:
  `OK source-ffmpeg`, `OK srt-ingest`; `compose ps`: source-ffmpeg "Up Less than a second"
  (imagen jrottenberg/ffmpeg:7.1-alpine), srt-ingest "Up 45 seconds" con
  `0.0.0.0:8890->8890/udp`. https://wow.teremoq.com/player/ y /api/health → 200.
- **INCIDENTE 2026-10-12 y causa raíz.** Tras el primer deploy, el player anunciaba
  `anon/live1` pero no llegaba media (0 frames; `export ts` con cliente moq = 0 bytes).
  Visibilidad: nuevo workflow `prod-diagnostics.yml` (workflow_dispatch, solo lectura, secrets
  de deploy; #211) → run 38234037695. Observado en producción: contenedores `source-ffmpeg`,
  `srt-ingest` y `moq-relay` running, restarts=0; srt-ingest "SRT publish accepted" y
  "publishing ingest broadcast path=anon/live1"; el relay recibía ~1 MB/s PERO el log de
  ffmpeg mostraba `frame=0 ... time=11:40:24 speed=51.3x` y srt-ingest registraba
  `subscribed error ... track=catalog.json err=internal error`.
  **Causa raíz**: `testsrc2=...:d=0` tiene duración CERO (medido con la imagen exacta:
  `frame=0`; sin `d` → `frame=60` en 2 s), mientras `sine ...:d=0` sí es infinito. Solo salía
  audio, sin vídeo (sin catálogo) y, sin `-re`, a 51x tiempo real. NO era la carrera de
  arranque (SRT aceptado a los 0,1 s), ni la imagen ni el puerto.
  **Fix** (#212, tests de configuración, mutantes verificados muertos): sin `d=` en las
  entradas lavfi y `-re` exactamente una vez por entrada lavfi. refuter-correctness: LOW×2;
  refuter-tests: 2 HIGH de cobertura (alias `duration=`, `-re` atribuido a la entrada
  equivocada) corregidos y verificados con mutantes.
- **Evidencia bytes > 0 en producción** (cliente oficial `moqdev/moq:0.12.7 --connect
  https://wow.teremoq.com:4443/anon --broadcast anon/live1 export ts`, ventanas de 20 s):
  10:30:51 UTC 54 896 B; 10:31:22 UTC 7 196 264 B; 10:45:30 UTC 12 705 980 B; 10:46:07 UTC
  12 337 876 B (y una lectura larga previa de 154 684 520 B). Catálogo ahora con
  `0.avc3`, `1.aac` (suscripciones a ambas pistas). `prod-diagnostics` 10:24 UTC: source-ffmpeg
  restarts=0, TX 30 MB → 42,7 MB en 15 s (avanza). Solo flujo de datos; nada afirmado sobre
  calidad de imagen o sonido.
- Observación sin resolver (LOW): las lecturas de 20 s son muy variables (54 KB a 12 MB) y el
  cliente registra `current group evicted ... track=1.aac`; es comportamiento del consumidor
  de prueba, no concluyente. Pendiente de revisar con Fase 1.
- `/metrics/latency` en bucle 404: endpoint solo de dev (plugin Vite, `apply: serve`);
  corregido en #213 gateando el POST con `import.meta.env.DEV` (MEDIUM backlog: el cableado
  de bootstrap.ts no tiene test; CI no ejecuta metrics.test.ts).
- `/cert-hash` y `/certificate.sha256` siguen 404; `/api/cert-hash` da 200. Comentado en #167,
  no corregido (no necesario con certificados Let's Encrypt).
- CI de #204: el fallo "QoS integration" (PTS-sync / P95) es preexistente en `main`
  (mismos fallos en runs de main del 07-oct) y es de contenido, fuera de las gates de flujo.
- `8890/udp` abierto: no verificable desde aquí (UDP); lo publica `srt-ingest` en la compose.
- MEDIUM/LOW registrado (sin bloquear): el reintento si srt-ingest aún no escucha depende
  del restart de Docker (`depends_on: service_started`, sin healthcheck).

## Next

- Fase 1 (#206): data en `anon/live1-meta`, contadores de bytes; Fases 2/3 (#207/#208).
- Verificación humana audiovisual de #205 (único veredicto válido de vídeo/audio): pendiente
  de instrucción al usuario en el issue.
- Siguiente task aprobado, NO implementado: vista Admin "Pipeline" (issue #214) con 3 fases
  (ingesta v/a/data, MoQ+relay, player). Por fase: transporte automático
  OK/DEGRADED/DOWN/BLOCKED/UNKNOWN y verificación humana VERIFIED/NOT_VERIFIED (operador +
  fecha). Fases posteriores BLOCKED si falla una anterior; causa, última transición,
  last-green, bytes/objetos, trazabilidad; alimentada por observaciones reales y
  `prod-diagnostics`/API, sin datos simulados ni Docker lanzado desde admin-api.
- Trabajo aparte posterior: ruleset "Protect main" y check "QoS integration".
