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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS_COUNT=0
FAIL_COUNT=0
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
if ! docker ps --format '{{.Names}}' | grep -q "^${RELAY_HOST}$"; then
  echo "[INTEGRATION] ERROR: contenedor '${RELAY_HOST}' no está corriendo." >&2
  exit 1
fi
log "Pipeline activa: OK"

##############################################################################
# 1. Inyectar video real: FFmpeg testsrc2 → stdout → moq import ts
##############################################################################

# ── Track de sincronía: moq-clock-ietf no disponible en este entorno. ────────
# El relay incluye clock en el catalog; verify-sync-track.sh lo verifica.
SYNC_PID=""
log "Sync publisher: skipped (moq-clock-ietf no disponible; clock verificado en catalog)"

# ── Inyectar video real: FFmpeg → stdout → moq import ts ─────────────────────
log "Arrancando inyector de video real (FFmpeg testsrc2 → pipe → moq import ts)..."
ENCODER_START_MS=$(date +%s%3N)
export ENCODER_START_MS

# Sin -d: el stdout del contenedor FFmpeg debe fluir al pipe directamente.
# Con -d la salida va al daemon Docker y el pipe queda vacío.
docker run --rm \
  --name integ-ffmpeg \
  --network "$DOCKER_NET" \
  linuxserver/ffmpeg:latest \
  -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -profile:v main -level 4.0 \
  -g 60 -keyint_min 60 \
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

log "Inyector arrancado (T0=${ENCODER_START_MS}ms). Esperando 8s para estabilizar..."
sleep 8

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
if MEASURE_BROADCAST="$BROADCAST" ENCODER_START_MS="$ENCODER_START_MS" \
   DURATION="$WINDOW_SEC" SKIP_INJECT=1 \
   bash "${SCRIPT_DIR}/measure-e2e.sh" 2>/dev/null; then
  pass "Latencia glass-to-glass P95 ≤ 700ms"
else
  fail "Latencia glass-to-glass P95 > 700ms"
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
echo "  PASS: ${PASS_COUNT}/4   FAIL: ${FAIL_COUNT}/4"
echo ""

if [[ $FAIL_COUNT -eq 0 ]]; then
  echo "  ========== RESULT: PASS =========="
  exit 0
else
  echo "  ========== RESULT: FAIL =========="
  exit 1
fi
