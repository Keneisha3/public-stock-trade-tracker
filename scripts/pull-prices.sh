#!/bin/bash
# For places that cannot reach Yahoo (a cloud session): copy the charts the GitHub "prices"
# workflow mode saved on the replay-results branch into DIR, then read them offline:
#   scripts/pull-prices.sh DIR && python3 trade.py market VST --offline DIR
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:?usage: scripts/pull-prices.sh DIR}"
mkdir -p "$out"
git fetch -q origin replay-results
for f in $(git ls-tree --name-only origin/replay-results prices/); do
  git show "origin/replay-results:$f" > "$out/$(basename "$f")"
done
ls "$out"
