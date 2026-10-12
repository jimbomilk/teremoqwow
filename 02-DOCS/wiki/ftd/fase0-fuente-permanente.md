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
- [ ] PR abierto y vinculado al proyecto #3.
- [ ] Gate producción (PENDIENTE, no desplegado): `source-ffmpeg` running sin reinicios
      >=10 min, sonda state=running, srt-ingest con SRT recibiendo bytes.
- [ ] Gate humana (PENDIENTE): operador confirma con fecha que ve/oye la fuente.

## Evidence

- `timeout 120 python3 -m pytest scripts/test_source_ffmpeg_prod.py scripts/test_srt_ingest_prod.py -q`
  → 43 passed (27 de source-ffmpeg + 16 de #204).
- `scripts/validate-schemas.sh` → "All schemas valid." (con source-status.json).
- ffmpeg local: el comando (testsrc2+sine→libx264/aac→mpegts, 2 s a fichero) arranca y
  termina rc=0. Solo prueba que el comando es aceptado, no calidad.
- NO verificado: `docker compose config` (falta /home/deploy/.env local), pull de la imagen
  `jrottenberg/ffmpeg:7.1-alpine` (que traiga libx264), conexión SRT real, producción.
- MEDIUM/LOW registrado (sin bloquear): el reintento si srt-ingest aún no escucha depende
  del restart de Docker (`depends_on: service_started`, sin healthcheck).

## Next

Merge de #204 y esta entrega tras verificar en producción; después Fase 1 (data en
`anon/live1-meta`, contadores de bytes), Fase 2, Fase 3 y admin con semáforos por fase
(automático=flujo, humano=calidad con operador+fecha).
