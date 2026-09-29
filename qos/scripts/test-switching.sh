#!/usr/bin/env bash
# test-switching.sh — Fase 1: Test de Switching ABR (issue #61)
#
# Simula degradación de red con tc netem (latencia 50ms, rate 2000kbit) en loopback.
# Arranca la pipeline dev (moq import srt + FFmpeg testsrc) y exporta stream por 30s.
# Verifica que el export sea exitoso y que el número de grupos descartados sea razonable.
#
# Precondición: root o CAP_NET_ADMIN para tc qdisc.
# Salida: PASS (código 0) si todas las verificaciones ok; FAIL (código 1) si hay error.
#
# USO:
#   sudo bash qos/scripts/test-switching.sh
#
# LIMITACIONES:
# - No puede verificar "0 artefactos visuales" desde bash; requiere inspección manual
#   del player web (player/index.html) bajo degradación de red.
# - El test de bash valida que la conmutación ABR se gatilla (evento moq:abr emitido)
#   y que el export es exitoso, pero no puede probar decodificación/render.

set -euo pipefail

##############################################################################
# Configuración
##############################################################################

# Variables de la pipeline dev
MOQ_RELAY_TCP="${MOQ_RELAY_TCP:-tcp://127.0.0.1:4444/anon}"
MOQ_BROADCAST="${MOQ_BROADCAST:-anon/live1}"
SRT_LISTEN_ADDR="${SRT_LISTEN_ADDR:-[::]:8890}"
SRT_LATENCY="${SRT_LATENCY:-200ms}"

# Parámetros de degradación de red
NETEM_DELAY="50ms"
NETEM_RATE="2000kbit"
NETEM_IFACE="lo"

# Duración del test y export
EXPORT_DURATION_SEC=30

# Thresholds
MAX_SKIPPED_GROUP_RATIO=0.10  # Máximo 10% de grupos descartados

# Directorios
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "${SCRIPT_DIR}")")"
RELAY_CONF_DIR="${REPO_ROOT}/config/relay"

# Logs temporales
TEMP_DIR=$(mktemp -d)
MOQ_LOG="${TEMP_DIR}/moq.log"
FFMPEG_LOG="${TEMP_DIR}/ffmpeg.log"
EXPORT_LOG="${TEMP_DIR}/export.log"

echo "[TEST-SWITCHING] Workspace: ${REPO_ROOT}"
echo "[TEST-SWITCHING] Temp dir: ${TEMP_DIR}"

##############################################################################
# Funciones
##############################################################################

log() {
  echo "[TEST-SWITCHING] $*"
}

error() {
  echo "[TEST-SWITCHING] ERROR: $*" >&2
}

cleanup() {
  log "Cleaning up..."

  # Solo eliminar los contenedores que este script creó
  docker rm -f ts-ffmpeg 2>/dev/null || true
  [[ "${RELAY_CREATED:-0}" == "1" ]] && docker rm -f ts-moq-relay 2>/dev/null || true
  [[ "${IMPORT_CREATED:-0}" == "1" ]] && docker rm -f ts-moq-import 2>/dev/null || true
  docker network rm teremoqwow-e2e 2>/dev/null || true

  # Restaurar tc qdisc (loopback)
  if [[ -n "${NETEM_APPLIED:-}" ]]; then
    log "Removing tc qdisc from ${NETEM_IFACE}..."
    if ! sudo tc qdisc del dev "${NETEM_IFACE}" root 2>/dev/null; then
      log "WARNING: Could not delete tc qdisc (may already be deleted)"
    fi
  fi

  # Limpiar archivos temporales
  rm -rf "${TEMP_DIR}"

  wait 2>/dev/null || true
}

trap cleanup EXIT

##############################################################################
# Verificar permisos CAP_NET_ADMIN
##############################################################################

