#!/usr/bin/env bash

################################################################################
# measure-e2e.sh
#
# Automatización para medir latencia glass-to-glass Fase 0.
#
# Uso:
#   ./measure-e2e.sh                    # Ejecutar pipeline completa (default 300s)
#   ./measure-e2e.sh --duration 60      # Medir durante 60s
#   ./measure-e2e.sh --analyze FILE.csv # Analizar CSV existente (sin arrancar)
#
# Criterio de aceptación:
#   - P95 latencia ≤ 700ms
#   - ≥ 1000 muestras
#   Exit code: 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE
#
################################################################################

set -u  # Error on unset variables

# ============================================================================
# Configuration
# ============================================================================

DURATION="${DURATION:-300}"              # seconds (5 min default)
SKIP_INJECT="${SKIP_INJECT:-0}"          # 1 = omitir inyección (stream ya activo)
LATENCY_OUTPUT_FILE="/tmp/latency-results.csv"
LATENCY_RAW_FILE="/tmp/latency-raw.jsonl"
ENCODER_LOG="/tmp/encoder-log.txt"
TEST_VIDEO="/tmp/test-5min.mp4"

PLAYER_HOST="${PLAYER_HOST:-localhost}"
PLAYER_PORT="${PLAYER_PORT:-5173}"
PLAYER_METRICS_URL="http://${PLAYER_HOST}:${PLAYER_PORT}/metrics/latency"

P95_THRESHOLD_MS=700
MIN_SAMPLES=1000

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Utilities
# ============================================================================

log_info() {
  echo "[INFO] $*" >&2
}

log_warn() {
  echo -e "${YELLOW}[WARN] $*${NC}" >&2
}

log_error() {
  echo -e "${RED}[ERROR] $*${NC}" >&2
}

log_success() {
  echo -e "${GREEN}[SUCCESS] $*${NC}" >&2
}

check_command() {
  if ! command -v "$1" &> /dev/null; then
    log_error "Command not found: $1"
    return 1
  fi
}

# ============================================================================
# Pre-flight checks
# ============================================================================

preflight_checks() {
  log_info "Running pre-flight checks..."

  if ! check_command docker; then
    log_error "docker is required"
    return 1
  fi

  # Require relay running (moq-relay container in teremoqwow-e2e network)
  if ! docker network ls | grep -q teremoqwow-e2e; then
    log_error "Docker network 'teremoqwow-e2e' not found."
    log_error "Start the dev pipeline first: docker compose -f config/relay/... up"
    return 1
  fi
  if ! docker ps --format '{{.Names}}' | grep -q '^moq-relay$'; then
    log_error "Container 'moq-relay' not running."
    log_error "Start the dev pipeline before running this script."
    return 1
  fi
  if ! docker ps --format '{{.Names}}' | grep -q '^moq-import$'; then
    log_error "Container 'moq-import' (SRT import) not running."
    log_error "Start the dev pipeline before running this script."
    return 1
  fi

  log_success "Pre-flight checks passed"
  return 0
}

# ============================================================================
# Generate test video
# ============================================================================

generate_test_video() {
  if [ -f "$TEST_VIDEO" ]; then
    log_info "Test video already exists: $TEST_VIDEO"
    return 0
  fi
  
  log_info "Generating 5-minute test video with pattern..."
  
  ffmpeg -f lavfi \
    -i "testsrc=size=1280x720:duration=300" \
    -f lavfi -i "sine=f=440:d=300" \
    -c:v libx265 -preset veryfast \
    -c:a aac \
    -y "$TEST_VIDEO" \
    2>&1 | grep -E "frame=|Duration|time=" || true
  
  if [ ! -f "$TEST_VIDEO" ]; then
    log_error "Failed to generate test video"
    return 1
  fi
  
  log_success "Test video generated: $TEST_VIDEO ($(du -h "$TEST_VIDEO" | cut -f1))"
  return 0
}

# ============================================================================
# Capture latency metrics from player
# ============================================================================

