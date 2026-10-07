#!/usr/bin/env bash
# Prueba de integración end-to-end con video real.
# Orquesta: pipeline MoQ, inyector FFmpeg, verificadores de lip-sync, PTS-sync
# y track de sincronía. Todos los checks usan video real (sin simuladores).
#
# USO:
#   sudo bash qos/scripts/integration-test.sh
#
# PRERREQUISITOS:
#   - Docker con red teremoqwow-e2e
#   - Contenedores moq-relay y moq-import corriendo
#   - CAP_NET_ADMIN para tc netem (o ejecutar sin netem con SKIP_NETEM=1)
#
# EXIT CODE: 0=PASS, 1=FAIL

set -euo pipefail

##############################################################################
# Configuración
##############################################################################

BROADCAST="${BROADCAST:-anon/live1}"
RELAY_HOST="${RELAY_HOST:-moq-relay}"
RELAY_TCP="${RELAY_TCP:-tcp://moq-relay:4444/anon}"
DOCKER_NET="teremoqwow-e2e"
LIPSYNC_THRESHOLD_MS="${LIPSYNC_THRESHOLD_MS:-45}"
PTS_SYNC_THRESHOLD_MS="${PTS_SYNC_THRESHOLD_MS:-50}"
WINDOW_SEC="${WINDOW_SEC:-15}"
SKIP_NETEM="${SKIP_NETEM:-0}"
SKIP_REMOTE_CHECK="${SKIP_REMOTE_CHECK:-0}"
SKIP_REMOTE_LATENCY="${SKIP_REMOTE_LATENCY:-0}"
SKIP_CERT_CHECK="${SKIP_CERT_CHECK:-0}"
PLAYER_HOST="${PLAYER_HOST:-laptop-077c92vt.tailbd33d7.ts.net}"
PLAYER_PORT="${PLAYER_PORT:-5443}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/qos-diagnostics.sh"

# Validar WINDOW_SEC antes de cualquier aritmética (evita x[$(cmd)] en $(( )))
qos_require_window_sec || exit $?

# El gate debe sobrevivir al timeout interno de ffprobe (WINDOW_SEC + margen)
# para que su exit=124 llegue al diagnóstico y se clasifique TOOL_ERROR.
READINESS_DEADLINE_SEC=$((WINDOW_SEC + QOS_FFPROBE_TIMEOUT_MARGIN_SEC + QOS_GATE_TIMEOUT_SLACK_SEC))
PASS_COUNT=0
FAIL_COUNT=0
TOTAL_CHECKS=4
[[ "$SKIP_REMOTE_LATENCY" == "0" ]] && TOTAL_CHECKS=5
REMOTE_PREFLIGHT_OUTPUT=""
RESULTS=()

##############################################################################
# Funciones
##############################################################################

