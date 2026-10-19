---
name: trader-replay
description: >-
  Point-in-time replay: what $100 would have done if invested 1 week, 2
  weeks, 1 month and 6 months ago by every strategy in this project (growth,
  medium and dividend account reviewers, the ATR stock bot, the crypto bot
  team, a separate Nancy Pelosi copycat that only acts once each filing was
  posted) against buy-and-hold S&P 500, TSX 60, Bitcoin and cash, valued at
  the latest Friday close. Decisions only see data up to that day's close and
  fill at the next open; FX fees, slippage, dividends and US withholding are
  counted. Use when the user says "backtest my strategies", "what would $100
  have done", "replay", "compare the bots", "how would following Pelosi have
  done", or "which strategy is working".
argument-hint: "[--asof YYYY-MM-DD] [--cash 100] [--skip crypto pelosi]"
---

# trader-replay

```bash
python3 trade.py replay                         # as of the latest Friday close, $100
python3 trade.py replay --asof 2026-10-16 --cash 100
python3 trade.py replay --skip crypto           # minutes faster
```

Writes `trader/replay/report.md` (a table: strategy x window) and
`report.json`. Needs network access to Yahoo Finance, Coinbase and the House
Clerk, plus `pdftotext` for the Pelosi filings.

## The rules of the replay (point in time)

- Each strategy starts with the cash at the close of the start day and steps
  one trading day at a time. A decision on day D sees prices, dividends and
  filings up to D's close only, and fills at the next open.
- Account reviewers review at the start and every Friday; the stock bot and
  crypto team run their normal cycles.
- Pelosi copycat: a trade is copied only after the filing that discloses it
  was posted (up to 45 days after the trade). Filings public in the 120 days
  before the start form the starting basket. Bought stock or calls: buy the
  stock. Sold stock or bought puts: sell. Equal weight. It is shown as its own
  row.
- Currency: US stocks trade in US dollars, Canadian stocks in Canadian
  dollars, like the real accounts. Each strategy's money starts in the
  currency it trades, so nothing is converted per trade (a 1.5 % fee applies
  only if a buy needs a currency the account ran out of). Results are shown in
  CAD at each day's rate, so USD/CAD moves still count.
- Costs: 5 bps slippage, the bots' fees, 15 % US dividend withholding (TFSA;
  none in an RRSP), dividends on ex-date only for shares owned before that day.

## Scenarios, Monte Carlo, risk

- `report.json` -> `scenarios`: each strategy replayed with different settings
  (built-ins, "Your settings" from accounts.json rules, and any in
  `trader/replay/scenarios.json` as `[{"strategy": "growth", "name": "...",
  "rules": {"momentum_months": 3}}]`). Tunable rules and their ranges are in
  `accounts.TUNABLE`.
- `monte_carlo`: 5,000 block-bootstrap runs (5-day blocks, the same days for
  every strategy) of the 6-month daily returns: percentiles, P(profit),
  P(beat S&P 500), drawdowns. Curves much shorter than the rest sit out.
- `results["6 months"][strategy]["risk"]`: volatility, Sharpe, max drawdown.
- VIX: `results[w]["VIX agent"]` (SPY while the VIX is at or under 25, US-dollar cash
  above it, decided at the close; `switches`, `risk_on_days_pct`), VIX
  variants under `scenarios` with strategy "vix", every strategy's
  `vix_regimes` (average daily return by calm/normal/nervous/fear, correlation
  with VIX changes), and the VIX path in `factors`. Real VIX spikes usually
  come WITH the drop, so the agent often exits after the damage: say so.

## Reading it to the user

Lead with the table. Then say plainly:
- 1 week and 2 weeks are noise: a single stock or a single day decides them.
  Only the 6-month column says anything, and even that is one period.
- Compare every strategy with the S&P 500 and TSX rows: a strategy that does
  not beat holding an index after costs is not worth the effort.
- The watchlists are today's, which flatters the reviewers (hindsight bias).
- On $100, FX fees and minimums are a big share; real accounts usually do
  better on costs, and Questrade may not allow fractional shares.
Then move to improvements, one at a time, each to be re-tested.

**Not financial advice.** A replay of the past does not predict the future.