capture_metrics() {
  local duration="$1"
  local output_file="$2"
  local relay_net="teremoqwow-e2e"
  local relay_host="moq-relay"
  local export_name="measure-export"
  local broadcast="${MEASURE_BROADCAST:-anon/live1}"

  log_info "Starting MoQ export SRT sink for real latency capture..."
  rm -f "$output_file" "$LATENCY_RAW_FILE"

  # Cleanup de exportador al salir
  trap 'docker rm -f "$export_name" 2>/dev/null || true' RETURN

  docker rm -f "$export_name" 2>/dev/null || true
  docker run -d --rm \
    --name "$export_name" \
    --network "$relay_net" \
    moqdev/moq:latest \
    --connect "tcp://${relay_host}:4444/anon" \
    --broadcast "$broadcast" \
    export ts --listen '[::]:9002' >/dev/null 2>&1 || {
    log_warn "No se pudo arrancar el exportador — abortando captura"
    return 1
  }

  sleep 2

  # T_START = epoch ms en el que FFmpeg comenzó a inyectar (exportado desde main)
  local T_START="${ENCODER_START_MS:-0}"
  if [[ "$T_START" == "0" ]]; then
    log_warn "ENCODER_START_MS no definido; T_START = ahora"
    T_START=$(date +%s%3N)
  fi

  log_info "Midiendo latencia real con ffprobe durante ${duration}s (T_START=${T_START}ms)..."

  # ffprobe consume el SRT, emite frames en formato compact (una línea por frame).
  # Por cada frame de vídeo calculamos:
  #   latency = wallclock_recibido - T_START - pts_ms_del_frame
  # Esto mide el retardo real extremo a extremo a través del stack MoQ.
  docker run --rm \
    --network "$relay_net" \
    linuxserver/ffmpeg:latest \
    ffprobe -v quiet \
    -show_frames -select_streams v:0 \
    -print_format compact \
    -read_intervals "%+${duration}" \
    "srt://${export_name}:9002" 2>/dev/null | \
  while IFS='|' read -ra fields; do
    T_NOW=$(date +%s%3N)
    for field in "${fields[@]}"; do
      if [[ "$field" == pkt_pts_time=* ]]; then
        pts_s="${field#*=}"
        latency_ms=$(python3 -c "
import sys
try:
    t_start = int($T_START)
    t_now = int($T_NOW)
    pts_ms = int(float('$pts_s') * 1000)
    lat = t_now - t_start - pts_ms
    print(max(0, lat))
except:
    print(0)
" 2>/dev/null || echo 0)
        if [[ "$latency_ms" -gt 0 && "$latency_ms" -lt 10000 ]]; then
          echo "$latency_ms" >> "$output_file"
          echo "{\"timestamp_ms\": $T_NOW, \"latency_ms\": $latency_ms}" >> "$LATENCY_RAW_FILE"
        fi
      fi
    done
  done

  local sample_count=0
  [[ -f "$output_file" ]] && sample_count=$(wc -l < "$output_file")
  log_success "Capturadas $sample_count muestras de latencia real"
  return 0
}

# ============================================================================
# Analyze latency data
# ============================================================================

analyze_latency() {
  local input_file="$1"
  
  if [ ! -f "$input_file" ]; then
    log_error "Latency file not found: $input_file"
    return 1
  fi
  
  log_info "Analyzing latency data from: $input_file"
  
  local sample_count=$(wc -l < "$input_file")

  # Calcular percentiles con sort + awk
  local percentiles=$(sort -n "$input_file" | awk -v n="$sample_count" '
    BEGIN {
      p50_idx = int(n * 0.5);
      p95_idx = int(n * 0.95);
      p99_idx = int(n * 0.99);
    }
    NR == p50_idx { p50 = $1 }
    NR == p95_idx { p95 = $1 }
    NR == p99_idx { p99 = $1 }
    END {
      if (p50 == 0) p50 = $(int(n * 0.5));
      if (p95 == 0) p95 = $(int(n * 0.95));
      if (p99 == 0) p99 = $(int(n * 0.99));
      printf "p50:%d,p95:%d,p99:%d", int(p50), int(p95), int(p99);
    }
  ')
  
  # Parse results
  local p50=$(echo "$percentiles" | cut -d: -f2 | cut -d, -f1)
  local p95=$(echo "$percentiles" | cut -d: -f2 | cut -d, -f2)
  local p99=$(echo "$percentiles" | cut -d: -f2 | cut -d, -f3)
  
  # Fallback si awk no parseó bien
  if [ -z "$p50" ] || [ "$p50" = "0" ]; then
    p50=$(awk '{sum+=$1; print int(sum/NR)}' "$input_file" | tail -1)
  fi
  if [ -z "$p95" ] || [ "$p95" = "0" ]; then
    p95=$(sort -n "$input_file" | awk -v n="$sample_count" 'NR == int(n * 0.95) {print int($1)}')
  fi
  if [ -z "$p99" ] || [ "$p99" = "0" ]; then
    p99=$(sort -n "$input_file" | awk -v n="$sample_count" 'NR == int(n * 0.99) {print int($1)}')
  fi
  
  # Output results
  echo ""
  echo "╔════════════════════════════════════════════════════════════╗"
  echo "║           LATENCY GLASS-TO-GLASS RESULTS (Fase 0)          ║"
  echo "╚════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  Samples:     $sample_count"
  echo "  P50 latency: ${p50}ms"
  echo "  P95 latency: ${p95}ms (threshold: ${P95_THRESHOLD_MS}ms)"
  echo "  P99 latency: ${p99}ms"
  echo ""
  
  # Determine pass/fail
  local status="UNKNOWN"
  local exit_code=2
  
  if [ "$sample_count" -lt "$MIN_SAMPLES" ]; then
    status="INCONCLUSIVE"
    log_warn "Too few samples: $sample_count < $MIN_SAMPLES"
    exit_code=2
  elif [ "$p95" -le "$P95_THRESHOLD_MS" ]; then
    status="PASS ✓"
    log_success "P95 latency within budget!"
    exit_code=0
  else
    status="FAIL ✗"
    log_error "P95 latency exceeds threshold: ${p95}ms > ${P95_THRESHOLD_MS}ms"
    exit_code=1
  fi
  
  echo "  Status:      $status"
  echo ""
  
  # Troubleshooting hints
  if [ "$exit_code" != "0" ]; then
    echo "  📋 Troubleshooting:"
    if [ "$p95" -gt $((P95_THRESHOLD_MS + 100)) ]; then
      echo "     - Check MediaMTX buffer: curl http://localhost:9997/stats"
      echo "     - Check relay RTT: docker logs <relay-container> | grep rtt"
      echo "     - Check player decode: browser dev tools → Performance tab"
    fi
    if [ "$sample_count" -lt "$MIN_SAMPLES" ]; then
      echo "     - Pocas muestras: verifica que moq-import y moq-relay están activos"
      echo "     - Aumenta --duration o comprueba la red teremoqwow-e2e"
    fi
    echo ""
  fi
  
  return "$exit_code"
}

# ============================================================================
# Main
# ============================================================================

main() {
  local mode="run"  # "run" (full) o "analyze" (CSV only)
  
  # Parse arguments
  while [ $# -gt 0 ]; do
    case "$1" in
      --duration)
        DURATION="$2"
        shift 2
        ;;
      --analyze)
        mode="analyze"
        LATENCY_OUTPUT_FILE="$2"
        shift 2
        ;;
      --help)
        cat << EOF
Usage: $0 [OPTIONS]

OPTIONS:
  --duration SECONDS    Measurement duration in seconds (default: 300)
  --analyze FILE.csv    Analyze existing CSV file (skip capture)
  --help               Show this message

CRITERIA (Fase 0):
  - P95 latency ≤ 700ms
  - ≥ 1000 samples
  - Exit code: 0=PASS, 1=FAIL, 2=INCONCLUSIVE

EXAMPLE:
  ./measure-e2e.sh --duration 60
  ./measure-e2e.sh --analyze /tmp/latency-results.csv

EOF
        exit 0
        ;;
      *)
        log_error "Unknown option: $1"
        exit 1
        ;;
    esac
  done
  
  log_info "Teremoqwow Latency Measurement — Fase 0"
  echo ""
  
  if [ "$mode" = "analyze" ]; then
    # Analyze mode: skip capture, only analyze
    analyze_latency "$LATENCY_OUTPUT_FILE"
    return $?
  fi
  
  # Full run mode: preflight → generate video → capture → analyze
  
  if ! preflight_checks; then
    log_error "Pre-flight checks failed. Asegúrate de que la pipeline dev está arriba:"
    echo "  docker compose -f config/relay/docker-compose.yml up -d"
    exit 1
  fi

  local injector_pid=""
  if [[ "$SKIP_INJECT" == "0" ]]; then
    # Inyectar video real: FFmpeg → stdout pipe → moq import ts
    log_info "Arrancando inyector FFmpeg (testsrc2 → pipe → moq import ts)..."
    docker rm -f measure-ffmpeg 2>/dev/null || true
    ENCODER_START_MS=$(date +%s%3N)
    export ENCODER_START_MS
    docker run -d --rm \
      --name measure-ffmpeg \
      --network teremoqwow-e2e \
      linuxserver/ffmpeg:latest \
      -re \
      -f lavfi -i "testsrc2=size=1280x720:rate=30" \
      -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
      -c:v libx264 -preset ultrafast -tune zerolatency \
      -c:a aac -b:a 128k \
      -f mpegts pipe:1 2>/dev/null | \
    docker run --rm -i \
      --network teremoqwow-e2e \
      moqdev/moq:latest \
      --connect "tcp://moq-relay:4444/anon" \
      --broadcast "${MEASURE_BROADCAST:-anon/live1}" \
      import ts 2>/dev/null &
    injector_pid=$!
    log_info "Inyector arrancado (T0=${ENCODER_START_MS}ms). Esperando 3s..."
    sleep 3
  else
    log_info "SKIP_INJECT=1 — usando stream ya activo (T0=${ENCODER_START_MS:-0}ms)"
  fi

  # Capturar latencia real con ffprobe en el extremo de salida
  capture_metrics "$DURATION" "$LATENCY_OUTPUT_FILE"
  local capture_result=$?

  # Detener inyector propio (si fue arrancado aquí)
  [[ -n "$injector_pid" ]] && kill "$injector_pid" 2>/dev/null || true
  docker rm -f measure-ffmpeg 2>/dev/null || true

  [[ $capture_result -ne 0 ]] && { log_error "Captura fallida"; exit 1; }

  analyze_latency "$LATENCY_OUTPUT_FILE"
  local result=$?

  log_info "Resultados detallados: $LATENCY_OUTPUT_FILE"

  return $result
}

# Execute
main "$@"
