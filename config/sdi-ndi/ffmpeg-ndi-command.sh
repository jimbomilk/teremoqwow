#!/usr/bin/env bash
# ffmpeg-ndi-command.sh — issue #89
# Captura señal NDI y la publica al relay MoQ.
# Requiere FFmpeg compilado con --enable-libndi_newtek y NDI SDK en LD_LIBRARY_PATH.
#
# Variables de entorno:
#   NDI_SOURCE — nombre de la fuente NDI, p.ej. "CAMARA-ESTUDIO-1" o "SOURCE@192.168.1.10"
#   RELAY_TCP  — endpoint TCP del relay (default: "tcp://localhost:4444")
#   BROADCAST  — namespace del broadcast (default: "live/ndi-1")
#   AUTH_NS    — namespace de autenticación (default: "anon")
set -euo pipefail

NDI_SOURCE="${NDI_SOURCE:-}"
RELAY_TCP="${RELAY_TCP:-tcp://localhost:4444}"
BROADCAST="${BROADCAST:-live/ndi-1}"
AUTH_NS="${AUTH_NS:-anon}"

if [ -z "$NDI_SOURCE" ]; then
  echo "[ndi] ERROR: NDI_SOURCE no definida." >&2
  echo "[ndi] Lista fuentes disponibles con:" >&2
  echo "       ffmpeg -f libndi_newtek -find_sources 1 -i dummy 2>&1 | grep Found" >&2
  exit 1
fi

echo "[ndi] Fuente NDI : $NDI_SOURCE"
echo "[ndi] Relay TCP  : $RELAY_TCP"
echo "[ndi] Broadcast  : $BROADCAST"

# libndi_newtek produce vídeo descomprimido; se transcodifica a H.264/AAC antes del pipe.
ffmpeg \
  -f libndi_newtek \
  -i "$NDI_SOURCE" \
  -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -profile:v main \
    -level 4.0 \
    -g 60 \
    -keyint_min 60 \
    -sc_threshold 0 \
    -b:v 3000k \
    -maxrate 3500k \
    -bufsize 1500k \
  -c:a aac \
    -b:a 128k \
    -ar 48000 \
  -thread_queue_size 512 \
  -f mpegts pipe:1 \
  2>/dev/null \
| moq \
    --connect "${RELAY_TCP}/${AUTH_NS}" \
    --broadcast "$BROADCAST" \
    import ts
