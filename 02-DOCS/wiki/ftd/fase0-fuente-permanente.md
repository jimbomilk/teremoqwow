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
- **Gates de flujo NO comprobadas (PENDIENTES)**: sin acceso al servidor (SSH directo:
  "Host key verification failed", no se desactivó) y sin endpoint público del relay
  (`:4443/announced/` sin respuesta). Por tanto NO hay evidencia de: RestartCount estable,
  sonda state=running, bytes SRT crecientes en dos muestras, broadcast `anon/live1`
  anunciado. El único dato es que el contenedor arrancó (1 s tras el up), insuficiente
  para descartar crash-loop. Comandos para el operador (en el servidor, como deploy):
  `docker inspect -f '{{.RestartCount}} {{.State.Status}}' teremoqwow-source-ffmpeg-1`
  (dos veces, 30 s entre ellas); `bash /opt/teremoqwow/scripts/probe-source-ffmpeg.sh`;
  `docker logs --since 30s teremoqwow-srt-ingest-1` dos veces separadas 15 s (bytes/sesión
  creciendo); `docker logs --tail 50 teremoqwow-moq-relay-1 | grep -i live1`.
- CI de #204: el fallo "QoS integration" (PTS-sync / P95) es preexistente en `main`
  (mismos fallos en runs de main del 07-oct) y es de contenido, fuera de las gates de flujo.
- `8890/udp` abierto: no verificable desde aquí (UDP); lo publica `srt-ingest` en la compose.
- MEDIUM/LOW registrado (sin bloquear): el reintento si srt-ingest aún no escucha depende
  del restart de Docker (`depends_on: service_started`, sin healthcheck).

## Next

Aprobar y mergear #204 (merge commit, no squash), retargetear #209 a main y mergearlo;
Actions despliega. Luego medir bytes en dos lecturas. Merge de #204 y esta entrega tras verificar en producción; después Fase 1 (data en
`anon/live1-meta`, contadores de bytes), Fase 2, Fase 3 y admin con semáforos por fase
(automático=flujo, humano=calidad con operador+fecha).