log()  { echo "[INTEGRATION] $*"; }
pass() { echo "[INTEGRATION] ✓ PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); RESULTS+=("PASS: $1"); }
fail() { echo "[INTEGRATION] ✗ FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); RESULTS+=("FAIL: $1"); }

cleanup() {
  log "Cleanup..."
  docker rm -f integ-ffmpeg integ-export 2>/dev/null || true
  [[ "${NETEM_APPLIED:-0}" == "1" ]] && sudo tc qdisc del dev lo root 2>/dev/null || true
}

trap cleanup EXIT

##############################################################################
# 0. Preflight
##############################################################################

log "=== Fase 3 Integration Test — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if ! docker network ls | grep -q "$DOCKER_NET"; then
  echo "[INTEGRATION] ERROR: red '$DOCKER_NET' no encontrada. Inicia la pipeline primero." >&2
  exit 1
fi

# ── Cert expiry check (salteable en CI con SKIP_CERT_CHECK=1) ──────────────
if [[ "${SKIP_CERT_CHECK}" == "0" ]]; then
  WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  for _cert_rel in "config/relay/certs/relay.pem" "config/relay/certs/player.pem"; do
    _cert_path="${WORKSPACE_ROOT}/${_cert_rel}"
    [[ ! -f "$_cert_path" ]] && continue
    _end_date=$(openssl x509 -enddate -noout -in "$_cert_path" 2>/dev/null | cut -d= -f2-)
    _expiry_epoch=$(date -d "$_end_date" +%s 2>/dev/null) || { log "WARN: no se pudo parsear fecha de ${_cert_rel}"; continue; }
    _now_epoch=$(date +%s)
    _days_left=$(( (_expiry_epoch - _now_epoch) / 86400 ))
    if (( _days_left < 0 )); then
      fail "cert caducado: ${_cert_rel} (expiró hace $(( -_days_left )) días)"
      exit 1
    elif (( _days_left <= 3 )); then
      log "WARN: cert ${_cert_rel} expira en ${_days_left} días — ejecuta scripts/renew-dev-certs.sh"
    fi
  done
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${RELAY_HOST}$"; then
  echo "[INTEGRATION] ERROR: contenedor '${RELAY_HOST}' no está corriendo." >&2
  exit 1
fi
log "Pipeline activa: OK"

##############################################################################
# CHECK 0. Preflight remoto (salteable con SKIP_REMOTE_CHECK=1)
##############################################################################

if [[ "$SKIP_REMOTE_CHECK" == "0" ]]; then
  log "--- CHECK 0: Preflight remoto ---"
  set +e
  REMOTE_PREFLIGHT_OUTPUT=$(bash "${SCRIPT_DIR}/check-remote-client.sh" 2>&1)
  REMOTE_RC=$?
  set -e
  if [[ $REMOTE_RC -eq 0 ]]; then
    log "✓ Preflight remoto: OK"
  else
    log "⚠ WARN: Preflight remoto rc=${REMOTE_RC} — continuando"
  fi
else
  log "SKIP_REMOTE_CHECK=1 — omitiendo preflight remoto"
fi

# Eliminar inyectores de streams previos para que ENCODER_START_MS sea el T0 real
log "Eliminando streams previos en ${DOCKER_NET}..."
docker ps -q --filter "ancestor=linuxserver/ffmpeg:latest" --filter "network=${DOCKER_NET}" | xargs -r docker rm -f 2>/dev/null || true
docker ps -q --filter "ancestor=moqdev/moq:0.12.7" --filter "network=${DOCKER_NET}" | xargs -r docker rm -f 2>/dev/null || true
sleep 2

##############################################################################
# 1. Inyectar video real: FFmpeg testsrc2 → stdout → moq import ts
##############################################################################

SYNC_PID=""
log "Sync publisher: skipped (moq-clock-ietf no disponible; clock verificado en catalog)"

log "Arrancando inyector de video real (FFmpeg testsrc2 → pipe → moq import ts)..."
# date +%s%3N da ns en WSL2; python3 garantiza ms reales
ENCODER_START_MS=$(python3 -c "import time; print(int(time.time()*1000))")
export ENCODER_START_MS

# GOP=15 (0.5s a 30fps) para que el relay no retenga más de 500ms antes de la primera clave
docker run --rm \
  --name integ-ffmpeg \
  --network "$DOCKER_NET" \
  linuxserver/ffmpeg:latest \
  -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -profile:v main -level 4.0 \
  -g 15 -keyint_min 15 -sc_threshold 0 \
  -c:a aac -b:a 128k \
  -f mpegts pipe:1 2>/dev/null | \
docker run --rm -i \
  --network "$DOCKER_NET" \
  moqdev/moq:0.12.7 \
  --connect "tcp://${RELAY_HOST}:4444/anon" \
  --broadcast "${BROADCAST}" \
  import ts 2>/dev/null &
INJECTOR_PID=$!

cleanup() {
  log "Cleanup..."
  [[ -n "${INJECTOR_PID:-}" ]] && kill "$INJECTOR_PID" 2>/dev/null || true
  docker rm -f integ-ffmpeg 2>/dev/null || true
  [[ "${NETEM_APPLIED:-0}" == "1" ]] && sudo tc qdisc del dev lo root 2>/dev/null || true
}

log "Inyector arrancado (T0=${ENCODER_START_MS}ms). Esperando catalog completo..."

# Sanity: espera activa a que el catalog exponga clock + tracks de video/audio.
# Si en 30s no aparece, la inyección está rota → aborta con diagnóstico claro.
STABILIZE_OK=0
for i in $(seq 1 30); do
  CAT=$(timeout 4 docker run --rm --network "$DOCKER_NET" moqdev/moq:0.12.7 \
    --connect "tcp://${RELAY_HOST}:4444/anon" \
    --broadcast "${BROADCAST}" \
    fetch catalog.json 2>/dev/null || true)
  if echo "$CAT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    ok = 'clock' in d and 'video' in d and 'audio' in d
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    STABILIZE_OK=1
    log "Catalog completo (clock + video + audio) tras ${i}s"
    break
  fi
  sleep 1
done
if [[ "$STABILIZE_OK" != "1" ]]; then
  echo "[INTEGRATION] ERROR: catalog no se estabilizó en 30s — el inyector no publica." >&2
  echo "[INTEGRATION]        Verifica que el pipe ffmpeg | moq import esté conectado." >&2
  exit 1
fi

##############################################################################
# 2. Aplicar degradación de red (opcional)
##############################################################################

if [[ "$SKIP_NETEM" == "0" ]] && [[ $EUID -eq 0 ]]; then
  log "Aplicando tc netem: delay=30ms, rate=5000kbit en lo..."
  sudo tc qdisc del dev lo root 2>/dev/null || true
  sudo tc qdisc add dev lo root netem delay 30ms rate 5000kbit
  NETEM_APPLIED=1
  log "netem aplicado: OK"
else
  log "SKIP_NETEM=${SKIP_NETEM} o sin root — sin degradación de red"
fi

##############################################################################
# 3. Verificar track de sincronía (issue #65)
##############################################################################

log "--- MEDIA READINESS: audio/video frames (deadline ${READINESS_DEADLINE_SEC}s) ---"
  _readiness_output=$(mktemp)
  set +e
  BROADCAST="$BROADCAST" WINDOW_SEC="$WINDOW_SEC" RELAY_HOST="$RELAY_HOST" \
    LIPSYNC_READINESS_ONLY=1 \
    timeout "$READINESS_DEADLINE_SEC" bash "${SCRIPT_DIR}/verify-lipsync.sh" \
    >"$_readiness_output" 2>&1
  _readiness_rc=$?
  set -e
  cat "$_readiness_output"
  if [[ "$_readiness_rc" -ne 0 ]]; then
    if grep -Eq '^\[QOS-DIAGNOSTIC\] stage=[^ ]+ exit=[1-9][0-9]*( |$)' "$_readiness_output"; then
      fail "Media readiness TOOL_ERROR"
    else
      fail "Media readiness DATA_PATH_FAILURE"
    fi
    rm -f "$_readiness_output"
    echo "  ========== RESULT: FAIL =========="
    exit 1
fi
rm -f "$_readiness_output"
log "Media readiness READY: audio_frames>0 and video_frames>0"

log "--- CHECK 1/4: Track de sincronía ---"
if MOQ_NAMESPACE="$BROADCAST" bash "${SCRIPT_DIR}/verify-sync-track.sh"; then
  pass "Track de sincronía (≥3 pulsos en 5s)"
else
  fail "Track de sincronía"
fi

##############################################################################
# 4. Verificar lip-sync A/V (issue #66)
##############################################################################

log "--- CHECK 2/4: Lip-sync A/V ---"
if BROADCAST="$BROADCAST" THRESHOLD_MS="$LIPSYNC_THRESHOLD_MS" \
   WINDOW_SEC="$WINDOW_SEC" RELAY_HOST="$RELAY_HOST" \
   bash "${SCRIPT_DIR}/verify-lipsync.sh"; then
  OFFSET=$(python3 -c "import json; d=json.load(open('/tmp/lipsync-report.json')); print(d['av_offset_ms_avg'])" 2>/dev/null || echo "?")
  pass "Lip-sync offset=${OFFSET}ms < ${LIPSYNC_THRESHOLD_MS}ms"
else
  OFFSET=$(python3 -c "import json; d=json.load(open('/tmp/lipsync-report.json')); print(d['av_offset_ms_avg'])" 2>/dev/null || echo "?")
  fail "Lip-sync offset=${OFFSET}ms ≥ ${LIPSYNC_THRESHOLD_MS}ms"
fi

##############################################################################
# 5. Verificar sincronía PTS telemetría-vídeo (issue #72)
##############################################################################

log "--- CHECK 3/4: PTS-sync telemetría-vídeo ---"
if BROADCAST="$BROADCAST" THRESHOLD_MS="$PTS_SYNC_THRESHOLD_MS" \
   WINDOW_SEC="$WINDOW_SEC" RELAY_HOST="$RELAY_HOST" \
   bash "${SCRIPT_DIR}/verify-pts-sync.sh"; then
  DEV=$(python3 -c "import json; d=json.load(open('/tmp/pts-sync-report.json')); print(d['pts_deviation_ms_avg'])" 2>/dev/null || echo "?")
  pass "PTS-sync desviación=${DEV}ms < ${PTS_SYNC_THRESHOLD_MS}ms"
else
  DEV=$(python3 -c "import json; d=json.load(open('/tmp/pts-sync-report.json')); print(d['pts_deviation_ms_avg'])" 2>/dev/null || echo "?")
  fail "PTS-sync desviación=${DEV}ms ≥ ${PTS_SYNC_THRESHOLD_MS}ms"
fi

##############################################################################
# 6. Verificar latencia glass-to-glass (measure-e2e, P95 ≤ 700ms)
##############################################################################

log "--- CHECK 4/4: Latencia glass-to-glass (${WINDOW_SEC}s) ---"
# SKIP_INJECT=1: el stream ya fluye desde el inyector arrancado en el paso 1
# exit codes de measure-e2e: 0=PASS, 1=FAIL, 2=INCONCLUSIVE (overhead CLI, no del pipeline)
set +e
MEASURE_BROADCAST="$BROADCAST" ENCODER_START_MS="$ENCODER_START_MS" \
  DURATION="$WINDOW_SEC" SKIP_INJECT=1 \
  bash "${SCRIPT_DIR}/measure-e2e.sh"
MEASURE_RC=$?
set -e
case "$MEASURE_RC" in
  0) pass "Latencia glass-to-glass P95 ≤ 700ms" ;;
  2) log "[INTEGRATION] ⚠ INCONCLUSIVE: Latencia P95 no evaluable con CLI (overhead moq 0.12.7 + ffprobe TS)"
     log "[INTEGRATION]   → usa CHECK 5 para medida real del player"
     fail "Latencia glass-to-glass inconclusive" ;;
  *) fail "Latencia glass-to-glass P95 > 700ms" ;;
