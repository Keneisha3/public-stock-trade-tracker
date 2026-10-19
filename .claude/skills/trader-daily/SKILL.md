---
name: trader-daily
description: >-
  The daily briefing, one command: syncs Questrade, refreshes prices,
  dividends and USD/CAD, reviews every account against its strategy, records
  the day's value, runs the paper trading bot, checks news on your holdings,
  new Congress stock-trade filings and your price alerts, then writes
  trader/briefing.md and trader/briefing.json (the dashboard reads them).
  Use when the user says "morning briefing", "daily update", "what happened
  today", "run my daily", "how did my portfolio do", "check everything", or
  sets up a daily schedule.
argument-hint: "[--skip news congress ...]"
---

# trader-daily

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/daily.py"                     # the full run
python3 "${CLAUDE_SKILL_DIR}/daily.py" --skip congress     # faster
python3 "${CLAUDE_SKILL_DIR}/daily.py" --json
```

Steps, each optional and failure-tolerant: sync (Questrade, if a token is
saved), market, review, history, paper, news, congress, alerts.

## Reading it to the user

Lead with one line: total, today's change, monthly dividend income. Then the
to-do list (ACTION items) and proposed trades, each with its one-line
reason. Then anything in news that touches a holding, new Congress filings
in stocks they own, and the paper bot in one line against buy-and-hold.
Finish with steps that failed and how to fix them (usually: no Questrade
token yet, or no SEC user agent). Keep it short: this is a daily habit, not
a report.

## Running it every day

- **On the user's computer (best):** the dashboard has a Refresh button
  that runs this. Or schedule it: macOS/Linux
  `crontab -e` -> `15 16 * * 1-5 cd /path/to/repo && python3 .claude/skills/trader-daily/daily.py >/dev/null`
  (4:15 p.m. on weekdays, after the close; use the time zone the computer is in).
- **In Claude:** `/loop 24h /trader-daily`, or a scheduled task that opens
  the repo and runs the skill each weekday morning.

Data lives in `trader/` on the machine that runs it (git-ignored). A cloud
session starts empty, so the daily habit belongs on the user's own computer.

**Not financial advice.** Nothing here places a trade.
