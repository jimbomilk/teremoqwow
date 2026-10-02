#!/usr/bin/env bash
# check-remote-client.sh — preflight del nodo remoto para tests E2E
# USO: bash qos/scripts/check-remote-client.sh [remote_host]
# ARGS: remote_host (default: laptop-077c92vt.tailbd33d7.ts.net)
#
# Exit codes: 0=OK  1=crítico  2=opcional fallido (cert pronto, sin muestras)

set -euo pipefail

PLAYER_HOST="${PLAYER_HOST:-laptop-077c92vt.tailbd33d7.ts.net}"
PLAYER_PORT="${PLAYER_PORT:-5443}"
REMOTE_IP="${REMOTE_IP:-100.83.19.119}"
RELAY_CERT="config/relay/certs/relay.pem"
PLAYER_CERT="config/relay/certs/player.pem"
CERT_WARN_DAYS=3

PASS="[PASS]"
WARN="[WARN]"
FAIL="[FAIL]"

critical=0
optional=0

# ── 1. Tailscale ─────────────────────────────────────────────────────────────
echo "--- Check 1: Tailscale node ${REMOTE_IP} (chema-pc) ---"
if command -v tailscale &>/dev/null; then
  if tailscale status 2>/dev/null | grep -qF "${REMOTE_IP}"; then
    echo "${PASS} chema-pc (${REMOTE_IP}) is online in Tailscale"
  else
    echo "${WARN} chema-pc (${REMOTE_IP}) NOT found in tailscale status (may be offline)"
    optional=1
  fi
else
  echo "${WARN} tailscale not installed — skipping Tailscale check"
fi

# ── 2. Player HTTPS accesible ────────────────────────────────────────────────
echo ""
echo "--- Check 2: Player HTTPS ${PLAYER_HOST}:${PLAYER_PORT} ---"
if curl -sk --max-time 5 "https://${PLAYER_HOST}:${PLAYER_PORT}/" -o /dev/null; then
  echo "${PASS} Player HTTPS reachable at https://${PLAYER_HOST}:${PLAYER_PORT}/"
else
  echo "${FAIL} Player HTTPS NOT reachable at https://${PLAYER_HOST}:${PLAYER_PORT}/"
  critical=1
fi

# ── 3. Relay cert hash publicado ─────────────────────────────────────────────
echo ""
echo "--- Check 3: Relay cert hash (localhost:8090) ---"
CERT_HASH_URL="http://localhost:8090/certificate.sha256"
if curl -s --max-time 5 "${CERT_HASH_URL}" -o /dev/null; then
  HASH=$(curl -s --max-time 5 "${CERT_HASH_URL}")
  if [[ -n "${HASH}" ]]; then
    echo "${PASS} Relay cert hash available: ${HASH:0:16}..."
  else
    echo "${WARN} Relay cert hash endpoint returned empty body"
    optional=1
  fi
else
  echo "${WARN} Relay cert hash endpoint not reachable (relay may not be running)"
  optional=1
fi

# ── 4. Caducidad de certificados ─────────────────────────────────────────────
echo ""
echo "--- Check 4: Certificate expiry ---"
check_cert_expiry() {
  local certfile="$1"
  local label="$2"
  if [[ ! -f "${certfile}" ]]; then
    echo "${WARN} ${label}: file not found (${certfile}) — skipping"
    return
  fi
  local enddate
  enddate=$(openssl x509 -enddate -noout -in "${certfile}" 2>/dev/null | cut -d= -f2)
  if [[ -z "${enddate}" ]]; then
    echo "${WARN} ${label}: could not parse cert expiry"
    return
  fi
  local expiry_epoch now_epoch days_left
  expiry_epoch=$(date -d "${enddate}" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "${enddate}" +%s 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
  if (( days_left <= CERT_WARN_DAYS )); then
    echo "${WARN} ${label}: expires in ${days_left} day(s) (${enddate}) — renew soon!"
    optional=1
  else
    echo "${PASS} ${label}: valid for ${days_left} more days (${enddate})"
  fi
}

check_cert_expiry "${RELAY_CERT}" "relay.pem"
check_cert_expiry "${PLAYER_CERT}" "player.pem"

# ── 5. /metrics/latency ──────────────────────────────────────────────────────
echo ""
echo "--- Check 5: /metrics/latency endpoint ---"
METRICS_URL="https://${PLAYER_HOST}:${PLAYER_PORT}/metrics/latency"
METRICS_JSON=$(curl -sk --max-time 5 "${METRICS_URL}" 2>/dev/null || true)
if [[ -z "${METRICS_JSON}" ]]; then
  echo "${WARN} /metrics/latency not reachable (player may not be running or no Vite dev server)"
  optional=1
else
  SAMPLES=$(echo "${METRICS_JSON}" | grep -o '"samples":[0-9]*' | grep -o '[0-9]*' || echo "0")
  P95=$(echo "${METRICS_JSON}" | grep -o '"p95_ms":[0-9]*' | grep -o '[0-9]*' || echo "0")

  if [[ "${SAMPLES}" == "0" || "${SAMPLES}" == "null" || -z "${SAMPLES}" ]]; then
    echo "${WARN} /metrics/latency: samples=0 — player connecting or no stream yet"
    optional=1
  elif (( P95 >= 700 )); then
    echo "${FAIL} /metrics/latency: p95_ms=${P95} >= 700ms — latency too high!"
    critical=1
  else
    echo "${PASS} /metrics/latency: samples=${SAMPLES}, p95_ms=${P95}ms (< 700ms threshold)"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
if (( critical > 0 )); then
  echo "RESULT: FAIL — critical check(s) failed"
  exit 1
elif (( optional > 0 )); then
  echo "RESULT: WARN — optional check(s) failed (cert expiry / no samples)"
  exit 2
else
  echo "RESULT: PASS — all checks OK"
  exit 0
fi
