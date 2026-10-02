#!/usr/bin/env bash
set -euo pipefail

# Opta Stats Perform Telemetry Adapter
# Polls matchstats endpoint and publishes events to MOQ relay

# Configuration variables
OPTA_BASE_URL="${OPTA_BASE_URL:-https://api.performfeeds.com/soccerdata}"
OPTA_OUTLET_KEY="${OPTA_OUTLET_KEY:-REPLACE_ME}"
OPTA_AUTH_KEY="${OPTA_AUTH_KEY:-REPLACE_ME}"
MATCH_ID="${MATCH_ID:-}"
MOQ_RELAY_TCP="${MOQ_RELAY_TCP:-tcp://127.0.0.1:4444/anon}"
BROADCAST="${BROADCAST:-anon/live1}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-5}"
VIDEO_TIMESCALE="${VIDEO_TIMESCALE:-90000}"

# Validate MATCH_ID
if [[ -z "$MATCH_ID" ]]; then
    echo "[ADAPTER] ERROR: MATCH_ID is required" >&2
    exit 1
fi
if [[ ! "$MATCH_ID" =~ ^[a-zA-Z0-9_-]{1,64}$ ]]; then
    echo "[ADAPTER] ERROR: MATCH_ID contains invalid characters (allowed: [a-zA-Z0-9_-], max 64 chars)" >&2
    exit 1
fi

# State
SEQ=0

# Cleanup on exit
cleanup() {
    echo "[ADAPTER] INFO: shutting down gracefully" >&2
    exit 0
}

trap cleanup SIGINT SIGTERM

# Main loop
while true; do
    # Fetch matchstats from Opta API
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -u "${OPTA_OUTLET_KEY}:${OPTA_AUTH_KEY}" \
        "${OPTA_BASE_URL}/matchstats/${MATCH_ID}?_rt=b&_lcl=en&_fmt=json" 2>/dev/null || echo "")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    if [[ "$HTTP_CODE" != "200" ]]; then
        echo "[ADAPTER] WARN: HTTP $HTTP_CODE from Opta API, retrying..." >&2
        sleep "$POLL_INTERVAL_SEC"
        continue
    fi
    
    if [[ -z "$BODY" ]]; then
        echo "[ADAPTER] WARN: empty response body, retrying..." >&2
        sleep "$POLL_INTERVAL_SEC"
        continue
    fi
    
    # Generate canonical telemetry event
    WALLCLOCK_NS=$(($(date +%s%N)))
    EVENT_JSON=$(BODY_JSON="$BODY" MATCH_ID_VAL="$MATCH_ID" SEQ_VAL="$SEQ" WALLCLOCK_VAL="$WALLCLOCK_NS" python3 << 'PYTHON_EOF'
import json
import uuid
import sys
import os

try:
    api_response = json.loads(os.environ['BODY_JSON'])
except Exception:
    sys.exit(1)

event = {
    "id": str(uuid.uuid4()),
    "timestamp": {
        "wallclock_ns": int(os.environ['WALLCLOCK_VAL']),
        "source": "app"
    },
    "kind": "stats.match",
    "source": "opta",
    "producer_id": os.environ['MATCH_ID_VAL'],
    "sequence": int(os.environ['SEQ_VAL']),
    "payload": {
        "matchId": api_response.get("matchId"),
        "homeTeam": api_response.get("homeTeam"),
        "awayTeam": api_response.get("awayTeam"),
        "score": api_response.get("score")
    }
}

print(json.dumps(event))
PYTHON_EOF
)
    
    if [[ -z "$EVENT_JSON" ]]; then
        echo "[ADAPTER] WARN: failed to transform event, skipping..." >&2
        sleep "$POLL_INTERVAL_SEC"
        continue
    fi
    
    # Publish with backpressure handling
    START_TIME=$(date +%s%N)
    
    PUBLISH_OUTPUT=$(echo "$EVENT_JSON" | timeout 2 docker run --rm -i \
        --network teremoqwow-e2e \
        moqdev/moq:latest \
        --connect "${MOQ_RELAY_TCP}" \
        --broadcast "${BROADCAST}" \
        publish telemetry 2>&1) || PUBLISH_STATUS=$?
    
    END_TIME=$(date +%s%N)
    ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
    
    if [[ ${PUBLISH_STATUS:-0} -eq 124 ]]; then
        # Timeout (>2s)
        echo "[ADAPTER] WARN: backpressure — skipping frame" >&2
    elif [[ ${PUBLISH_STATUS:-0} -ne 0 ]]; then
        echo "[ADAPTER] WARN: publish failed (exit code $PUBLISH_STATUS), retrying..." >&2
    else
        echo "[ADAPTER] OK: published event seq=$SEQ kind=stats.match" >&2
        ((SEQ++))
    fi
    
    sleep "$POLL_INTERVAL_SEC"
done