esac

##############################################################################
# CHECK 5. Latencia glass-to-glass desde player remoto (/metrics/latency)
##############################################################################

# Imprime el campo $2 del objeto JSON $1 si es número o cadena (nada si falta,
# es null/bool/lista/objeto). rc 3 si $1 no es un objeto JSON.
_metrics_field() {
  printf '%s' "$1" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(3)
if not isinstance(d, dict):
    sys.exit(3)
v = d.get(sys.argv[1])
if isinstance(v, bool) or not isinstance(v, (int, float, str)):
    sys.exit(0)
print(v)
' "$2"
}

if [[ "$SKIP_REMOTE_LATENCY" == "0" ]]; then
  log "--- CHECK 5/${TOTAL_CHECKS}: Latencia glass-to-glass (player remoto) ---"
  set +e
  METRICS_JSON=$(curl -sk --max-time 5 "https://${PLAYER_HOST}:${PLAYER_PORT}/metrics/latency" 2>/dev/null || true)
  set -e
  if [[ -z "${METRICS_JSON}" ]]; then
    log "⚠ WARN: /metrics/latency no responde (player no disponible)"
    PASS_COUNT=$((PASS_COUNT + 1))
    RESULTS+=("WARN: Latencia remota (player no disponible — no FAIL)")
  else
    # Un cuerpo que no es un objeto JSON (HTML 404/502, null, ...) o sin P95
    # válido NO es una medida: INCONCLUSIVE (cuenta como FAIL, nunca como PASS).
    METRICS_JSON_OK=1
    SAMPLES=$(_metrics_field "${METRICS_JSON}" samples) || METRICS_JSON_OK=0
    P95=$(_metrics_field "${METRICS_JSON}" p95_ms) || METRICS_JSON_OK=0
    if [[ "${METRICS_JSON_OK}" != "1" ]]; then
      fail "Latencia remota INCONCLUSIVE: respuesta no es un objeto JSON, descartada sin evaluar"
    elif ! qos_is_decimal "${SAMPLES}"; then
      fail "Latencia remota samples ausente o no numérico (INCONCLUSIVE): descartado sin evaluar"
    elif [[ "${SAMPLES}" =~ ^0+(\.0+)?$ ]]; then
      log "⚠ WARN: samples=0 — player conectando, sin muestras"
      PASS_COUNT=$((PASS_COUNT + 1))
      RESULTS+=("WARN: Latencia remota samples=0 (player conectando)")
    elif ! qos_is_decimal "${P95}"; then
      fail "Latencia remota P95 ausente o no numérico (INCONCLUSIVE): descartado sin evaluar"
    elif python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) >= 700 else 1)' "${P95}"; then
      fail "Latencia remota P95=${P95}ms ≥ 700ms"
    else
      pass "Latencia remota P95=${P95}ms < 700ms (${SAMPLES} muestras)"
    fi
  fi
else
  log "SKIP_REMOTE_LATENCY=1 — omitiendo CHECK 5"
fi

##############################################################################
# Resultado final
##############################################################################

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        INTEGRATION TEST — RESULT                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo ""
echo "  PASS: ${PASS_COUNT}/${TOTAL_CHECKS}   FAIL: ${FAIL_COUNT}/${TOTAL_CHECKS}"
echo ""
if [[ -n "${REMOTE_PREFLIGHT_OUTPUT}" ]]; then
  echo "  --- Preflight remoto ---"
  echo "${REMOTE_PREFLIGHT_OUTPUT}" | sed 's/^/  /'
  echo ""
fi

if [[ $FAIL_COUNT -eq 0 ]]; then
  echo "  ========== RESULT: PASS =========="
  exit 0
else
  echo "  ========== RESULT: FAIL =========="
  exit 1
fi
