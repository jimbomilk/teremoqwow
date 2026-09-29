#!/usr/bin/env bash
# ffmpeg-sdi-command.sh — issue #89
# Captura señal SDI desde un dispositivo DeckLink y la publica al relay MoQ.
# Requiere FFmpeg compilado con --enable-decklink.
#
# Variables de entorno:
#   DEVICE     — nombre del dispositivo DeckLink (default: "DeckLink Mini Recorder 4K")
#   RELAY_TCP  — endpoint TCP del relay (default: "tcp://localhost:4444")
#   BROADCAST  — namespace del broadcast (default: "live/sdi-1")
#   AUTH_NS    — namespace de autenticación (default: "anon")
set -euo pipefail

DEVICE="${DEVICE:-DeckLink Mini Recorder 4K}"
RELAY_TCP="${RELAY_TCP:-tcp://localhost:4444}"
BROADCAST="${BROADCAST:-live/sdi-1}"
AUTH_NS="${AUTH_NS:-anon}"

echo "[sdi] Dispositivo : $DEVICE"
echo "[sdi] Relay TCP   : $RELAY_TCP"
echo "[sdi] Broadcast   : $BROADCAST"

# FFmpeg captura SDI vía DeckLink y codifica H.264/AAC en MPEG-TS hacia stdout.
# El pipe se conecta al importador MoQ que lo publica en el relay.
ffmpeg \
  -f decklink \
  -i "$DEVICE" \
  -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -profile:v main \
    -level 4.0 \
    -g 60 \
    -keyint_min 60 \
    -sc_threshold 0 \
    -b:v 4000k \
    -maxrate 4500k \
    -bufsize 2000k \
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
