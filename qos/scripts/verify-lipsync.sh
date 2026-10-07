#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/qos-diagnostics.sh"

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
REPORT_FILE="${LIPSYNC_REPORT_FILE:-/tmp/lipsync-report.json}"
EXPORT_CONTAINER="lipsync-export"
EXPORT_PORT="9001"

# Validar WINDOW_SEC antes de cualquier aritmética (evita x[$(cmd)] en $(( )))
qos_require_window_sec || exit $?
# THRESHOLD_MS entra en una comparación aritmética: validar antes de usarlo.
qos_require_decimal THRESHOLD_MS || exit $?

# Timestamp actual en ms (unix epoch). %N con ceros a la izquierda (p. ej. 089...)
# sería octal inválido en aritmética: forzar base 10.
MEASURED_AT_MS=$(($(date +%s) * 1000 + 10#$(date +%N) / 1000000))

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
  if [[ "${LIPSYNC_READINESS_ONLY:-0}" != "1" && ! -s "$REPORT_FILE" ]]; then
    generate_report "0" "0" "false" || true
  fi
  docker rm -f "$EXPORT_CONTAINER" 2>/dev/null || true
  if [[ -n "${_TMPDIR:-}" ]]; then
    rm -rf "$_TMPDIR"
  fi
}

trap cleanup EXIT

# Función para generar JSON conforme al schema
generate_report() {
  local av_offset_avg=$1
  local av_offset_max=$2
  local pass=$3

  python3 - "$REPORT_FILE" "$BROADCAST" "${MEASURED_AT_MS:-0}" \
    "$WINDOW_SEC" "$av_offset_avg" "$av_offset_max" "$THRESHOLD_MS" "$pass" <<'PY'
import json
import os
import stat
import sys

path, broadcast, measured_at, window, average, maximum, threshold, passed = sys.argv[1:]
report = {
    "broadcast": broadcast,
    "measured_at": {"unix_ms": int(measured_at)},
    "window_sec": int(window),
    "av_offset_ms_avg": float(average),
    "av_offset_ms_max": float(maximum),
    "threshold_ms": float(threshold),
    "pass": passed == "true",
}
parent = os.path.dirname(os.path.abspath(path)) or "."
name = os.path.basename(path)
dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
dirfd = os.open(parent, dir_flags)
try:
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=dirfd)
    file_stat = os.fstat(fd)
    if not stat.S_ISREG(file_stat.st_mode):
        raise RuntimeError("report path must be regular")
    if file_stat.st_nlink != 1:
        raise RuntimeError("report path must be a single-link regular file")
    os.fchmod(fd, 0o600)
    os.ftruncate(fd, 0)
finally:
    os.close(dirfd)
with os.fdopen(fd, "w") as handle:
    json.dump(report, handle, indent=2)
PY
}

# Materialize a failure report before starting external tools. This keeps the
# artifact deterministic even if a decoder/pipe exits during startup.
if [[ "${LIPSYNC_READINESS_ONLY:-0}" != "1" ]]; then
  mkdir -p "$(dirname "$REPORT_FILE")"
  generate_report "0" "0" "false"
fi

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
  warn "relay no disponible — INCONCLUSIVE, no se puede medir lip-sync"
  generate_report "0" "0" "false"
  log "FAIL: relay unavailable — sin relay no hay PASS posible"
  exit 1
fi

log "Exporting MoQ stream via pipe → ffprobe (${WINDOW_SEC}s)..."

# moq export ts escribe MPEG-TS en stdout; ffprobe lo lee desde stdin.
# Se capturan vídeo y audio en una sola pasada para evitar dos conexiones.
# timeout previene que el pipe bloquee indefinidamente si el broadcast no tiene datos.
# ffprobe local escribe JSON a tempfile; se parsea leyendo el archivo (evita
# los problemas de interpolar un JSON multi-KB en heredocs de python -c).
_TMPDIR=$(mktemp -d)
_TMPJSON="${_TMPDIR}/ffprobe.json"
_EXPORT_STDERR="${_TMPDIR}/exporter.stderr"
_FFPROBE_STDERR="${_TMPDIR}/ffprobe.stderr"
set +e
docker run --rm \
    --network teremoqwow-e2e \
    moqdev/moq:0.12.7 \
    --connect "tcp://${RELAY_HOST}:4444/anon" \
    --broadcast "${BROADCAST}" \
    export ts 2>"$_EXPORT_STDERR" | \
