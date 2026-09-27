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
# 2. Arrancar FFmpeg: 3 renditions de vídeo (High/Medium/Low) en un único
#    MPEG-TS multi-PID enviado al listener SRT (issue #62).
#
#    SPS/PPS alineados entre calidades:
#      - Perfil H.264 main en los 3 streams; sólo varía el level (4.0/3.1/3.0).
#      - -force_key_frames sincroniza IDRs exactos cada 2 s en los 3 streams.
#      - -sc_threshold 0 evita IDRs extra por cambio de escena que
#        desalinearían los GOP entre calidades.
#      - -x264-params nal-hrd=cbr:force-cfr=1 garantiza PTS síncronos.
#
#    En dev/test se usa fuente sintética (testsrc2 + sine).
#    En producción sustituir la fuente por el source SRT externo real,
#    p.ej.: -i "srt://broadcast-encoder:port?streamid=publish:live1"
##############################################################################

ffmpeg -hide_banner -loglevel warning \
  -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
  -filter_complex "[0:v]split=3[v_high][v_med][v_low]" \
  \
  -map "[v_high]" \
  -map "[v_med]" \
  -map "[v_low]" \
  -map 1:a \
  \
  -c:v:0 libx264 -preset:v:0 ultrafast -tune:v:0 zerolatency \
  -profile:v:0 main -level:v:0 4.0 \
  -s:v:0 1280x720 -b:v:0 2500k \
  -g:v:0 60 -keyint_min:v:0 60 -sc_threshold:v:0 0 \
  -force_key_frames:v:0 "expr:gte(t,n_forced*2)" \
  -x264-params:v:0 "nal-hrd=cbr:force-cfr=1" \
  -pix_fmt:v:0 yuv420p \
  \
  -c:v:1 libx264 -preset:v:1 ultrafast -tune:v:1 zerolatency \
  -profile:v:1 main -level:v:1 3.1 \
  -s:v:1 854x480 -b:v:1 1200k \
  -g:v:1 60 -keyint_min:v:1 60 -sc_threshold:v:1 0 \
  -force_key_frames:v:1 "expr:gte(t,n_forced*2)" \
  -x264-params:v:1 "nal-hrd=cbr:force-cfr=1" \
  -pix_fmt:v:1 yuv420p \
  \
  -c:v:2 libx264 -preset:v:2 ultrafast -tune:v:2 zerolatency \
  -profile:v:2 main -level:v:2 3.0 \
  -s:v:2 640x360 -b:v:2 600k \
  -g:v:2 60 -keyint_min:v:2 60 -sc_threshold:v:2 0 \
  -force_key_frames:v:2 "expr:gte(t,n_forced*2)" \
  -x264-params:v:2 "nal-hrd=cbr:force-cfr=1" \
  -pix_fmt:v:2 yuv420p \
  \
  -c:a aac -b:a 128k -ar 48000 -ac 2 \
  -f mpegts "srt://127.0.0.1:8890?streamid=publish:live1" &
FFMPEG_PID=$!

# Esperar a que cualquiera de los dos procesos termine (error o señal).
wait -n "${MOQ_PID}" "${FFMPEG_PID}" 2>/dev/null || true
cleanup
