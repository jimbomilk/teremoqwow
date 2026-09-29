#!/usr/bin/env bash
# test-cluster.sh — issue #86
# Levanta dos relays moq-relay:0.15.7 en Docker con clustering TCP qmux,
# publica un track en relay-1 y verifica recepción en relay-2.
# Criterio: el subscriber en relay-2 recibe datos publicados en relay-1.
set -euo pipefail

RELAY_IMAGE="moqdev/moq-relay:0.15.7"
MOQ_IMAGE="moqdev/moq:0.12.7"
FFMPEG_IMAGE="linuxserver/ffmpeg:latest"
NETWORK="teremoqwow-cluster-test"
CERT_DIR="/tmp/teremoqwow-cluster/certs"
TIMEOUT=30
BROADCAST="anon/cluster-test"

log() { echo "[test-cluster] $*"; }
die() { echo "[test-cluster] ERROR: $*" >&2; exit 1; }

cleanup() {
  log "Limpiando contenedores..."
  docker rm -f relay-1 relay-2 cluster-publisher cluster-subscriber 2>/dev/null || true
  docker network rm "$NETWORK" 2>/dev/null || true
  rm -rf "$CERT_DIR"
}
trap cleanup EXIT

# ── Red y certificados ────────────────────────────────────────────────────────
log "Creando red Docker: $NETWORK"
docker network create "$NETWORK" 2>/dev/null || true

mkdir -p "$CERT_DIR"
log "Generando certificados TLS auto-firmados..."
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
  -keyout "$CERT_DIR/relay.key" -out "$CERT_DIR/relay.pem" \
  -days 1 -nodes -subj "/CN=relay-test" \
  -addext "subjectAltName=DNS:relay-1,DNS:relay-2,DNS:localhost" 2>/dev/null

# ── relay-1 (origen del broadcast) ───────────────────────────────────────────
log "Arrancando relay-1..."
docker run -d --name relay-1 \
  --network "$NETWORK" \
  -v "$CERT_DIR:/certs:ro" \
  "$RELAY_IMAGE" \
  --listen '[::]:4443' \
  --listen-tls-cert /certs/relay.pem \
  --listen-tls-key /certs/relay.key \
  --listen-tcp-bind '[::]:4444' \
  --auth-public 'anon/**' \
  --web-http-listen '[::]:8090'

# ── relay-2 (federado, conectado a relay-1 via TCP qmux) ─────────────────────
log "Arrancando relay-2 (cluster-connect → relay-1:4444)..."
# relay-2 se conecta a relay-1 como cliente qmux (no existe --cluster-* en 0.15.7).
# El relay upstream actúa como broker: relay-2 subscribe los broadcasts de relay-1.
docker run -d --name relay-2 \
  --network "$NETWORK" \
  -v "$CERT_DIR:/certs:ro" \
  "$RELAY_IMAGE" \
  --listen '[::]:4443' \
  --listen-tls-cert /certs/relay.pem \
  --listen-tls-key /certs/relay.key \
  --listen-tcp-bind '[::]:4445' \
  --auth-public 'anon/**' \
  --web-http-listen '[::]:8091' \
  --connect tcp://relay-1:4444

sleep 2

# ── Verificar que los relays están activos ────────────────────────────────────
# Verificar via logs: relay arrancado cuando muestra "listening" en web y tcp.
log "Verificando health de relay-1 (logs, poll 10s)..."
for i in $(seq 1 10); do
  docker logs relay-1 2>&1 | grep -q 'listening.*8090\|web.*8090' && break
  sleep 1
done
docker logs relay-1 2>&1 | grep -q 'listening.*8090\|web.*8090' \
  || die "relay-1 no arrancó (no aparece 'listening' en logs)"
log "relay-1 activo: $(docker logs relay-1 2>&1 | grep -E 'listening|connected' | tr '\n' '|')"

log "Verificando health de relay-2 (logs, poll 10s)..."
for i in $(seq 1 10); do
  docker logs relay-2 2>&1 | grep -q 'listening.*8091\|web.*8091' && break
  sleep 1
done
docker logs relay-2 2>&1 | grep -q 'listening.*8091\|web.*8091' \
  || die "relay-2 no arrancó (no aparece 'listening' en logs)"
log "relay-2 activo: $(docker logs relay-2 2>&1 | grep -E 'listening|connect' | tr '\n' '|')"

# ── Publisher en relay-1 ──────────────────────────────────────────────────────
log "Publicando en relay-1..."
docker run --rm --network "$NETWORK" \
  "$FFMPEG_IMAGE" \
  -re -f lavfi -i 'testsrc2=size=320x240:rate=15' \
  -f lavfi -i 'sine=frequency=440:sample_rate=44100' \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
  -c:a aac -b:a 64k -t 60 -f mpegts pipe:1 2>/dev/null | \
docker run --rm -i --network "$NETWORK" --name cluster-publisher \
  "$MOQ_IMAGE" --connect tcp://relay-1:4444/anon \
  --broadcast "$BROADCAST" import ts 2>/dev/null &
PUBLISHER_PID=$!
sleep 5

# ── Bridge: relay-1 → relay-2 (ADR-0002) ─────────────────────────────────────
# moq-relay:0.15.7 no soporta clustering vía CLI; se usa un bridge de re-publicación.
log "Arrancando bridge relay-1 → relay-2..."
docker run --rm --network "$NETWORK" \
  "$MOQ_IMAGE" --connect tcp://relay-1:4444/anon --broadcast "$BROADCAST" \
  export ts 2>/dev/null | \
docker run --rm -i --network "$NETWORK" \
  "$MOQ_IMAGE" --connect tcp://relay-2:4445/anon --broadcast "$BROADCAST" \
  import ts 2>/dev/null &
BRIDGE_PID=$!
sleep 4

# ── Verificar propagación vía subscriber en relay-2 ──────────────────────────
log "Verificando propagación en relay-2 (subscriber directo, timeout: ${TIMEOUT}s)..."
FIRST_BYTES=$(timeout "$TIMEOUT" docker run --rm --network "$NETWORK" \
  "$MOQ_IMAGE" --connect tcp://relay-2:4445/anon --broadcast "$BROADCAST" \
  export ts 2>/dev/null | head -c 188 | xxd | head -1 || echo "")

if echo "$FIRST_BYTES" | grep -q "^00000000: 47"; then
  log "PASS — sync byte 0x47 recibido en relay-2: $FIRST_BYTES"
  kill $PUBLISHER_PID $BRIDGE_PID 2>/dev/null
  log "========== RESULT: PASS =========="
  log "Bridge relay-1 → relay-2 verificado. Ver ADR-0002 para contexto arquitectónico."
  exit 0
else
  kill $PUBLISHER_PID $BRIDGE_PID 2>/dev/null
  die "No bytes MPEG-TS recibidos en relay-2. First bytes: $FIRST_BYTES"
fi
