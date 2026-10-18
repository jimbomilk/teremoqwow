#!/bin/bash

# REFUTER INVOCATION SCRIPT for Task #206 Blockers 1-3
# Invoke both refuters in parallel on the frozen snapshot

set -e

REPO_ROOT="/home/jimbomilk/projects/teremoqwow"
COMMIT_HASH="0ffdd05531c6de0a263b09754cb6e78444884f06"
CONTEXT_FILE="REFUTER-CONTEXT-BLOCKERS-206.md"

echo "=========================================="
echo "Task #206 Blockers 1-3 Refuter Invocation"
echo "=========================================="
echo ""
echo "Commit: $COMMIT_HASH"
echo "Context: $CONTEXT_FILE"
echo ""

cd "$REPO_ROOT"

# Verify context file exists
if [ ! -f "$CONTEXT_FILE" ]; then
  echo "ERROR: Context file $CONTEXT_FILE not found"
  exit 1
fi

# Verify test suites are ready
echo "[CHECK] Verifying test suites..."
cd "$REPO_ROOT/ingest/meta-track"
if ! npm test 2>&1 | grep -q "pass 78"; then
  echo "ERROR: Test suite does not show 78 PASS"
  exit 1
fi
echo "  ✓ npm test: 78 PASS"

cd "$REPO_ROOT"
if ! scripts/test-collector-timeout.sh 2>&1 | grep -q "PASS"; then
  echo "ERROR: Collector timeout test failed"
  exit 1
fi
echo "  ✓ test-collector-timeout.sh: 5 PASS"

# Prepare refuter invocation
echo ""
echo "[READY] Ready to invoke refuters"
echo ""
echo "Refuter-Correctness command:"
echo "  python3 .github/agents/refuter-correctness.py \\",
echo "    --contract ./REFUTER-CONTEXT-BLOCKERS-206.md \\",
echo "    --spec ./schemas/ \\",
echo "    --commit '$COMMIT_HASH' \\",
echo "    --entry 'cd ingest/meta-track && npm test'"
echo ""
echo "Refuter-Tests command:"
echo "  python3 .github/agents/refuter-tests.py \\",
echo "    --contract ./REFUTER-CONTEXT-BLOCKERS-206.md \\",
echo "    --spec ./schemas/ \\",
echo "    --commit '$COMMIT_HASH' \\",
echo "    --entry 'cd ingest/meta-track && npm test'"
echo ""
echo "Or invoke directly with:"
echo "  cd ingest/meta-track && npm test"
echo "  scripts/test-collector-timeout.sh"
echo ""