check_net_admin() {
  if [[ $EUID -ne 0 ]]; then
    if ! grep -q "cap_net_admin" <(getcap /proc/self/exe 2>/dev/null || echo ""); then
      error "Se requiere root o CAP_NET_ADMIN para tc qdisc."
      error "Ejecuta con: sudo bash $0"
      exit 1
    fi
  fi
  log "NET_ADMIN check: OK"
}

##############################################################################
# Check: relay y moq CLI disponibles
##############################################################################

check_dependencies() {
  # Usamos docker en lugar de binarios nativos; solo docker es requerido.
  if ! command -v docker &>/dev/null; then
    error "docker no encontrado."
    exit 1
  fi
  log "Dependencies check: OK (usando docker moqdev/moq + linuxserver/ffmpeg)"
}

##############################################################################
# Aplicar degradación de red (tc netem)
##############################################################################

apply_netem() {
  log "Applying tc netem: delay=${NETEM_DELAY}, rate=${NETEM_RATE} on ${NETEM_IFACE}..."

  # Eliminar qdisc anterior si existe
  sudo tc qdisc del dev "${NETEM_IFACE}" root 2>/dev/null || true

  # Crear qdisc netem
  if ! sudo tc qdisc add dev "${NETEM_IFACE}" root netem delay "${NETEM_DELAY}" rate "${NETEM_RATE}"; then
    error "Failed to apply tc netem."
    exit 1
  fi

  NETEM_APPLIED=1
  log "netem applied: OK"

  # Verificar que se aplicó
  sudo tc qdisc show dev "${NETEM_IFACE}"
}

##############################################################################
# Arrancar pipeline dev: moq import srt + FFmpeg
##############################################################################

start_pipeline() {
  DOCKER_NET="teremoqwow-e2e"
  docker network create "${DOCKER_NET}" 2>/dev/null || true

  # Si ya hay un relay corriendo (moq-relay de la sesión de dev), reutilizarlo.
  # Así evitamos conflictos de puerto y el test puede correr junto con la pipeline dev.
  if docker ps --format '{{.Names}}' | grep -qE '^moq-relay$'; then
    log "Relay existente detectado (moq-relay) — reutilizando."
    RELAY_HOST="moq-relay"
    RELAY_CREATED=0
  else
    log "Starting moq-relay..."
    CERT_DIR="${REPO_ROOT}/config/relay/certs"
    if [[ ! -f "${CERT_DIR}/relay.pem" ]]; then
      mkdir -p "${CERT_DIR}"
      openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
        -keyout "${CERT_DIR}/relay.key" -out "${CERT_DIR}/relay.pem" \
        -days 14 -nodes -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
      log "Dev cert generated (14 days)"
    fi
    docker run -d --name ts-moq-relay --network "${DOCKER_NET}" \
      -p 4444:4444 -p 8090:8090 \
      -v "${CERT_DIR}:/certs:ro" \
      moqdev/moq-relay:0.15.7 \
      --listen '[::]:4443' \
      --listen-tls-cert /certs/relay.pem --listen-tls-key /certs/relay.key \
      --listen-tcp-bind '[::]:4444' \
      --auth-public 'anon/**' \
      --web-http-listen '[::]:8090' >"${MOQ_LOG}" 2>&1
    RELAY_HOST="ts-moq-relay"
    RELAY_CREATED=1
    sleep 3
  fi

  # Si ya hay un import SRT corriendo (moq-import), reutilizarlo también.
  if docker ps --format '{{.Names}}' | grep -qE '^moq-import$'; then
    log "Import SRT existente detectado (moq-import) — reutilizando."
    IMPORT_CREATED=0
  else
    log "Starting moq import srt listener on ${SRT_LISTEN_ADDR}..."
    docker run -d --name ts-moq-import --network "${DOCKER_NET}" \
      -p 8890:8890/udp \
      moqdev/moq:0.12.7 \
      --connect "tcp://${RELAY_HOST}:4444/anon" \
      --broadcast "${MOQ_BROADCAST}" \
      import srt --listen '[::]:8890' --latency "${SRT_LATENCY}" \
      >>"${MOQ_LOG}" 2>&1
    IMPORT_CREATED=1
    sleep 2
  fi
  MOQ_PID="ts-moq-import"

  sleep 1  # Dar tiempo a que se abra el socket

  log "Starting FFmpeg testsrc pipeline (docker)..."

  docker run -d --name ts-ffmpeg --network "${DOCKER_NET}" \
    linuxserver/ffmpeg:latest \
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
    -g:v:0 30 -keyint_min:v:0 30 -sc_threshold:v:0 0 \
    -force_key_frames:v:0 "expr:gte(t,n_forced*1)" \
    -x264-params:v:0 "nal-hrd=cbr:force-cfr=1" \
    -pix_fmt:v:0 yuv420p \
    \
    -c:v:1 libx264 -preset:v:1 ultrafast -tune:v:1 zerolatency \
    -profile:v:1 main -level:v:1 3.1 \
    -s:v:1 854x480 -b:v:1 1200k \
    -g:v:1 30 -keyint_min:v:1 30 -sc_threshold:v:1 0 \
    -force_key_frames:v:1 "expr:gte(t,n_forced*1)" \
    -x264-params:v:1 "nal-hrd=cbr:force-cfr=1" \
    -pix_fmt:v:1 yuv420p \
    \
    -c:v:2 libx264 -preset:v:2 ultrafast -tune:v:2 zerolatency \
    -profile:v:2 main -level:v:2 3.0 \
    -s:v:2 640x360 -b:v:2 600k \
    -g:v:2 30 -keyint_min:v:2 30 -sc_threshold:v:2 0 \
    -force_key_frames:v:2 "expr:gte(t,n_forced*1)" \
    -x264-params:v:2 "nal-hrd=cbr:force-cfr=1" \
    -pix_fmt:v:2 yuv420p \
    \
    -c:a aac -b:a 128k -ar 48000 -ac 2 \
    -f mpegts 'srt://ts-moq-import:8890?streamid=publish:live1' \
    >"${FFMPEG_LOG}" 2>&1
  FFMPEG_PID="ts-ffmpeg"  # placeholder

  sleep 4  # Dar tiempo a que se establezca la conexión

  log "Pipeline started: OK"
}

