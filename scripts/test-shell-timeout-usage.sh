#!/bin/bash
set -u -o pipefail

# Test: EXTERNAL_TIMEOUT is actually USED in timeout commands
# (not just calculated but never passed to timeout)

echo "Testing EXTERNAL_TIMEOUT is actually used in timeout commands..."

# Read the pipeline-collector.sh script
SCRIPT="$(dirname "$0")/pipeline-collector.sh"

# Test 1: EXTERNAL_TIMEOUT is used in measure_session timeout command
if grep -q "timeout.*\$EXTERNAL_TIMEOUT" "$SCRIPT"; then
  echo "✓ Test 1: EXTERNAL_TIMEOUT used in timeout command"
else
  echo "✗ Test 1 FAILED: EXTERNAL_TIMEOUT not used in timeout"
  echo "  (mutation: hardcoding timeout value survives if not in use)"
  exit 1
fi

# Test 2: EXTERNAL_TIMEOUT calculation happens after test override
# (file order check: EXTERNAL_TIMEOUT= must come after test override block)
OVERRIDE_LINE=$(grep -n "PIPELINE_WINDOW_SECONDS" "$SCRIPT" | tail -1 | cut -d: -f1)
CALC_LINE=$(grep -n "^EXTERNAL_TIMEOUT=" "$SCRIPT" | head -1 | cut -d: -f1)

if [ "$OVERRIDE_LINE" -lt "$CALC_LINE" ]; then
  echo "✓ Test 2: EXTERNAL_TIMEOUT calculated after WINDOW override (line $CALC_LINE after override line $OVERRIDE_LINE)"
else
  echo "✗ Test 2 FAILED: EXTERNAL_TIMEOUT calculated before override"
  echo "  (mutation: moving calc before override survives if order wrong)"
  exit 1
fi

# Test 3: Numeric validation uses proper range check, not glob
if grep -q '\$PIPELINE_EXTERNAL_TIMEOUT.*-ge.*-le' "$SCRIPT"; then
  echo "✓ Test 3: Numeric validation uses -ge/-le range (not glob)"
else
  echo "✗ Test 3 FAILED: Numeric validation not using proper range check"
  echo "  (mutation: [0-9]* glob accepts junk if validation wrong)"
  exit 1
fi

# Test 4: Verify observer still gets original WINDOW (not EXTERNAL_TIMEOUT)
# grep for "--window" argument to observer - should be $WINDOW not $EXTERNAL_TIMEOUT
if grep -q -- '--window.*\$WINDOW' "$SCRIPT"; then
  echo "✓ Test 4: Observer receives original WINDOW value (not EXTERNAL_TIMEOUT)"
else
  echo "✗ Test 4 FAILED: Observer not receiving correct WINDOW"
  echo "  (mutation: passing EXTERNAL_TIMEOUT to observer survives if wrong)"
  exit 1
fi

echo "All shell timeout usage tests PASSED"
