#!/usr/bin/env bash
# Pruebas de contrato del perfil MSF draft-01: cada ejemplo valid/ debe validar
# y cada invalid/ debe ser rechazado por schemas/moq/msf/v1/teremoqwow-profile.json.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
shopt -s globstar nullglob

EX=schemas/moq/msf/v1/examples
schemas=()
for f in schemas/**/*.json; do
  case "$f" in */examples/*) continue ;; esac
  schemas+=("$f")
done
ref_args=()
for f in "${schemas[@]}"; do
  [ "$f" = "schemas/moq/msf/v1/teremoqwow-profile.json" ] && continue
  ref_args+=(-r "$f")
done

run() { # $1 = instancia
  npx --yes -p ajv-cli@5 -p ajv-formats@3 -- \
    ajv validate --spec=draft2020 -c ajv-formats \
    -s schemas/moq/msf/v1/teremoqwow-profile.json "${ref_args[@]}" -d "$1" >/dev/null 2>&1
}

fail=0
for f in "$EX"/valid/*.json; do
  if run "$f"; then echo "  ok   (válido)   $f"; else echo "  FAIL (debía validar) $f"; fail=1; fi
done
for f in "$EX"/invalid/*.json; do
  if run "$f"; then echo "  FAIL (debía rechazarse) $f"; fail=1; else echo "  ok   (rechazado) $f"; fi
done
[ $fail -eq 0 ] && echo "MSF profile tests OK" || { echo "MSF profile tests FAILED"; exit 1; }
