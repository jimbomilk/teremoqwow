#!/usr/bin/env bash
# Valida todos los esquemas JSON del repo contra JSON Schema 2020-12.
# Precarga todos los schemas como referencias para resolver $ref cruzados por $id canónico.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

shopt -s globstar nullglob
all_json=(schemas/**/*.json)
schemas=()
for f in "${all_json[@]}"; do
  # Los ficheros bajo examples/ son instancias (válidas/inválidas), no schemas.
  case "$f" in */examples/*) continue ;; esac
  schemas+=("$f")
done

if [ ${#schemas[@]} -eq 0 ]; then
  echo "No schemas found under schemas/**/*.json"
  exit 0
fi

echo "Validating ${#schemas[@]} schema file(s) with ajv-cli..."
for target in "${schemas[@]}"; do
  echo "  → $target"
  ref_args=()
  for f in "${schemas[@]}"; do
    [ "$f" = "$target" ] && continue
    ref_args+=(-r "$f")
  done
  npx --yes -p ajv-cli@5 -p ajv-formats@3 -- \
    ajv compile --spec=draft2020 -c ajv-formats -s "$target" "${ref_args[@]}" >/dev/null
done

echo "All schemas valid."
