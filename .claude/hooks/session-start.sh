#!/bin/bash
# SessionStart: get a session ready to use the trader skills. Never fails the session.
set -u
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

# pdftotext reads Congress disclosure PDFs (/trader-pelosi). Install it in cloud sessions only.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && ! command -v pdftotext >/dev/null 2>&1; then
  (apt-get install -y -qq poppler-utils >/dev/null 2>&1 || \
   (apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq poppler-utils >/dev/null 2>&1)) || true
fi

# First run: create trader/ with defaults (git-ignored, never overwrites).
if [ ! -f trader/accounts.json ]; then
  python3 .claude/skills/trader-init/init.py >/dev/null 2>&1 || true
  echo "trader/ was just created with defaults: import or sync holdings with /trader-accounts."
fi

# What the session should know.
ua="${SEC_USER_AGENT:-}"
if [ -z "$ua" ] && [ -f trader/config.json ]; then
  ua=$(python3 -c "import json;print(json.load(open('trader/config.json')).get('sec_user_agent',''))" 2>/dev/null)
fi
case "$ua" in ""|*you@example.com*) echo "SEC user agent not set: SEC filings are skipped until SEC_USER_AGENT or sec_user_agent in trader/config.json is set.";; esac
command -v pdftotext >/dev/null 2>&1 || echo "pdftotext missing: /trader-pelosi can list filings but not read the PDFs."
if [ -f trader/accounts/questrade.json ]; then
  n=$(python3 -c "import json;print(len(json.load(open('trader/accounts/questrade.json')).get('positions',[])))" 2>/dev/null)
  echo "Questrade holdings on file: ${n:-0} positions."
fi
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  echo "Cloud session: trader/ starts empty here and is not saved. Daily use belongs on your own computer."
fi
exit 0
