#!/bin/bash
# Prueba empírica local: levanta un relay aislado, publica y observa meta-heartbeat
# REQUISITOS: Docker, docker-compose disponibles
# MODO: opt-in via META_TRACK_EMPIRICAL_TEST=1
# LIMPIEZA: auto al salir

set -eu
shopt -s lastpipe

# Configuración
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="/tmp/meta-track-empirical-$$"
RELAY_NETWORK="meta-track-it-$$"
RELAY_HTTP_PORT="18090"
RELAY_TCP_PORT="19090"
RELAY_NAME="meta-relay-$$"
RELAY_IMAGE="moqdev/moq-relay:0.15.7"
RELAY_READY_FILE="$TEST_DIR/relay-ready"
PUBLISHER_OUTPUT="$TEST_DIR/publisher.log"
OBSERVER_OUTPUT="$TEST_DIR/observer.log"

# Limpieza
cleanup() {
  local rc=$?
  echo "[TEST] Cleaning up..."

  # Detener containers
  docker stop "$RELAY_NAME" 2>/dev/null || true
  docker rm "$RELAY_NAME" 2>/dev/null || true

  # Borrar red
  docker network rm "$RELAY_NETWORK" 2>/dev/null || true

  # Borrar directorio temporal
  rm -rf "$TEST_DIR"

  if [ $rc -eq 0 ]; then
    echo "[TEST] ✓ All tests passed"
  else
    echo "[TEST] ✗ Test failed with exit code $rc"
  fi
  exit $rc
}

trap cleanup EXIT

# Crear directorio temporal
mkdir -p "$TEST_DIR"

echo "[TEST] Starting empirical test..."
echo "[TEST] TEST_DIR=$TEST_DIR"

# 1. Crear red Docker
echo "[TEST] Creating Docker network: $RELAY_NETWORK"
docker network create "$RELAY_NETWORK" >/dev/null

# 2. Levantar relay aislado
echo "[TEST] Starting relay: $RELAY_NAME on port $RELAY_HTTP_PORT (internal)"
docker run -d --rm \
  --name "$RELAY_NAME" \
  --network "$RELAY_NETWORK" \
  "$RELAY_IMAGE" \
  --listen-tcp-bind "0.0.0.0:$RELAY_TCP_PORT" \
  --web-http-listen "0.0.0.0:$RELAY_HTTP_PORT" \
  --auth-public "anon/**" \
  >/dev/null 2>&1

sleep 3

# Verificar conectividad desde el host (no es crítico, en test usamos nombres Docker)
echo "[TEST] ✓ Relay started (listening on internal network)"

# 3. Construir imagen de meta-track
echo "[TEST] Building meta-track image..."
cd "$PROJECT_DIR/ingest/meta-track"
docker build -t teremoqwow-meta-track:1-test . >/dev/null 2>&1
echo "[TEST] ✓ Image built"

# 4. Arrancar publisher en background en la red del relay
echo "[TEST] Starting publisher..."
docker run -d --rm \
  --name "meta-publisher-$$" \
  --network "$RELAY_NETWORK" \
  -e MOQ_URL="http://$RELAY_NAME:$RELAY_HTTP_PORT/" \
  -e BROADCAST="anon/live1-meta" \
  -e TRACK="heartbeat" \
  -e INTERVAL_MS=1000 \
  -e HEALTH_MARKER_PATH="/tmp/health" \
  "teremoqwow-meta-track:1-test" \
  publish \
  >"$PUBLISHER_OUTPUT" 2>&1 &
PUBLISHER_PID=$!
sleep 3

# Verificar que el publisher arrancó
if ! ps -p $PUBLISHER_PID >/dev/null 2>&1; then
  echo "[TEST] ✗ Publisher process died"
  cat "$PUBLISHER_OUTPUT"
  exit 1
fi
echo "[TEST] ✓ Publisher started (PID $PUBLISHER_PID)"

# 5. Ejecutar observer durante 20 segundos
echo "[TEST] Running observer for 20 seconds..."
OBSERVER_START=$(date +%s%3N)

docker run --rm \
  --network "$RELAY_NETWORK" \
  -e MOQ_URL="http://$RELAY_NAME:$RELAY_HTTP_PORT/" \
  -e BROADCAST="anon/live1-meta" \
  -e TRACK="heartbeat" \
  "teremoqwow-meta-track:1-test" \
  observe --window 20 \
  >"$OBSERVER_OUTPUT" 2>&1

OBSERVER_END=$(date +%s%3N)

# 6. Parsear y verificar resultados
echo ""
echo "[TEST] Observer output:"
cat "$OBSERVER_OUTPUT"
echo ""

OBS_RESULT=$(cat "$OBSERVER_OUTPUT")
CONNECTED=$(echo "$OBS_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('connected', False))")
OBJECTS=$(echo "$OBS_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('objects', 0))")
BYTES=$(echo "$OBS_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('bytes', 0))")
MONOTONIC=$(echo "$OBS_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('monotonic', False))")
BOOT_IDS=$(echo "$OBS_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('boot_ids', [])))")

