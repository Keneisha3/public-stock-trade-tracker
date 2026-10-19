# Portfolio Tracker: project notes

A personal investing workbench for a Canadian investor with two real accounts:
**Questrade** (aggressive growth, US stocks) and **Wealthsimple** (steady
dividends), plus an optional medium-term sleeve, a paper-trading bot, a daily
briefing and a local dashboard. Everything is standard-library Python.

## Layout

```
.claude/skills/trader-*/     16 skills (11 from Jakeschincariol/trader-skill + 5 of ours)
  trader-accounts/           accounts.py (import, Questrade sync, review), market.py (Yahoo data)
  trader-paper/              paper.py: ATR breach bot, paper money only
  trader-daily/              daily.py: the one-command daily run
  trader-init/               init.py: creates trader/
  trader-team/               team.py + scanner/analyst/risk_manager/executor: crypto bot team, paper only
app/                         server.py + index.html: the dashboard (127.0.0.1:8765)
tests/                       unittest, offline; _synth.py builds fake Yahoo charts
trader/                      the user's data (git-ignored, never commit it)
trade.py                     one entry point: python3 trade.py <command> (docs use this, not skill paths)
scripts/update-skills.sh     pull upstream skill updates
```

Data flows through `trader/`: `accounts.json` (config) -> `accounts/<id>.json`
(holdings) + `market.json` (prices) -> `proposals.json`, `history.json`,
`briefing.json`, `paper/ledger.json`. The upstream skills use
`trader/portfolio.json`, `targets.json`, `orders.json`, `config.json`.

## Commands

```bash
python3 -m unittest discover -s tests            # all tests, offline, ~3 s
python3 trade.py dashboard --open                # the dashboard
python3 trade.py daily                           # the daily run
python3 trade.py accounts review
python3 trade.py paper backtest
python3 trade.py crypto check                    # crypto bot team; never trades
```

## Rules that always hold

- **Nothing places a real trade.** Questrade's personal API is read-only,
  Wealthsimple has no API, the paper bot never imports a broker (a test
  enforces it). The crypto bot team trades only simulated money or Alpaca's
  PAPER endpoint, behind a guard (TRADING_MODE=paper, paper URL, PK key, PA
  account); no live-trading URL may ever appear in it (a test enforces it),
  and `risk_pct` can never exceed 2. Real orders only ever go through
  `/trader-broker` with the user's explicit yes per order. Never add
  auto-execution with real money.
- **Not financial advice.** Show heuristics as heuristics. Never promise
  returns. Be honest that most day traders lose money and that the ATR edge
  is small (+0.33 % over 3 days in the research).
- **Secrets stay out of chat and git.** Never ask for a Questrade token or
  broker keys in chat; the user runs `accounts.py sync --token` themselves.
  `trader/` and `.env` are git-ignored; this repo is public. Keys live only in
  `.env` (template: `.env.example`) and are printed masked.
- **Canadian context matters:** account type (TFSA vs RRSP) changes US
  dividend withholding; frequent trading in a TFSA risks business-income tax.

## Plugins

Enabled in `.claude/settings.json`: `agent-skills@addy-agent-skills`
(review, TDD, security-auditor) and `ponytail@ponytail` (smallest change,
stdlib first).

## Code conventions

- Standard library only, Python 3.9+ (`tests/test_repo.py` checks imports).
- Pure functions for the math (`review_account`, `metrics`, `step`), thin CLIs.
- Every new behaviour gets an offline test; network calls take an `http=` or
  `--offline DIR` hook so tests never touch the internet.
- Match the upstream skill style: plain-English SKILL.md with a frontmatter
  description that lists trigger phrases, and a "Not financial advice" line.