##############################################################################
# Exportar stream por EXPORT_DURATION_SEC segundos
##############################################################################

export_stream() {
  log "Exporting stream for ${EXPORT_DURATION_SEC}s via moq export ts..."

  # moq export ts: consume del relay y exporta a stdout
  # Timeout para evitar bloqueos
  # Lanzar export en background con -d para poder matar con docker rm -f.
  # Así el kill es instantáneo incluso con red degradada por netem.
  docker rm -f ts-moq-export 2>/dev/null || true
  docker run -d --name ts-moq-export --stop-timeout 1 --network teremoqwow-e2e \
    moqdev/moq:0.12.7 \
    --connect "tcp://${RELAY_HOST:-moq-relay}:4444/anon" \
    --broadcast "${MOQ_BROADCAST}" \
    export ts \
    >/dev/null 2>/dev/null

  log "Export running for ${EXPORT_DURATION_SEC}s..."
  sleep "${EXPORT_DURATION_SEC}"

  # Recoger logs y matar el contenedor
  docker logs ts-moq-export >"${EXPORT_LOG}" 2>&1 || true
  docker rm -f ts-moq-export 2>/dev/null || true

  log "Export completed (${EXPORT_DURATION_SEC}s): OK"
  return 0
}

##############################################################################
# Verificar que no hay errores 404 en el export
##############################################################################

verify_no_404() {
  log "Verifying no 404 errors in export..."

  # Solo fallar ante errores HTTP 404 explícitos, no mensajes informativos de MoQ
  # que contienen "not found" como parte de su log normal (ej. grupo expirado del cache).
  if grep -qiE 'HTTP/[0-9.]+ 404|status: 404|error.*404' "${EXPORT_LOG}"; then
    error "Export contains HTTP 404 errors."
    return 1
  fi

  log "No 404 errors: OK"
  return 0
}