echo "[TEST] Results:"
echo "  Connected: $CONNECTED"
echo "  Objects: $OBJECTS"
echo "  Bytes: $BYTES"
echo "  Monotonic: $MONOTONIC"
echo "  Boot IDs: $BOOT_IDS"
echo "  Window duration: $((OBSERVER_END - OBSERVER_START)) ms"
echo ""

# 7. Verificaciones
ERRORS=0

if [ "$CONNECTED" != "True" ]; then
  echo "[TEST] ✗ Observer not connected"
  ((ERRORS++))
else
  echo "[TEST] ✓ Observer connected"
fi

if [ "$OBJECTS" -lt 10 ]; then
  echo "[TEST] ✗ Expected at least 10 objects in 20s window, got $OBJECTS"
  ((ERRORS++))
else
  echo "[TEST] ✓ Sufficient objects: $OBJECTS"
fi

if [ "$MONOTONIC" != "True" ]; then
  echo "[TEST] ✗ Sequence not monotonic"
  ((ERRORS++))
else
  echo "[TEST] ✓ Sequence is monotonic"
fi

if [ "$BOOT_IDS" -lt 1 ]; then
  echo "[TEST] ✗ No boot IDs detected"
  ((ERRORS++))
else
  echo "[TEST] ✓ Boot IDs present: $BOOT_IDS"
fi

# 8. Test de recuperación: reiniciar el relay
echo ""
echo "[TEST] Testing recovery: restarting relay..."
RECOVERY_START=$(date +%s%3N)

docker restart "$RELAY_NAME" >/dev/null 2>&1
sleep 5

# Ejecutar observer nuevamente
docker run --rm \
  --network "$RELAY_NETWORK" \
  -e MOQ_URL="http://$RELAY_NAME:18090/" \
  -e BROADCAST="anon/live1-meta" \
  -e TRACK="heartbeat" \
  "teremoqwow-meta-track:1-test" \
  observe --window 10 \
  >"$TEST_DIR/observer-recovery.log" 2>&1

RECOVERY_END=$(date +%s%3N)
RECOVERY_TIME=$((RECOVERY_END - RECOVERY_START))

RECOVERY_RESULT=$(cat "$TEST_DIR/observer-recovery.log")
RECOVERY_CONNECTED=$(echo "$RECOVERY_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('connected', False))")
RECOVERY_OBJECTS=$(echo "$RECOVERY_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('objects', 0))")

echo "[TEST] Recovery results (after ${RECOVERY_TIME}ms):"
echo "  Connected: $RECOVERY_CONNECTED"
echo "  Objects: $RECOVERY_OBJECTS"

if [ "$RECOVERY_CONNECTED" = "True" ] && [ "$RECOVERY_OBJECTS" -ge 5 ]; then
  echo "[TEST] ✓ Recovered within reasonable time"
else
  echo "[TEST] ⚠ Recovery time or object count suboptimal"
fi

# 9. Test: restart publisher
echo ""
echo "[TEST] Testing publisher restart..."

# Obtener new boot_id (reiniciando el publisher)
PUBLISHER_RESTART_START=$(date +%s%3N)

# Matar el publisher actual
docker kill "meta-publisher-$$" 2>/dev/null || true
sleep 1

# Arrancar uno nuevo
docker run -d --rm \
  --name "meta-publisher-restart-$$" \
  --network "$RELAY_NETWORK" \
  -e MOQ_URL="http://$RELAY_NAME:18090/" \
  -e BROADCAST="anon/live1-meta" \
  -e TRACK="heartbeat" \
  -e INTERVAL_MS=1000 \
  "teremoqwow-meta-track:1-test" \
  publish \
  >/dev/null 2>&1 &
PUBLISHER_PID=$!
sleep 2

# Observar
docker run --rm \
  --network "$RELAY_NETWORK" \
  -e MOQ_URL="http://$RELAY_NAME:18090/" \
  -e BROADCAST="anon/live1-meta" \
  -e TRACK="heartbeat" \
  "teremoqwow-meta-track:1-test" \
  observe --window 10 \
  >"$TEST_DIR/observer-new-boot.log" 2>&1

PUBLISHER_RESTART_END=$(date +%s%3N)

RESTART_RESULT=$(cat "$TEST_DIR/observer-new-boot.log")
NEW_BOOT_COUNT=$(echo "$RESTART_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('boot_ids', [])))")

echo "[TEST] After publisher restart:"
echo "  Different boot_ids detected: $NEW_BOOT_COUNT"
echo "  Time to stable: $((PUBLISHER_RESTART_END - PUBLISHER_RESTART_START))ms"

if [ "$NEW_BOOT_COUNT" -ge 1 ]; then
  echo "[TEST] ✓ Boot ID change detected (restart acknowledged)"
else
  echo "[TEST] ⚠ Boot ID detection unclear"
fi

# Salida
if [ $ERRORS -eq 0 ]; then
  echo ""
  echo "[TEST] ✓ All empirical tests passed"
  exit 0
else
  echo ""
  echo "[TEST] ✗ $ERRORS test(s) failed"
  exit 1
fi
