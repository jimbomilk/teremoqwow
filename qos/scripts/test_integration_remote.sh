#!/usr/bin/env bash
# test_integration_remote.sh — análisis estático de los nuevos checks remotos
# en integration-test.sh (CHECK 0 preflight + CHECK 5 latencia remota).
#
# USO: bash qos/scripts/test_integration_remote.sh
# EXIT: 0=todos PASS, 1=algún FAIL

set -uo pipefail

SCRIPT="qos/scripts/integration-test.sh"
PASS=0
FAIL=0

check() {
  local desc="$1"
  shift
  if "$@" 2>/dev/null; then
    echo "PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $desc"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== RED→GREEN: integration-test.sh remote checks ==="
echo ""

check "CHECK 0 presente en el script"          grep -q "CHECK 0"              "$SCRIPT"
check "SKIP_REMOTE_CHECK declarado"            grep -q "SKIP_REMOTE_CHECK"    "$SCRIPT"
check "CHECK 5 presente en el script"          grep -q "CHECK 5"              "$SCRIPT"
check "SKIP_REMOTE_LATENCY declarado"          grep -q "SKIP_REMOTE_LATENCY"  "$SCRIPT"
check "PLAYER_HOST declarado"                  grep -q "PLAYER_HOST"          "$SCRIPT"
check "endpoint /metrics/latency referenciado" grep -q "metrics/latency"      "$SCRIPT"
check "check-remote-client.sh invocado"        grep -q "check-remote-client"  "$SCRIPT"
check "TOTAL_CHECKS dinámico en resumen"       grep -q "TOTAL_CHECKS"         "$SCRIPT"
check "sintaxis bash válida"                   bash -n                        "$SCRIPT"

echo ""
TOTAL=$((PASS + FAIL))
echo "PASS: ${PASS}/${TOTAL}   FAIL: ${FAIL}/${TOTAL}"
echo ""
[[ $FAIL -eq 0 ]] && echo "RESULT: GREEN" || echo "RESULT: RED"
[[ $FAIL -eq 0 ]]
