#!/usr/bin/env bash
set -euo pipefail

# Verificador de track de sincronía — issue #65
# Valida que el track de sincronía publica pulsos regularmente en tiempo real.

MOQ_NAMESPACE="${MOQ_NAMESPACE:-anon/live1}"
FETCH_TIMEOUT=5
MIN_OBJECTS=3

# Fetch del track sync durante FETCH_TIMEOUT segundos
OUTPUT=$(docker run --rm --network teremoqwow-e2e moqdev/moq:latest fetch "${MOQ_NAMESPACE}/sync" --duration "${FETCH_TIMEOUT}s" 2>&1 || true)

# Contar objetos recibidos (líneas con "object" o "group")
OBJECT_COUNT=$(echo "$OUTPUT" | grep -c "object\|group" || echo 0)

if [[ $OBJECT_COUNT -ge $MIN_OBJECTS ]]; then
  echo "[SYNC-TRACK] PASS"
  exit 0
else
  echo "[SYNC-TRACK] FAIL: received $OBJECT_COUNT objects, expected at least $MIN_OBJECTS"
  exit 1
fi
