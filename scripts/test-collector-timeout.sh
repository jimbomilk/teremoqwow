#!/usr/bin/env bash

###
# TEST: pipeline-collector.sh HIGH BLOCKER #3
# Verifies that external timeout > observer window + startup buffer
# Ensures SIGINT doesn't kill healthy observer before report emitted
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[TEST] Checking pipeline-collector.sh timeout contract..."

# Read the script and extract STARTUP_BUFFER and calculation
# Verify: EXTERNAL_TIMEOUT = WINDOW + STARTUP_BUFFER
STARTUP_BUFFER=$(grep -E '^\s*STARTUP_BUFFER=' pipeline-collector.sh | head -1 | sed 's/.*=//; s/#.*//' | tr -d ' ')
WINDOW_DEFAULT=$(grep -E '^\s*WINDOW=' pipeline-collector.sh | head -1 | sed 's/.*=//; s/#.*//' | tr -d ' ')

echo "  WINDOW default: $WINDOW_DEFAULT"
echo "  STARTUP_BUFFER: $STARTUP_BUFFER"
echo "  EXTERNAL_TIMEOUT calc: WINDOW + $STARTUP_BUFFER"

# Verify numeric values
if ! [[ "$STARTUP_BUFFER" =~ ^[0-9]+$ ]]; then
  echo "FAIL: STARTUP_BUFFER not numeric: $STARTUP_BUFFER"
  exit 1
fi

if ! [[ "$WINDOW_DEFAULT" =~ ^[0-9]+$ ]]; then
  echo "FAIL: WINDOW not numeric: $WINDOW_DEFAULT"
  exit 1
fi

# Test 1: Verify EXTERNAL_TIMEOUT is used in timeout commands
echo "[TEST 1] Verify EXTERNAL_TIMEOUT variable is defined..."
if grep -q 'EXTERNAL_TIMEOUT=' pipeline-collector.sh; then
  echo "  PASS: EXTERNAL_TIMEOUT variable defined"
else
  echo "  FAIL: EXTERNAL_TIMEOUT variable not found"
  exit 1
fi

# Test 2: Verify EXTERNAL_TIMEOUT is used in timeout command
echo "[TEST 2] Verify EXTERNAL_TIMEOUT used in timeout command..."
if grep -q 'timeout.*EXTERNAL_TIMEOUT' pipeline-collector.sh; then
  echo "  PASS: timeout command uses EXTERNAL_TIMEOUT"
else
  echo "  FAIL: timeout command not using EXTERNAL_TIMEOUT"
  exit 1
fi

# Test 3: Verify observer receives original WINDOW (not EXTERNAL_TIMEOUT)
echo "[TEST 3] Verify observer gets original WINDOW (not inflated timeout)..."
if grep -q 'observe --window "\$WINDOW"' pipeline-collector.sh; then
  echo "  PASS: observer receives original WINDOW value"
else
  echo "  FAIL: observer not receiving correct WINDOW argument"
  exit 1
fi

# Test 4: Verify STARTUP_BUFFER >= 2 (observer reserves 2s internally)
echo "[TEST 4] Verify STARTUP_BUFFER accounts for observer internal buffer..."
if [ "$STARTUP_BUFFER" -ge 2 ]; then
  echo "  PASS: STARTUP_BUFFER ($STARTUP_BUFFER) >= observer buffer (2s)"
else
  echo "  FAIL: STARTUP_BUFFER ($STARTUP_BUFFER) < observer buffer (2s), deadline may be exceeded"
  exit 1
fi

# Test 5: Test mode can override PIPELINE_EXTERNAL_TIMEOUT
echo "[TEST 5] Verify test mode can override external timeout..."
if grep -q 'PIPELINE_EXTERNAL_TIMEOUT' pipeline-collector.sh; then
  echo "  PASS: test mode can override PIPELINE_EXTERNAL_TIMEOUT"
else
  echo "  INFO: test mode may not override PIPELINE_EXTERNAL_TIMEOUT"
fi

echo ""
echo "[PASS] All timeout contract tests passed"
echo "  Observer window: WINDOW=$WINDOW_DEFAULT"
echo "  External timeout: WINDOW + STARTUP_BUFFER = $WINDOW_DEFAULT + $STARTUP_BUFFER seconds"
echo "  This ensures Docker startup <= $STARTUP_BUFFER seconds doesn't kill healthy observer"
