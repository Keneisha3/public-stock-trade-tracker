#!/bin/bash
# Pull the latest upstream Trader skill pack (Jakeschincariol/trader-skill) into .claude/skills/.
# Only the 11 upstream folders and their tests are replaced; this project's own skills
# (trader-accounts, trader-paper, trader-daily, trader-init) and tests/_load.py are left alone.
# Review the diff (git diff) and run the tests before committing.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone -q --depth 1 https://github.com/Jakeschincariol/trader-skill "$tmp/up"
rev=$(git -C "$tmp/up" rev-parse --short HEAD)
for d in "$tmp"/up/trader-*/; do
  name=$(basename "$d")
  rm -rf ".claude/skills/$name"
  cp -r "$d" ".claude/skills/$name"
done
cp "$tmp/up/LICENSE" .claude/skills/LICENSE-trader-skill
for t in "$tmp"/up/tests/test_*.py; do
  [ "$(basename "$t")" = "test_repo.py" ] && continue   # ours checks this repo's layout
  cp "$t" tests/
done
rm -rf tests/fixtures/trader-*/ 2>/dev/null || true
cp -r "$tmp"/up/tests/fixtures/trader-* tests/fixtures/
echo "updated to upstream $rev. Now: git diff --stat && python3 -m unittest discover -s tests"
