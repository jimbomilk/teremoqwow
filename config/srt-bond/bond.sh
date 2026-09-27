#!/bin/sh
# Active-backup SRT bond relay — issue #53
# Primario (:PRIMARY_PORT) → MediaMTX live-main. Failover automático a respaldo (:BACKUP_PORT).
set -u

: "${PRIMARY_PORT:=8891}"
: "${BACKUP_PORT:=8892}"
: "${MEDIAMTX_HOST:=mediamtx}"
: "${MEDIAMTX_PORT:=8890}"
: "${MEDIAMTX_PATH:=live-main}"
: "${SRT_LATENCY_MS:=200}"
: "${RECONNECT_DELAY_S:=1}"

PRIMARY_IN="srt://:${PRIMARY_PORT}?mode=listener&latency=${SRT_LATENCY_MS}"
BACKUP_IN="srt://:${BACKUP_PORT}?mode=listener&latency=${SRT_LATENCY_MS}"
OUTPUT="srt://${MEDIAMTX_HOST}:${MEDIAMTX_PORT}?streamid=publish:${MEDIAMTX_PATH}&mode=caller&latency=${SRT_LATENCY_MS}&timeout=10000"

log() { printf '[bond][%s] %s\n' "$(date -Iseconds)" "$*"; }

relay() {
    local input="$1" label="$2"
    log "ACTIVE ${label} -> ${MEDIAMTX_HOST}:${MEDIAMTX_PORT}/${MEDIAMTX_PATH}"
    srt-live-transmit "${input}" "${OUTPUT}"
    log "${label} ended (exit=$?)"
}

log "Bond iniciado | primary=:${PRIMARY_PORT} backup=:${BACKUP_PORT} output=${OUTPUT}"

while true; do
    relay "${PRIMARY_IN}" "PRIMARY :${PRIMARY_PORT}" || true
    log "Primary link dropped. Switching to BACKUP :${BACKUP_PORT}"
    relay "${BACKUP_IN}" "BACKUP :${BACKUP_PORT}" || true
    log "Both links dropped. Returning to PRIMARY after ${RECONNECT_DELAY_S}s"
    sleep "${RECONNECT_DELAY_S}"
done
