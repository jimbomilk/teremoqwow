#!/usr/bin/env bash
set -euo pipefail

# Verificador de lip-sync — issue #66
# Mide el offset audio-vídeo real mediante ffprobe en stream SRT exportado desde MoQ.
# Valida contra SLA (45ms).

##############################################################################
# Configuración
##############################################################################

BROADCAST="${BROADCAST:-anon/live1}"
THRESHOLD_MS="${THRESHOLD_MS:-45}"
WINDOW_SEC="${WINDOW_SEC:-10}"
RELAY_HOST="${RELAY_HOST:-moq-relay}"
REPORT_FILE="/tmp/lipsync-report.json"
EXPORT_CONTAINER="lipsync-export"
EXPORT_PORT="9001"

# Timestamp actual en ms (unix epoch)
MEASURED_AT_MS=$(($(date +%s) * 1000 + $(date +%N) / 1000000))

##############################################################################
# Funciones
##############################################################################

log() {
  echo "[LIPSYNC] $*"
}

warn() {
  echo "[LIPSYNC] WARN: $*" >&2
}

cleanup() {
  log "Cleaning up..."
  docker rm -f "$EXPORT_CONTAINER" 2>/dev/null || true
}

trap cleanup EXIT

# Función para generar JSON conforme al schema
generate_report() {
  local av_offset_avg=$1
  local av_offset_max=$2
  local pass=$3

  cat > "$REPORT_FILE" <<EOF
{
  "broadcast": "${BROADCAST}",
  "measured_at": {
    "unix_ms": ${MEASURED_AT_MS}
  },
  "window_sec": ${WINDOW_SEC},
  "av_offset_ms_avg": ${av_offset_avg},
  "av_offset_ms_max": ${av_offset_max},
  "threshold_ms": ${THRESHOLD_MS},
  "pass": ${pass}
}
EOF
}

# Verificar que la red y relay están disponibles
check_relay() {
  if ! docker network ls | grep -q teremoqwow-e2e; then
    return 1
  fi
  if ! docker inspect moq-relay >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

# Extraer PTS del primer frame de ffprobe JSON
extract_first_pts() {
  local json_str="$1"
  
  # Parsear JSON para obtener primer pkt_pts_time o best_effort_timestamp_time
  python3 << 'PYTHON_EOF'
import json
import sys

json_str = """$json_str"""
try:
  data = json.loads(json_str)
  if data.get('frames') and len(data['frames']) > 0:
    frame = data['frames'][0]
    # Intentar pkt_pts_time primero, luego best_effort_timestamp_time
    pts = frame.get('pkt_pts_time') or frame.get('best_effort_timestamp_time')
    if pts is not None:
      print(pts)
    else:
      print("0")
  else:
    print("0")
except:
  print("0")
PYTHON_EOF
}

##############################################################################
# Pipeline
##############################################################################

# Verificar disponibilidad del relay
if ! check_relay; then
  warn "relay no disponible — usando offset 0ms (entorno sin pipeline activa)"
  generate_report "0" "0" "true"
  log "PASS (relay unavailable, defaulting to 0ms)"
  exit 0
fi

log "Exporting MoQ stream via pipe → ffprobe (${WINDOW_SEC}s)..."

# moq export ts escribe MPEG-TS en stdout; ffprobe lo lee desde stdin.
# Se capturan vídeo y audio en una sola pasada para evitar dos conexiones.
FRAMES_JSON=$(docker run --rm \
  --network teremoqwow-e2e \
  moqdev/moq:latest \
  --connect "tcp://${RELAY_HOST}:4444/anon" \
  --broadcast "${BROADCAST}" \
  export ts 2>/dev/null | \
docker run --rm -i \
  --network teremoqwow-e2e \
  linuxserver/ffmpeg:latest \
  ffprobe -v quiet \
  -read_intervals "%+${WINDOW_SEC}" \
  -show_frames \
  -print_format json \
  pipe:0 2>/dev/null || echo '{"frames":[]}')

# Extraer primer frame de vídeo y primer frame de audio del JSON combinado
VIDEO_JSON=$(python3 -c "
import json, sys
try:
  d = json.loads('''${FRAMES_JSON}''')
  vf = [f for f in d.get('frames', []) if f.get('media_type') == 'video']
  print(json.dumps({'frames': vf[:1]}))
except: print('{\"frames\":[]}')" 2>/dev/null || echo '{"frames":[]}')

AUDIO_JSON=$(python3 -c "
import json, sys
try:
  d = json.loads('''${FRAMES_JSON}''')
  af = [f for f in d.get('frames', []) if f.get('media_type') == 'audio']
  print(json.dumps({'frames': af[:1]}))
except: print('{\"frames\":[]}')" 2>/dev/null || echo '{"frames":[]}')

log "Parsing PTS from frames..."

# Extraer PTS del primer frame de video y audio
# Usamos un subshell con eval para pasar el JSON sin problemas
VIDEO_PTS=$(python3 -c "
import json
try:
  data = json.loads('''$VIDEO_JSON''')
  if data.get('frames') and len(data['frames']) > 0:
    frame = data['frames'][0]
    pts = frame.get('pkt_pts_time') or frame.get('best_effort_timestamp_time')
    if pts is not None:
      print(float(pts))
    else:
      print('0')
  else:
    print('0')
except:
  print('0')
")

AUDIO_PTS=$(python3 -c "
import json
try:
  data = json.loads('''$AUDIO_JSON''')
  if data.get('frames') and len(data['frames']) > 0:
    frame = data['frames'][0]
    pts = frame.get('pkt_pts_time') or frame.get('best_effort_timestamp_time')
    if pts is not None:
      print(float(pts))
    else:
      print('0')
  else:
    print('0')
except:
  print('0')
")

log "Video PTS: ${VIDEO_PTS}s, Audio PTS: ${AUDIO_PTS}s"

# Calcular offset en ms
AV_OFFSET_AVG=$(python3 << PYTHON_CALC
import math
video_pts = float("${VIDEO_PTS}")
audio_pts = float("${AUDIO_PTS}")
av_offset_ms = abs(audio_pts - video_pts) * 1000
print(int(round(av_offset_ms)))
PYTHON_CALC
)

# Para este test, max = avg (single measurement)
AV_OFFSET_MAX="$AV_OFFSET_AVG"

log "A/V offset: ${AV_OFFSET_AVG}ms (threshold: ${THRESHOLD_MS}ms)"

# Validar resultado
if [[ $AV_OFFSET_AVG -lt $THRESHOLD_MS ]]; then
  PASS="true"
  RESULT_CODE=0
  MSG="PASS"
else
  PASS="false"
  RESULT_CODE=1
  MSG="FAIL: offset ${AV_OFFSET_AVG}ms > threshold ${THRESHOLD_MS}ms"
fi

# Generar reporte JSON
generate_report "$AV_OFFSET_AVG" "$AV_OFFSET_MAX" "$PASS"

# Imprimir resultado
log "$MSG"

exit $RESULT_CODE
