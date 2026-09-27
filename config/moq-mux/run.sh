#!/usr/bin/env bash
# CAMBIO (issue #116): moq-pub como binario standalone no existe en moqdev/moq 0.12.7.
# El CLI unificado `moq` usa `moq import srt --listen` para ingestar SRT directamente,
# sin MediaMTX intermedio y sin pipe FFmpeg→moq-pub.
# `moq import srt` actúa de listener SRT; FFmpeg publica en ese listener como source SRT.
#
# Uso: bash run.sh  (o exportar las variables de entorno antes de llamarlo)
set -euo pipefail

##############################################################################
# Variables de entorno — sobreescribir en el entorno de despliegue.
# Nunca commitees valores reales; úsalos sólo vía entorno o gestor de secretos.
##############################################################################

# Endpoint TCP del relay MoQ (moqdev/moq 0.12.7, subtree anon/**).
MOQ_RELAY_TCP="${MOQ_RELAY_TCP:-tcp://relay:4444/anon}"

# Broadcast path dentro del subtree autorizado por el relay (anon/**).
# NO usar teremoqwow/dev/live1: ese subtree no está bajo --auth-public 'anon/**'.
MOQ_BROADCAST="${MOQ_BROADCAST:-anon/live1}"

# Dirección en la que `moq import srt` escucha conexiones SRT entrantes.
SRT_LISTEN_ADDR="${SRT_LISTEN_ADDR:-[::]:8890}"

# Latencia SRT del listener (buffer de reordenación/recuperación).
SRT_LATENCY="${SRT_LATENCY:-200ms}"

##############################################################################
# Trap: asegurar que ambos procesos mueren al recibir SIGTERM o SIGINT.
##############################################################################

MOQ_PID=""
FFMPEG_PID=""

cleanup() {
  [[ -n "${FFMPEG_PID}" ]] && kill "${FFMPEG_PID}" 2>/dev/null || true
  [[ -n "${MOQ_PID}" ]]    && kill "${MOQ_PID}"    2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

##############################################################################
# 1. Arrancar el listener SRT de moq en background.
#
#    `moq import srt --listen` escucha en SRT_LISTEN_ADDR y reenvía el stream
#    al relay como broadcast MOQ_BROADCAST bajo MOQ_RELAY_TCP.
#    El namespace queda dentro del subtree anon/** que el relay autoriza
#    sin credenciales (--auth-public 'anon/**' en relay.toml).
##############################################################################

moq \
  --connect "${MOQ_RELAY_TCP}" \
  --broadcast "${MOQ_BROADCAST}" \
  import srt \
    --listen "${SRT_LISTEN_ADDR}" \
    --latency "${SRT_LATENCY}" &
MOQ_PID=$!

# Dar tiempo al listener para que abra el socket antes de que FFmpeg intente conectar.
sleep 1

##############################################################################
# 2. Arrancar FFmpeg que publica en el listener SRT.
#
#    En dev/test se usa una fuente sintética (testsrc2 + sine).
#    En producción, sustituir la fuente por el source SRT externo real,
#    p.ej.: -i "srt://broadcast-encoder:port?streamid=publish:live1"
#
#    GOP fijo de 60 frames (2 s a 30 fps), -sc_threshold 0 para evitar
#    IDRs extra por cambio de escena; garantiza PTS alineados entre calidades.
##############################################################################

ffmpeg -hide_banner -loglevel warning \
  -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -g 60 \
  -keyint_min 60 \
  -sc_threshold 0 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 128k \
  -f mpegts "srt://127.0.0.1:8890?streamid=publish:live1" &
FFMPEG_PID=$!

# Esperar a que cualquiera de los dos procesos termine (error o señal).
wait -n "${MOQ_PID}" "${FFMPEG_PID}" 2>/dev/null || true
cleanup
