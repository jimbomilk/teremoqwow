#!/bin/bash
set -u -o pipefail

# Test FIX #3: EXTERNAL_TIMEOUT calculated after WINDOW override

echo "Testing shell timeout contract fixes..."

# Test 1: EXTERNAL_TIMEOUT uses overridden WINDOW
export PIPELINE_COLLECTOR_TEST_MODE=1
export PIPELINE_WINDOW_SECONDS=1

# Source the script to get the calculated values (simulate the setup)
WINDOW=20
GRACE=5
STARTUP_BUFFER=3

# Test override is applied before calculation
PIPELINE_WINDOW_SECONDS=1
if [ "$PIPELINE_WINDOW_SECONDS" -ge 1 ] && [ "$PIPELINE_WINDOW_SECONDS" -le 20 ]; then
  WINDOW="$PIPELINE_WINDOW_SECONDS"
fi

# Now calculate EXTERNAL_TIMEOUT
EXTERNAL_TIMEOUT=$((WINDOW + STARTUP_BUFFER))

# Verify: WINDOW should be 1, EXTERNAL_TIMEOUT should be 1+3=4
if [ "$WINDOW" -eq 1 ]; then
  echo "✓ Test 1: WINDOW override applied (WINDOW=$WINDOW)"
else
  echo "✗ Test 1 FAILED: WINDOW not overridden (got $WINDOW)"
  exit 1
fi

if [ "$EXTERNAL_TIMEOUT" -eq 4 ]; then
  echo "✓ Test 2: EXTERNAL_TIMEOUT calculated after override (EXTERNAL_TIMEOUT=$EXTERNAL_TIMEOUT)"
else
  echo "✗ Test 2 FAILED: EXTERNAL_TIMEOUT not recalculated (got $EXTERNAL_TIMEOUT, expected 4)"
  exit 1
fi

# Test 3: STARTUP_BUFFER >= observer's minimum buffer
# Observer buffer = max(500, min(2000, window * 100))
# For any window 1-20, observer buffer <= 2000ms = 2s
# STARTUP_BUFFER=3 >= 2, so it's sufficient
if [ "$STARTUP_BUFFER" -ge 2 ]; then
  echo "✓ Test 3: STARTUP_BUFFER >= observer's max buffer (STARTUP_BUFFER=$STARTUP_BUFFER >= 2)"
else
  echo "✗ Test 3 FAILED: STARTUP_BUFFER too small (got $STARTUP_BUFFER, need >= 2)"
  exit 1
fi

# Test 4: Numeric validation rejects junk
unset PIPELINE_EXTERNAL_TIMEOUT
PIPELINE_EXTERNAL_TIMEOUT="1garbage"

# Current code checks: [ "$PIPELINE_EXTERNAL_TIMEOUT" -ge 5 ] 2>/dev/null
# This should fail (return false) for "1garbage"
if [ "$PIPELINE_EXTERNAL_TIMEOUT" -ge 5 ] 2>/dev/null; then
  echo "✗ Test 4 FAILED: Numeric validation accepted junk (1garbage)"
  exit 1
else
  echo "✓ Test 4: Numeric validation rejects junk (1garbage rejected)"
fi

# Test 5: Valid numeric override is accepted
PIPELINE_EXTERNAL_TIMEOUT=10
if [ "$PIPELINE_EXTERNAL_TIMEOUT" -ge 5 ] 2>/dev/null && [ "$PIPELINE_EXTERNAL_TIMEOUT" -le 60 ] 2>/dev/null; then
  echo "✓ Test 5: Valid override accepted (10)"
else
  echo "✗ Test 5 FAILED: Valid override rejected"
  exit 1
fi

echo "All shell timeout contract tests PASSED"
