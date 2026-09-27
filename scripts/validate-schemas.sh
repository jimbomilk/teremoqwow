#!/usr/bin/env bash
# Valida todos los esquemas JSON del repo contra JSON Schema 2020-12.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

shopt -s globstar nullglob
schemas=(schemas/**/*.json)

if [ ${#schemas[@]} -eq 0 ]; then
  echo "No schemas found under schemas/**/*.json"
  exit 0
fi

echo "Validating ${#schemas[@]} schema file(s) with ajv-cli..."
for f in "${schemas[@]}"; do
  echo "  → $f"
  npx --yes ajv-cli@5 compile --spec=draft2020 -s "$f" >/dev/null
done

echo "All schemas valid."
