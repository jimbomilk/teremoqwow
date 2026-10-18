#!/bin/bash

###
# TEST: Pipeline collector timeout is calculated AFTER window override
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "TEST: Pipeline collector EXTERNAL_TIMEOUT calculation order"

# Test 1: Verify FIX #3 comment is present
echo -n "Test 1: FIX #3 comment... "
if grep -q "# FIX #3: Calculate EXTERNAL_TIMEOUT AFTER test overrides" "$SCRIPT_DIR/pipeline-collector.sh"; then
  echo "✓ Present"
else
  echo "✗ FAILED"
  exit 1
fi

# Test 2: Find line numbers and verify order
echo -n "Test 2: Override before timeout calc... "
OVERRIDE_LINE=$(grep -n 'case "\${PIPELINE_WINDOW_SECONDS' "$SCRIPT_DIR/pipeline-collector.sh" | cut -d: -f1)
CALC_LINE=$(grep -n '^EXTERNAL_TIMEOUT=' "$SCRIPT_DIR/pipeline-collector.sh" | cut -d: -f1)

if [ -z "$OVERRIDE_LINE" ] || [ -z "$CALC_LINE" ]; then
  echo "✗ FAILED: Could not find lines"
  exit 1
fi

if [ "$OVERRIDE_LINE" -lt "$CALC_LINE" ]; then
  echo "✓ Override (line $OVERRIDE_LINE) before calc (line $CALC_LINE)"
else
  echo "✗ FAILED: Wrong order"
  exit 1
fi

# Test 3: Verify STARTUP_BUFFER is used
echo -n "Test 3: STARTUP_BUFFER defined... "
if grep -q "^STARTUP_BUFFER=" "$SCRIPT_DIR/pipeline-collector.sh"; then
  echo "✓ Yes"
else
  echo "✗ FAILED"
  exit 1
fi

# Test 4: Verify EXTERNAL_TIMEOUT = WINDOW + STARTUP_BUFFER
echo -n "Test 4: EXTERNAL_TIMEOUT formula... "
if grep -q 'EXTERNAL_TIMEOUT=\$((WINDOW + STARTUP_BUFFER))' "$SCRIPT_DIR/pipeline-collector.sh"; then
  echo "✓ Correct: WINDOW + STARTUP_BUFFER"
else
  echo "✗ FAILED"
  exit 1
fi

# Test 5: Numeric validation for test mode
echo -n "Test 5: Numeric validation in test mode... "
if grep -q '\[ "\$PIPELINE_EXTERNAL_TIMEOUT" -ge 5 \]' "$SCRIPT_DIR/pipeline-collector.sh"; then
  echo "✓ Validation present"
else
  echo "✗ FAILED"
  exit 1
fi

echo ""
echo "All timeout tests PASSED ✓"
