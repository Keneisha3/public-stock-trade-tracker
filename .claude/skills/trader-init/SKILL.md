---
name: trader-init
description: >-
  First-run setup. Creates the trader/ folder every other skill reads: risk
  limits (paper trading, no options, margin or shorts), your accounts with
  their strategies (Questrade aggressive growth, Wealthsimple steady
  dividend, optional medium term), the target mix between them, starter
  watchlists to score, and the paper bot's universe. Never overwrites what
  exists unless asked. Use when the user says "set me up", "get started",
  "first time", "init", "configure my accounts", "change my target mix", or
  when another skill reports that trader/accounts.json is missing.
argument-hint: "[--with-medium] [--mix growth=60,dividend=40] [--demo]"
---

# trader-init

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/init.py"
python3 "${CLAUDE_SKILL_DIR}/init.py" --with-medium --mix growth=50,medium=20,dividend=30
python3 "${CLAUDE_SKILL_DIR}/init.py" --questrade-type RRSP --wealthsimple-type TFSA
python3 "${CLAUDE_SKILL_DIR}/init.py" --demo      # sample holdings to try the dashboard
```

## Ask before running (keep it to one short message)

1. Account types: is Questrade a TFSA, RRSP, FHSA or a non-registered
   (cash/margin) account? Same for Wealthsimple. It matters: US dividends
   lose 15 % in a TFSA but not in an RRSP.
2. The target mix: how much should sit in growth vs dividend (and medium
   term, if they want that sleeve)? Default 60/40, or 45/20/35 with medium.
3. Their SEC user agent ("Name email") for SEC filings, or skip.

Then run `init.py` with the answers, show what was written, and point to the
next step: get the holdings in (`/trader-accounts`: Questrade sync or a
Wealthsimple CSV), then run `/trader-daily` or open the dashboard.

To change the mix or rules later, edit `trader/accounts.json` directly (it
has a `_help` line), or re-run with `--force` to start over.

## What it never does

It never asks for or stores a broker password or API key in these files. The
Questrade token goes through `accounts.py sync --token` (saved privately in
`trader/state/`), and the whole `trader/` folder is git-ignored, so holdings
never land on GitHub. Not financial advice: the defaults are cautious
starting points, not recommendations.
