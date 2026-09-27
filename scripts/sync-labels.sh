#!/usr/bin/env bash
# Sincroniza las labels del repo con .github/labels.yml (crea o actualiza; no borra).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OWNER="${OWNER:-jimbomilk}"
REPO="${REPO:-teremoqwow}"
FILE=".github/labels.yml"

command -v gh >/dev/null || { echo "gh CLI required"; exit 1; }
command -v yq >/dev/null || { echo "yq (mikefarah) required"; exit 1; }

count="$(yq '.labels | length' "$FILE")"
for i in $(seq 0 $((count - 1))); do
  name="$(yq -r ".labels[$i].name" "$FILE")"
  color="$(yq -r ".labels[$i].color" "$FILE")"
  desc="$(yq -r ".labels[$i].description // \"\"" "$FILE")"

  if gh label list --repo "$OWNER/$REPO" --search "$name" --json name --jq '.[].name' | grep -Fxq "$name"; then
    echo "→ Updating label '$name'"
    gh label edit "$name" --repo "$OWNER/$REPO" --color "$color" --description "$desc" >/dev/null
  else
    echo "→ Creating label '$name'"
    gh label create "$name" --repo "$OWNER/$REPO" --color "$color" --description "$desc" >/dev/null
  fi
done

echo "Done."
