---
name: trader-paper
description: >-
  Automated short-term trading bot, on PAPER money only. Runs the ATR breach
  strategy validated in Keneisha's ATR-Based-News-Triggered-Stock-System (a
  1.5 ATR up-move in a bull regime tends to keep going for a few days): buys
  at the next open, risks 1% of equity per trade with a 2 ATR stop, exits
  after 3 days, 5 bps costs, max 8 names. Backtests the rule over 5 years
  against buy-and-hold, then trades a paper ledger automatically every day
  and tracks whether it actually beats just holding. Use when the user says
  "day trade", "trading bot", "automate my trading", "auto trade", "swing
  trade", "paper trade", "backtest", "does the bot make money", "how is the
  bot doing", or asks for something that trades on its own.
argument-hint: "[backtest | run | status | reset]"
---

# trader-paper

An automated trading bot that only ever trades paper money. It exists so the
user can find out, with evidence, whether short-term trading makes money for
them before risking a dollar, and so the trading itch has somewhere safe to go.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/paper.py" backtest         # 5 years: bot vs buy-and-hold, per year
python3 "${CLAUDE_SKILL_DIR}/paper.py" run              # catch up to the latest close, trade on paper
python3 "${CLAUDE_SKILL_DIR}/paper.py" status           # equity, positions, trades, readiness
python3 "${CLAUDE_SKILL_DIR}/paper.py" reset --cash 10000
```

The universe is 30 liquid US large caps; put your own list in
`trader/paper/config.json` as `{"universe": ["NVDA", "AMD", ...]}`.

## The rule (from the ATR research project)

- **Breach:** today's close-to-close move is at least 1.5 x the 14-day ATR.
- **Regime:** an equal-weight index of the universe above its 50-day average
  is a bull regime. The research found breaches continue in bull regimes and
  fade in bear ones, so the bot only buys up-breaches in a bull regime and
  never shorts.
- **Trade:** buy at the next open; stop at entry - 2 ATR; sell at the close of
  the third day held. Risk 1 % of equity per trade, max 15 % in one name,
  max 8 names. 5 bps per side for commission and slippage.
- **Idle cash:** cash no trade is using sits in QQQ (the Nasdaq 100), sold at
  the open when a trade needs it. So the bot is "the index plus its trades"
  instead of mostly cash. In the replay, this beat both the cash version and
  holding QQQ alone in both test periods (as of 2025-10-17 over 24 months:
  +81 % vs +71 % for QQQ; the year to 2026-10-16: +30 % vs +20 %). The
  universe is today's large caps, which flatters it. Set `"idle": null` in
  the ledger's params to turn it off.

## Tell the user the truth about day trading

Say this plainly when they ask for a bot that "makes money daily":

- Most retail day traders lose money once costs are counted. No rule makes
  money every day; a good one makes a little more than it loses over many
  trades.
- The research behind this rule found a real but small edge: about +0.33 %
  expected drift over 3 days, a 49 % win rate, and long-only results that
  were mostly market beta (Sharpe 1.05 vs 1.03 for buy-and-hold). Costs ate
  half of it at 5 bps. That is a timing overlay, not a money machine.
- This is swing trading (a few days), not intraday. Free data is daily; real
  intraday trading needs paid real-time data and a broker API.
- In Canada, frequent trading inside a TFSA can make CRA treat the gains as
  business income and tax them. Do not run a trading strategy in the TFSA.

## Automation, and why it stays on paper

`run` is safe to schedule daily after the 4 p.m. ET close (the daily
briefing calls it). It catches up any missed days and never contacts a
broker. `status` prints a readiness checklist: 60+ trading days, 30+ closed
trades, profit after costs, beating buy-and-hold of the same stocks, worst
drawdown under 15 %. Until every line is ok, the answer to "should I run it
with real money" is no.

Even when it is ready, real money goes through the user, not the bot:
Questrade's personal API cannot place orders and Wealthsimple has no API. The
next step after paper would be the Alpaca paper API through `/trader-broker`,
still with a yes per order. Never wire this bot to place real orders on its
own.

**Not financial advice.** Simulated results on past and delayed data. Past
performance does not predict future results.