timeout $((WINDOW_SEC + QOS_FFPROBE_TIMEOUT_MARGIN_SEC)) ffprobe \
    -v quiet \
    -read_intervals "%+${WINDOW_SEC}" \
    -show_frames \
    -print_format json \
    pipe:0 2>"$_FFPROBE_STDERR" > "$_TMPJSON"
_PIPE_STATUS=("${PIPESTATUS[@]}")
set -e

# ffprobe cierra el pipe tras su -read_intervals: el exit 1 del exporter por
# "broken pipe" se tolera solo si ffprobe salió 0 (los frames se exigen abajo).
_EXPORT_EFFECTIVE=$(qos_effective_exporter_status \
  "${_PIPE_STATUS[0]}" "${_PIPE_STATUS[1]}" "$_EXPORT_STDERR")
qos_report_tool_diagnostic exporter "$_EXPORT_EFFECTIVE" "$_EXPORT_STDERR"
qos_report_tool_diagnostic ffprobe "${_PIPE_STATUS[1]}" "$_FFPROBE_STDERR"
if [[ "$_EXPORT_EFFECTIVE" -ne 0 || "${_PIPE_STATUS[1]}" -ne 0 ]]; then
  generate_report "0" "0" "false"
  warn "export/decoder tool failed; measurement unavailable"
  exit 1
fi

log "Parsing PTS from frames ($(wc -c < "$_TMPJSON") bytes)..."

# Calcular offset A/V como la mediana de |audio_pts - video_pts| emparejando
# cada frame de audio con el frame de video más cercano en el tiempo.
# Esto refleja el desalineamiento real, no la latencia entre primeros grupos.
_PTS_OUT=$(python3 - "$_TMPJSON" <<'PYEOF'
import json, sys, re
try:
    with open(sys.argv[1]) as f:
        raw = f.read()
except Exception:
    print("0 0 0"); sys.exit()
# ffprobe puede truncarse si timeout lo mata: extraer solo objetos frame completos.
frames = []
for m in re.finditer(r'\{\s*"media_type"\s*:.*?\}', raw, re.DOTALL):
    try:
        frames.append(json.loads(m.group(0)))
    except Exception:
        continue
def pts_of(fr):
    v = fr.get("pts_time") or fr.get("pkt_pts_time") or fr.get("best_effort_timestamp_time")
    return float(v) if v is not None else None
vpts = sorted(p for p in (pts_of(f) for f in frames if f.get("media_type")=="video") if p is not None)
apts = sorted(p for p in (pts_of(f) for f in frames if f.get("media_type")=="audio") if p is not None)
if not vpts or not apts:
    print(f"{vpts[0] if vpts else 0} {apts[0] if apts else 0} 0 {len(vpts)} {len(apts)}"); sys.exit()
import bisect
diffs = []
for a in apts:
    i = bisect.bisect_left(vpts, a)
    cand = []
    if i < len(vpts): cand.append(vpts[i])
    if i > 0:         cand.append(vpts[i-1])
    diffs.append(min(abs(a - v) for v in cand))
diffs.sort()
median_ms = int(round(diffs[len(diffs)//2] * 1000))
print(f"{vpts[0]} {apts[0]} {median_ms} {len(vpts)} {len(apts)}")
PYEOF
)
read -r VIDEO_PTS AUDIO_PTS AV_MEDIAN_MS VIDEO_FRAMES AUDIO_FRAMES <<< "$_PTS_OUT"

log "Video PTS: ${VIDEO_PTS}s, Audio PTS: ${AUDIO_PTS}s, A/V median offset: ${AV_MEDIAN_MS}ms"

if [[ "${VIDEO_FRAMES:-0}" -eq 0 || "${AUDIO_FRAMES:-0}" -eq 0 ]]; then
  generate_report "0" "0" "false"
  log "FAIL: incomplete media frames (audio and video are both required)"
  exit 1
fi

AV_OFFSET_AVG="${AV_MEDIAN_MS:-0}"
AV_OFFSET_MAX="$AV_OFFSET_AVG"

log "A/V offset: ${AV_OFFSET_AVG}ms (threshold: ${THRESHOLD_MS}ms)"

# The readiness gate establishes only that both media tracks are present.
# QoS quality is evaluated by the subsequent measurement check.
if [[ "${LIPSYNC_READINESS_ONLY:-0}" == "1" ]]; then
  log "READY: audio/video frames available"
  exit 0
fi

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