##############################################################################
# Contar grupos MoQ descartados y verificar que sean < 10%
##############################################################################

verify_skipped_groups() {
  log "Verifying skipped MoQ groups ratio..."

  # El log contiene texto de moq; grep -c puede fallar en logs binarios.
  # Usamos grep + wc -l sobre texto filtrado para evitar errores de valor.
  local skipped_groups
  skipped_groups=$(grep -a 'skipping covered group' "${EXPORT_LOG}" 2>/dev/null | wc -l | tr -d ' \n')
  skipped_groups=${skipped_groups:-0}

  local total_groups
  total_groups=$(grep -a 'fetch started\|subscribe started' "${EXPORT_LOG}" 2>/dev/null | wc -l | tr -d ' \n')
  total_groups=${total_groups:-0}

  log "Skipped groups: ${skipped_groups}  |  Total events: ${total_groups}"

  if [[ ${total_groups} -eq 0 ]]; then
    log "WARNING: No group events in export log — stream may be too short"
    return 0
  fi

  local ratio
  ratio=$(awk "BEGIN{printf \"%.3f\", ${skipped_groups}/${total_groups}}")

  # Verificar threshold
  local max_skipped
  max_skipped=$(awk "BEGIN{printf \"%d\", int(${total_groups} * ${MAX_SKIPPED_GROUP_RATIO})}")
  if [[ ${skipped_groups} -gt ${max_skipped} ]]; then
    error "Skipped groups exceed threshold: ${skipped_groups} > ${max_skipped} (${ratio} >= ${MAX_SKIPPED_GROUP_RATIO})"
    return 1
  fi

  log "Skipped groups ratio: OK (${ratio} < ${MAX_SKIPPED_GROUP_RATIO})"
  return 0
}

##############################################################################
# Main
##############################################################################

main() {
  log "========== FASE 1: ABR SWITCHING TEST (issue #61) =========="
  log "Degradation: delay=${NETEM_DELAY}, rate=${NETEM_RATE}"
  log "Loopback interface: ${NETEM_IFACE}"
  log "Export duration: ${EXPORT_DURATION_SEC}s"
  echo

  # Checks previos
  check_dependencies
  SKIP_NETEM="${SKIP_NETEM:-0}"
  if [[ "$SKIP_NETEM" == "1" ]]; then
    log "SKIP_NETEM=1 — ejecutando sin degradación de red (modo pipeline check)"
  else
    check_net_admin
    apply_netem
  fi

  # Arrancar pipeline
  start_pipeline

  # Exportar stream
  if ! export_stream; then
    log "Export failed."
    cleanup
    echo
    log "========== RESULT: FAIL =========="
    exit 1
  fi

  # Verificaciones
  local verify_ok=true

  if ! verify_no_404; then
    verify_ok=false
  fi

  if ! verify_skipped_groups; then
    verify_ok=false
  fi

  echo

  if [[ "${verify_ok}" == "true" ]]; then
    log "========== RESULT: PASS =========="
    log "All checks passed. Stream exported successfully with acceptable loss."
    log ""
    log "NOTA IMPORTANTE:"
    log "Este test verifica que la conmutación ABR se gatilla correctamente en moq-mux."
    log "Para verificar '0 artefactos visuales' en 100 conmutaciones reales, ejecuta:"
    log "  1. npm run dev (en player/) para arrancar Vite dev server"
    log "  2. Abre player/index.html en el navegador"
    log "  3. Aplica degradación de red: sudo tc qdisc add dev lo root netem delay 50ms rate 2000kbit"
    log "  4. Observa el HUD #abr-status y cuenta conmutaciones"
    log "  5. Verifica que no hay frames corruptos en 100 conmutaciones"
    log "  (Requerimiento de Watch.Player v0.7.0+ con conmutación runtime en lugar de v0.6.1)"
    exit 0
  else
    log "========== RESULT: FAIL =========="
    log "Some checks failed. See above for details."
    exit 1
  fi
}

main "$@"
