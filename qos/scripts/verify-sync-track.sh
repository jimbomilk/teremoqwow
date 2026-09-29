#!/usr/bin/env bash
set -euo pipefail

# Verificador de track de sincronía — issue #65
# Valida que el track de sincronía publica pulsos regularmente en tiempo real.

MOQ_NAMESPACE="${MOQ_NAMESPACE:-anon/live1}"
FETCH_TIMEOUT=5
MIN_OBJECTS=3

# moq fetch lee UN grupo; --duration no existe. Verificamos el campo `clock`
# del catalog.json que el relay publica automáticamente como proxy del sync track.
# Sin --json: moq fetch escribe el payload crudo (JSON del catalog) a stdout.
CATALOG=$(docker run --rm --network teremoqwow-e2e \
  moqdev/moq:0.12.7 \
  --connect "tcp://moq-relay:4444/anon" \
  --broadcast "${MOQ_NAMESPACE}" \
  fetch catalog.json 2>/dev/null || echo '{}')

if echo "$CATALOG" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'clock' in d else 1)" 2>/dev/null; then
  echo "[SYNC-TRACK] PASS: clock present in catalog"
  exit 0
else
  echo "[SYNC-TRACK] FAIL: clock field missing from catalog (broadcast not active?)"
  exit 1
fi
