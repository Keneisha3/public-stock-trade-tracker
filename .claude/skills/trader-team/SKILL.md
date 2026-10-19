---
name: trader-team
description: >-
  A crypto trading bot TEAM on PAPER money only: a Scanner checks 10 major
  coins on daily bars, an Analyst looks for an EMA 9/21 crossover with RSI
  50-70 in an uptrend, a Risk Manager risks at most 2% of the paper account
  per trade with a stop-loss and take-profit (2:1), and an Executor places
  SIMULATED trades (default, no account) or Alpaca PAPER trades, refusing
  anything that is not clearly paper. Logs every trade to CSV, prints a daily
  summary against buy-and-hold, has a kill switch and a backtest. Use when the
  user says "crypto bot", "trading bot team", "bot team", "scanner analyst
  risk executor", "paper trade crypto", "run the bot", "kill the bot", "how
  did the bot do", "review my trading CSV", or pastes the "Build Your Own AI
  Trading Bot Team (Paper Mode)" guide.
argument-hint: "[check | run | status | summary | kill | resume | backtest]"
---

# trader-team

Four roles, daily bars checked every 15 minutes, fake money only. The beginner guide
with every file explained is `docs/crypto-bot-team.md` in the repo.

`${CLAUDE_SKILL_DIR}` below is this skill's folder. Run from the repo root.

```bash
python3 "${CLAUDE_SKILL_DIR}/team.py" check            # set up right? never trades
python3 "${CLAUDE_SKILL_DIR}/team.py" backtest --days 30
python3 "${CLAUDE_SKILL_DIR}/team.py" run              # checks every 15 min until Ctrl+C or the kill switch
python3 "${CLAUDE_SKILL_DIR}/team.py" run --once       # one cycle, for cron
python3 "${CLAUDE_SKILL_DIR}/team.py" status
python3 "${CLAUDE_SKILL_DIR}/team.py" summary --day 2026-10-20
python3 "${CLAUDE_SKILL_DIR}/team.py" kill             # KILL SWITCH: sell all paper positions, stop
python3 "${CLAUDE_SKILL_DIR}/team.py" resume
```

If `trader/team/config.json` is missing, run `/trader-init` (it writes the
defaults), or copy `config.example.json` there.

## The roles

| role | file | job |
| --- | --- | --- |
| Scanner | `scanner.py` | data checks on 10 coins (enough bars, fresh, moving, volume) and picks setups: a fresh fast/slow EMA crossover; held coins always go on for an exit check |
| Analyst | `analyst.py` | BUY when EMA 9 crosses above EMA 21, price is above EMA 50 and RSI(14) is 50-70; EXIT when EMA 9 crosses back below |
| Risk Manager | `risk_manager.py` | stop = entry - 1.5 ATR, target = entry + 3 ATR; size so a stop-out costs at most 2 % of the account including fees; max 25 % in a coin, 3 open trades, 6 % total risk; cool-off after a stop; -5 % in a day trips the kill switch |
| Executor | `executor.py` | SIMULATED broker (default) or Alpaca PAPER; refuses unless `TRADING_MODE=paper`, the paper URL, a `PK` paper key and an Alpaca paper account (`PA...`) all check out |

`team.py` runs the cycle, `candles.py` fetches daily candles by default (Coinbase,
no key; or Alpaca), `trade_log.py` writes `trades.csv`, `events.csv` and
`equity.csv` and builds the summary.

## Helping the user set up

1. Start in `"broker": "sim"`. No account, no keys. Run `check`, then
   `backtest --days 30`, then `run`.
2. Only if they want Alpaca's paper account: they create PAPER keys
   themselves, copy `.env.example` to `.env` and paste the keys into that
   file on their own computer. **Never ask for keys in chat.** If they paste
   one, tell them to delete the message and regenerate the key in Alpaca.
   Then set `"broker": "alpaca-paper"` and `"data": "alpaca"`, run `check`.
3. `.env` is git-ignored. Confirm with `git check-ignore .env`.

Never add a live-trading URL, never relax the paper guard, never raise
`risk_pct` above 2 (the config loader refuses it). If the user asks to go
live, say no: this project is for learning with fake money, and live
crypto trading is a different risk.

## Reviewing results (the user's review prompt)

When they share or ask about `trader/team/trades.csv`:

1. Read `trades.csv`, `equity.csv` and `events.csv`, run `summary`.
2. Explain in plain words: trades, wins and losses, win rate, average win
   and loss, total P&L, fees and slippage, max drawdown, the bot against
   holding the same coins over the same time, errors and downtime.
3. Look for patterns in the LOSING trades: which coins, time of day, exit
   reason (stop-loss vs signal), RSI at entry, trades right after another loss.
4. Do not change the strategy to make the past look better. Suggest 3 small
   changes, each tested separately for 2 to 4 weeks, one at a time.
5. Remind them: one week is a first look, not proof; paper fills are kinder
   than real ones; keep the losing trades in the CSV.

## Safety rules

**Not financial advice. Paper money only.** Stay on paper for at least 2 to 4
weeks before drawing any conclusion, and even then this project never trades
real money. Claims like "$100 to $61,873" are unverified and not normal.
Most people who day trade lose money.
