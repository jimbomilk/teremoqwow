#!/usr/bin/env bash
# Pipeline FFmpeg → moq-pub: transcodifica a 3 renditions ABR y publica en el relay MoQ.
# Uso: bash run.sh  (o exportar las variables de entorno antes de llamarlo)
set -euo pipefail

##############################################################################
# Variables de entorno — sobreescribir en el entorno de despliegue.
# Nunca commitees valores reales; úsalos sólo vía entorno o gestor de secretos.
##############################################################################

# URL del relay MoQ/QUIC (RELAY_BIND en relay.toml).
MOQ_RELAY_URL="${MOQ_RELAY_URL:-https://relay:4443}"

# Namespace MoQ bajo el que se publican los tracks.
MOQ_NAMESPACE="${MOQ_NAMESPACE:-teremoqwow/dev/live1}"

# Origen SRT: MediaMTX en modo lectura (streamid=read:<path>).
SRT_SOURCE="${SRT_SOURCE:-srt://mediamtx:8890?streamid=read:live-main}"

# Framerate del source. Debe coincidir con el del broadcast para que -g sea exacto.
# Si el source tiene framerate variable, FFmpeg lo convierte a CFR con -r.
FRAMERATE="${FRAMERATE:-30}"

# GOP en frames = FRAMERATE × 2 s.  Con 30 fps → 60 frames = 2 s exactos.
GOP_FRAMES=$(( FRAMERATE * 2 ))

# Token JWT para autenticación con el relay (vacío = sin autenticación, sólo dev).
# En producción, inyectar vía gestor de secretos (p.ej. Vault, AWS Secrets Manager).
MOQ_JWT_TOKEN="${MOQ_JWT_TOKEN:-}"

# En dev con certificados auto-firmados, añadir --insecure.
# En producción dejar vacío.
MOQ_INSECURE="${MOQ_INSECURE:-true}"

##############################################################################
# Construir los argumentos de moq-pub dinámicamente para evitar palabras vacías.
##############################################################################

MOQ_ARGS=(
  --url       "${MOQ_RELAY_URL}"
  --namespace "${MOQ_NAMESPACE}"
)
[[ -n "${MOQ_JWT_TOKEN}" ]]         && MOQ_ARGS+=(--token "${MOQ_JWT_TOKEN}")
[[ "${MOQ_INSECURE}" == "true" ]]   && MOQ_ARGS+=(--insecure)

##############################################################################
# Pipeline principal
#
# FFmpeg lee de SRT, genera tres streams de vídeo (High / Medium / Low) más
# un único stream de audio, y vuelca todo en un único MPEG-TS a stdout.
# moq-pub lee por stdin y publica cada PID como un track MoQ independiente
# bajo el namespace indicado.
#
# Aproximación elegida: pipe (stdout → stdin).
#   + Sin puerto TCP adicional para el tramo FFmpeg→moq-pub.
#   + El kernel gestiona el buffer; SIGPIPE propaga fallos entre procesos.
#   + Compatible con docker-compose sin exponer puertos internos extra.
#
# GOP alineado:
#   -g ${GOP_FRAMES}                          → tamaño de GOP en frames (x264).
#   -keyint_min ${GOP_FRAMES}                 → prohíbe GOP más cortos.
#   -force_key_frames "expr:gte(t,n_forced*2)"→ FFmpeg inserta IDR a t=0,2,4,…s
#                                               independientemente de VFR upstream.
# Los tres streams empiezan en t=0 del mismo source, así que sus keyframes
# quedan alineados entre renditions en cada múltiplo de 2 s.
#
# Audio: un único track AAC-LC 128 kbps / 48 kHz / estéreo compartido por
# las tres renditions de vídeo. El player ABR selecciona un stream de vídeo
# pero consume siempre el mismo track de audio.
##############################################################################

ffmpeg -hide_banner -loglevel warning \
  -i "${SRT_SOURCE}" \
  -filter_complex "[0:v]split=3[v_high][v_med][v_low]" \
  \
  -map "[v_high]" \
    -c:v:0        libx264 \
    -preset:v:0   veryfast \
    -tune:v:0     zerolatency \
    -profile:v:0  main \
    -b:v:0        3000k \
    -s:v:0        1920x1080 \
    -r:v:0        "${FRAMERATE}" \
    -g:v:0        "${GOP_FRAMES}" \
    -keyint_min:v:0 "${GOP_FRAMES}" \
    -force_key_frames:v:0 "expr:gte(t,n_forced*2)" \
  \
  -map "[v_med]" \
    -c:v:1        libx264 \
    -preset:v:1   veryfast \
    -tune:v:1     zerolatency \
    -profile:v:1  main \
    -b:v:1        2000k \
    -s:v:1        1280x720 \
    -r:v:1        "${FRAMERATE}" \
    -g:v:1        "${GOP_FRAMES}" \
    -keyint_min:v:1 "${GOP_FRAMES}" \
    -force_key_frames:v:1 "expr:gte(t,n_forced*2)" \
  \
  -map "[v_low]" \
    -c:v:2        libx264 \
    -preset:v:2   veryfast \
    -tune:v:2     zerolatency \
    -profile:v:2  main \
    -b:v:2        1000k \
    -s:v:2        854x480 \
    -r:v:2        "${FRAMERATE}" \
    -g:v:2        "${GOP_FRAMES}" \
    -keyint_min:v:2 "${GOP_FRAMES}" \
    -force_key_frames:v:2 "expr:gte(t,n_forced*2)" \
  \
  -map "0:a" \
    -c:a aac \
    -b:a 128k \
    -ar 48000 \
    -ac 2 \
  \
  -f mpegts pipe:1 \
| moq-pub "${MOQ_ARGS[@]}"
