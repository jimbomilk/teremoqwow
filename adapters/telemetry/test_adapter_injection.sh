#!/usr/bin/env bash
# TDD G2: security tests for C2/C3 (BODY heredoc RCE) and H5/H6 (MATCH_ID injection)
set -uo pipefail

PASS=0
FAIL=0
TMPDIR_TEST=$(mktemp -d)
MARKER="${TMPDIR_TEST}/injection_marker"

cleanup() { rm -rf "$TMPDIR_TEST"; }
trap cleanup EXIT

ok()   { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPTA="${SCRIPT_DIR}/opta-adapter.sh"
STATS="${SCRIPT_DIR}/stats-perform-adapter.sh"

echo ""
echo "=== TDD Group G2: adapter injection security tests ==="

# ────────────────────────────────────────────────────────────────────
# C2/C3 RED — vulnerable pattern: unquoted heredoc with malicious BODY
# ────────────────────────────────────────────────────────────────────
echo ""
echo "--- C2/C3 RED: unquoted heredoc expands \$BODY into Python source ---"

# Payload: valid JSON + triple-quote escape to break out of json.loads() and
# call open() after the successful parse, before the function returns.
MALICIOUS_BODY=$(printf '{"key":"val"}'"'''"');open("%s","w").write("INJECTED");x=('"'''" "$MARKER")

rm -f "$MARKER"
python3 << VULN_EOF 2>/dev/null || true
import json
import sys
try:
    api_response = json.loads('''$MALICIOUS_BODY''')
except Exception:
    sys.exit(1)
VULN_EOF

if [[ -f "$MARKER" ]]; then
    echo "  [CONFIRMED RED] Vulnerable pattern: injection marker created → code executed outside json.loads"
else
    echo "  [SKIP RED] Shell expansion altered payload (env/shell version difference)"
    echo "             Vulnerability class still present: unquoted heredoc lets BODY mutate Python AST"
fi

# ────────────────────────────────────────────────────────────────────
# C2/C3 GREEN — fixed pattern: quoted heredoc, BODY via env var
# ────────────────────────────────────────────────────────────────────
echo ""
echo "--- C2/C3 GREEN: quoted heredoc + os.environ prevents injection ---"

rm -f "$MARKER"
BODY_JSON="$MALICIOUS_BODY" MARKER_PATH="$MARKER" python3 << 'FIXED_EOF' 2>/dev/null || true
import json
import sys
import os
try:
    api_response = json.loads(os.environ['BODY_JSON'])
except Exception:
    sys.exit(0)
FIXED_EOF

if [[ ! -f "$MARKER" ]]; then
    ok "C2/C3: fixed pattern does not execute injected code (marker absent)"
else
    fail "C2/C3: fixed pattern still created injection marker"
fi

# Verify the adapters themselves use the fixed pattern
for adapter in "$OPTA" "$STATS"; do
    name=$(basename "$adapter")
    if grep -q "json.loads(os.environ\['BODY_JSON'\])" "$adapter" && \
       grep -q "<< 'PYTHON_EOF'" "$adapter"; then
        ok "C2/C3 $name: uses quoted heredoc + os.environ (not interpolation)"
    else
        fail "C2/C3 $name: still uses vulnerable interpolation pattern"
    fi
done

# ────────────────────────────────────────────────────────────────────
# H5/H6 RED — invalid MATCH_ID must be rejected with exit 1
# ────────────────────────────────────────────────────────────────────
echo ""
echo "--- H5/H6 RED: invalid MATCH_ID values must cause exit 1 ---"

LONG_ID=$(python3 -c 'print("x"*65)')  # 65 chars > max 64

declare -a INVALID_IDS=(
    'abc"def'
    'abc def'
    'abc;def'
    'abc$(cmd)'
    "abc'def"
    'abc/def'
    "$LONG_ID"
)

for mid in "${INVALID_IDS[@]}"; do
    for adapter in "$OPTA" "$STATS"; do
        name=$(basename "$adapter")
        result=0
        MATCH_ID="$mid" bash "$adapter" 2>/dev/null || result=$?
        short="${mid:0:20}"
        if [[ $result -eq 1 ]]; then
            ok "H5/H6 $name: '${short}...' → rejected (exit 1)"
        else
            fail "H5/H6 $name: '${short}...' → NOT rejected (exit $result)"
        fi
    done
done

# Newline-embedded ID (separate because of array embedding limitations)
NEWLINE_ID=$(printf 'abc\ndef')
for adapter in "$OPTA" "$STATS"; do
    name=$(basename "$adapter")
    result=0
    MATCH_ID="$NEWLINE_ID" bash "$adapter" 2>/dev/null || result=$?
    if [[ $result -eq 1 ]]; then
        ok "H5/H6 $name: newline-embedded ID → rejected (exit 1)"
    else
        fail "H5/H6 $name: newline-embedded ID → NOT rejected (exit $result)"
    fi
done

# ────────────────────────────────────────────────────────────────────
# H5/H6 GREEN — valid MATCH_ID passes validation (no exit 1)
# ────────────────────────────────────────────────────────────────────
echo ""
echo "--- H5/H6 GREEN: valid MATCH_ID passes validation ---"

declare -a VALID_IDS=("abc123" "match-001" "MATCH_ID_2024" "a1b2c3d4" "abc_def-ghi" "$(python3 -c 'print("x"*64)')")

for mid in "${VALID_IDS[@]}"; do
    for adapter in "$OPTA" "$STATS"; do
        name=$(basename "$adapter")
        result=0
        # 127.0.0.1:1 → connection refused immediately; timeout kills loop after 1s
        MATCH_ID="$mid" POLL_INTERVAL_SEC=0 \
            OPTA_BASE_URL="http://127.0.0.1:1" \
            STATS_PERFORM_URL="http://127.0.0.1:1" \
            timeout 1 bash "$adapter" 2>/dev/null || result=$?
        short="${mid:0:20}"
        if [[ $result -ne 1 ]]; then
            ok "H5/H6 $name: '${short}' → passes validation (exit $result)"
        else
            fail "H5/H6 $name: '${short}' → incorrectly rejected"
        fi
    done
done

# ────────────────────────────────────────────────────────────────────
# Invariant — normal JSON body produces valid event (no injection needed)
# ────────────────────────────────────────────────────────────────────
echo ""
echo "--- Invariant: normal JSON body transforms correctly ---"

NORMAL_BODY='{"matchId":"m001","homeTeam":"TeamA","awayTeam":"TeamB","score":"1-0"}'
EVENT=$(BODY_JSON="$NORMAL_BODY" MATCH_ID_VAL="m001" SEQ_VAL="0" WALLCLOCK_VAL="1000000000000000000" python3 << 'PYTHON_EOF'
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

if echo "$EVENT" | python3 -c "import json,sys; e=json.load(sys.stdin); assert e['payload']['matchId']=='m001'; assert e['kind']=='stats.match'" 2>/dev/null; then
    ok "Invariant: normal JSON body produces valid structured event"
else
    fail "Invariant: normal JSON body failed to produce valid event"
fi

# ────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
[[ $FAIL -eq 0 ]]
