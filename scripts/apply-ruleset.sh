#!/usr/bin/env bash
# Aplica los rulesets declarados en .github/rulesets/*.json de forma idempotente.
# Uso:
#   ./scripts/apply-ruleset.sh                  # aplica todos
#   ./scripts/apply-ruleset.sh main-protection  # aplica sólo uno
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OWNER="${OWNER:-jimbomilk}"
REPO="${REPO:-teremoqwow}"
RULESETS_DIR=".github/rulesets"

command -v gh >/dev/null || { echo "gh CLI required"; exit 1; }
command -v jq >/dev/null || { echo "jq required"; exit 1; }

targets=()
if [ $# -gt 0 ]; then
  for name in "$@"; do targets+=("$RULESETS_DIR/$name.json"); done
else
  shopt -s nullglob
  targets=("$RULESETS_DIR"/*.json)
fi

if [ ${#targets[@]} -eq 0 ]; then
  echo "No rulesets found in $RULESETS_DIR"
  exit 0
fi

existing_json="$(gh api "/repos/$OWNER/$REPO/rulesets")"

for file in "${targets[@]}"; do
  [ -f "$file" ] || { echo "  ! missing: $file"; continue; }
  name="$(jq -r '.name' "$file")"
  id="$(echo "$existing_json" | jq -r --arg n "$name" '.[] | select(.name==$n) | .id' | head -n1)"

  if [ -n "$id" ] && [ "$id" != "null" ]; then
    echo "→ Updating ruleset '$name' (id=$id)"
    gh api --method PUT "/repos/$OWNER/$REPO/rulesets/$id" --input "$file" >/dev/null
  else
    echo "→ Creating ruleset '$name'"
    gh api --method POST "/repos/$OWNER/$REPO/rulesets" --input "$file" >/dev/null
  fi
done

echo "Done."
