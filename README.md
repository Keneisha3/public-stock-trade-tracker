# Portfolio Tracker

A personal investing workbench for a Canadian investor, in plain Python with
nothing to install. It looks after two real accounts with different
jobs, an aggressive growth account at **Questrade** (US stocks) and a steady
dividend account at **Wealthsimple**, and adds a daily briefing, a local
dashboard and a paper-trading bot that has to prove itself before anyone
trusts it.

![The dashboard, with demo holdings](docs/dashboard.png)

*The dashboard with made-up demo holdings and simulated prices.*

## What it does

| | |
| --- | --- |
| **Reviews each account against its own strategy** | Growth: momentum, trend, a stop from your cost, trims winners that outgrow the cap. Medium term: trend-following, flags broken trends. Dividend: yield in a sane band, dividend growth, cut detection, volatility, projected monthly income. |
| **Plans your next contribution** | Splits new money toward your target mix (say 60 % growth, 40 % dividend), then inside each account to the holdings under target. No buy ever pushes a stock past its cap. |
| **Knows it is Canadian** | Values everything in CAD with live USD/CAD, knows US dividends lose 15 % in a TFSA but not in an RRSP, flags when you need to convert currency, and warns that day trading in a TFSA can be taxed as business income. |
| **Runs a daily briefing** | One command: sync Questrade, refresh prices and dividends, review, record the day's value, run the paper bot, check news on your holdings, new Congress stock-trade filings and your price alerts. |
| **Shows it all on a dashboard** | A local web page: total and today's change, value history, mix vs target, to-dos, proposed trades, holdings with flags and sparklines, the paper bot vs buy-and-hold, news, Congress filings, CSV import. Light and dark mode, works on a phone. |
| **Paper-trades automatically** | An ATR breakout bot from my [ATR research project](https://github.com/Keneisha3/ATR-Based-News-Triggered-Stock-System) trades a paper ledger every day, with a 5-year backtest and a "ready for real money?" checklist it has to pass. |
| **Runs a crypto bot team on fake money** | A Scanner, Analyst, Risk Manager and Executor trade 10 coins on daily bars, checked every 15 minutes (EMA crossover + RSI, 2 % max risk, stop-loss and take-profit on every trade). Simulated by default, or Alpaca's paper account. CSV log, daily summary against buy-and-hold, kill switch. [Beginner guide](docs/crypto-bot-team.md). |
| **Never trades for you** | Proposals are a to-do list. You place every real trade yourself in your broker's app. |

## Quick start

You need Python 3.9 or newer. There is nothing to pip install.

```bash
git clone https://github.com/Keneisha3/public-stock-trade-tracker.git
cd public-stock-trade-tracker
python3 trade.py dashboard --open     # opens http://127.0.0.1:8765
```

The first screen sets things up. Pick **Try it with demo holdings** to see it
working, or **Set up my accounts** to start real. Then get your holdings in:

- **Wealthsimple:** export the holdings report as CSV from the web app and
  upload it on the dashboard (or `python3 trade.py accounts import wealthsimple file.csv`).
- **Questrade:** in Questrade's App Hub, register a personal app with read
  access and generate a token, then run this once:
  `python3 trade.py accounts sync questrade --token YOUR_TOKEN`.
  The token rotates on every login and is kept in `trader/state/` (mode 600).
  After that, **Refresh everything** syncs it for you.
- Set cash balances on the dashboard.

Press **Refresh everything** once a day, or schedule the daily run (below).

Optional: set `SEC_USER_AGENT="Your Name you@example.com"` to include SEC
filings in the news. Install `pdftotext` (poppler) so the Congress tracker
can read disclosure PDFs.

## Ask in plain words

The `.claude/skills/` folder holds a skill for every tool, so an AI coding
assistant opened in this folder can run them from plain requests:

| Say | Skill |
| --- | --- |
| "set me up", "change my target mix" | `/trader-init` |
| "review my portfolio", "where should my next $500 go?" | `/trader-accounts` |
| "morning briefing", "what happened today?" | `/trader-daily` |
| "backtest the bot", "how is the paper bot doing?" | `/trader-paper` |
| "copy Berkshire's top 5" | `/trader-copycat` |
| "any news on my stocks?" | `/trader-news` |
| "what is Pelosi buying?" | `/trader-pelosi` |
| "how did Apple's earnings look?" | `/trader-analyst` |
| "screen for growing companies under 30x earnings" | `/trader-screener` |
| "size this to $5,000" / "check these orders" | `/trader-budget` / `/trader-risk` |
| "tax-loss harvest", "alert me if NVDA drops to 150", "rebalance" | `/trader-tax`, `/trader-alerts`, `/trader-rebalance` |
| "run the crypto bot", "how did the bot team do?", "kill the bot" | `/trader-team` |
| "place the order" (paper by default, a yes per order) | `/trader-broker` |

Two plugins are switched on in the project settings:
[Agent Skills](https://github.com/addyosmani/agent-skills) (spec, test-first,
security and code-review workflows) and
[Ponytail](https://github.com/DietrichGebert/ponytail) (smallest,
standard-library-first changes; needs Node.js).

## The command line

Everything goes through `trade.py`. Add `--help` to any command:

```bash
python3 trade.py init --with-medium --mix growth=50,medium=20,dividend=30
python3 trade.py accounts market                  # prices, dividends, USD/CAD
python3 trade.py accounts review                  # flags + proposals per account
python3 trade.py accounts review --contribute 1000
python3 trade.py daily                            # the whole daily run
python3 trade.py paper backtest                   # stock bot: 5 years vs buy-and-hold
python3 trade.py paper status                     # equity, trades, readiness
python3 trade.py crypto status                    # crypto bot team
python3 trade.py replay                           # $100 in every strategy, 1 week to 6 months ago
python3 trade.py news                             # also: copycat, pelosi, analyst, screener,
                                                  # budget, risk, broker, tax, alerts, rebalance
```

**Run everything by itself:** `python3 trade.py schedule --install` (Mac/Linux)
schedules the daily run for weekdays at 5:30 p.m. and a crypto bot team cycle every 15
minutes. [docs/daily-use.md](docs/daily-use.md) covers Windows and the 5-minute
daily routine.

## The strategies

Defaults, all overridable per account in `trader/accounts.json`:

| rule | growth (Questrade) | medium term | dividend (Wealthsimple) |
| --- | --- | --- | --- |
| max per stock | 30 % | 15 % | 12 % |
| cash target / max | 0 / 10 % | 3 / 10 % | 2 / 8 % |
| momentum lookback | 3 months | 6 months | n/a |
| stop from your cost | -25 % | -20 % | -30 % |
| also flags | laggards (down 12 months and below cost) | price under its 200-day average and falling | no dividend, yield under 2 % or over 8 %, cuts, shrinking payouts, volatility over 30 % |

With only a few holdings, the cap rises to an equal share so good stocks are
not sold into idle cash. A "concentrated" flag asks for more names instead,
and every account has a watchlist of ideas that get scored like holdings.
Scores (0 to 100) rank holdings inside an account. They are simple
heuristics on public data, not forecasts.

## The paper bot, honestly

The bot buys a stock the day after it jumps at least 1.5x its average true
range (ATR), but only while the market is in an uptrend. It risks 1 % of
equity per trade, puts its stop 2 ATR below the entry, exits after 3 days
and pays 5 bps per side.
The research behind it found a real but small edge: about +0.33 % over 3
days, a 49 % win rate, and long-only results that were mostly market beta.
That is why it trades paper money, and why `status` shows a readiness
checklist (60+ days, 30+ trades, profit after costs, beating buy-and-hold,
drawdown under 15 %). Most people who day trade lose money; this exists to
find out with evidence instead of with savings.

## Replay: what would $100 have done?

`python3 trade.py replay` gives every strategy $100 CAD 12, 6, 3 and 1 months,
2 weeks and 1 week before the latest Friday close (`--windows` to change them), and compares them with
holding the S&P 500, the Nasdaq 100, the TSX 60, Bitcoin or cash. It is strictly point in time:
each decision sees only what was known at that day's close and fills at the
next open. US stocks trade in US dollars and Canadian stocks in Canadian
dollars, as in the real accounts, so nothing is converted per trade; results
are shown in CAD at each day's rate. It counts slippage, dividends and US
withholding. A
separate **Pelosi copycat** row copies Nancy Pelosi's disclosed trades from
the day each filing was posted, not the day she traded. A test wrecks every
price after the as-of date and checks that no result moves.

**No hindsight in the stock picks.** By default the agents choose only from
what was in the S&P 500 on each day (a membership history back to 1996, MIT
licence, [fja05680/sp500](https://github.com/fja05680/sp500)), plus 93 index
funds (sectors, factors, countries, bonds, gold, Canadian funds) and about 70
large Canadian companies. At each review a scanner ranks all of them and the
reviewer scores the best 20 to 25; the stock bot trades any member, only on
days it was a member. Yahoo has no prices for many companies that later left
the market, so the report shows how many index members it could price.
Today's hand-picked watchlists stay as comparison rows marked "hindsight".
`--history 10y` loads ten years; `--universe watchlists` goes back to the old way.

On top of the replay:

- **Scenarios.** Each strategy is replayed with different settings (momentum
  lookback, per-stock cap, number of holdings, stop-loss, cash, rebalance
  frequency, yield floor). The table shows the inputs beside the outputs,
  including a **Your settings** row for whatever you saved on the dashboard.
- **Monte Carlo.** 5,000 block-bootstrap runs of each strategy's own daily
  returns give the bad, median and good case for the next 6 months, the
  chance of a profit, and the chance of beating the S&P 500.
- **Your own portfolio.** With your holdings imported (or `--holdings ACCOUNT=FILE`),
  each account gets two extra rows: your current mix held as is, and the same mix
  run by that account's strategy rules. Holdings stay in `trader/` on your
  computer; the GitHub workflow never sees them.
- **Rolling windows.** Twelve 3-month windows, one starting each month, show
  how often each strategy beat the S&P 500. That is the evidence that matters.
- **Self-checks.** Every run checks its own numbers: prices are fresh, every
  window is complete, values are sane, curves line up, and the S&P 500 row
  matches the raw price change. `--strict` (used by the workflow) fails the
  run if any check fails.
- **Risk stats.** Volatility, Sharpe ratio, max drawdown and share of up days.
- **VIX agent and VIX analysis.** A rule-based agent holds the Nasdaq 100
  while the VIX (the market's fear gauge) is at or under 30 and steps aside to
  US-dollar cash above it (also tested: the S&P 500, thresholds 20 and 25,
  "above its 50-day average", and the 3-month VIX term structure). Every strategy
  is also broken down by VIX regime (calm, normal, nervous, fear) and by how
  it moves with the VIX. The daily briefing and the dashboard show today's
  VIX and what the agent would do.

**Walk-forward test.** The workflow's `walk-forward` mode downloads ten years
of prices once, replays five periods ending 2019-10, 2020-10, 2022-10, 2024-10
and 2026-10 in parallel (the 2018 sell-off, the 2020 crash and the 2022 bear
market included), and combines them into one table (`scripts/walkforward.py`).

**What the walk-forward found** (`research/pit-v8-model/` on the
`replay-results` branch). Settings were chosen on the training periods only
(24-month windows ending 2019, 2020, 2022 and 2024); the last 12 months were
held out and only used to check. `stats.md` adds 28 overlapping 12-month
windows inside the training years, with 90 % confidence ranges.

| agent | training: beat the S&P 500 | training: average gap | 28 windows: average gap (90 % range) | test, last 12 months |
| --- | ---: | ---: | --- | ---: |
| **70 % Nasdaq 100 + 30 % dual momentum (the chosen plan)** | 4 of 4 | +14.9 pts | +8.5 (+3.9 to +15.2), 23 of 28 | +27.1 % |
| Dual momentum alone (single strongest fund) | 3 of 4 | +11.8 pts | +13.4 (+2.0 to +26.9) | +35.8 % |
| Just holding the Nasdaq 100 | 3 of 4 | +14.0 pts | +5.8 (+0.1 to +12.3) | +20.3 % |
| Congress buying | 1 of 4 | -1.7 pts | +0.1 (-2.3 to +1.9) | +32.6 % |
| Insider buying | 1 of 4 | -8.0 pts | -1.1 (-4.4 to +3.6) | +2.8 % |
| Learned score (ridge model, refit yearly) | 1 of 4 | -21.0 pts | -5.2 (-15.9 to +4.5) | +19.4 % |
| Reviewers, stock bot, momentum, VIX agent | 0 to 2 of 4 | below zero | ranges include zero | |
| S&P 500 | | | | +17.9 % |

The chosen plan keeps drops like the Nasdaq 100's (average worst drop -22 %
in training). Its edge over simply holding the Nasdaq 100 is small in
training and larger in the test year. Insider and Congress signals, a
learned score and member-weighted Congress trades did not beat the index
once hindsight was removed. The live paper record (`forward/record.json`,
from 2026-10-19) is the test that matters next.

**It runs itself.** The `replay` GitHub Actions workflow runs the whole replay
on GitHub's machines every Saturday after Friday's close (or on demand from the
Actions tab, with an optional as-of date). The report appears on the run's
summary page and on the
[`replay-results`](https://github.com/Keneisha3/public-stock-trade-tracker/tree/replay-results)
branch, with one file per week in `history/`. It uses the default watchlists,
never your holdings.

Every account's settings are editable on the dashboard (**Strategy settings**)
and are range-checked. The live review and the replay use the same rules.

## The crypto bot team

Four roles trade 10 big coins on daily bars (checked every 15 minutes), on fake money only:

| role | job |
| --- | --- |
| Scanner | checks the data and spots a fresh EMA 9/21 crossover |
| Analyst | BUY only if price is above the 50-bar EMA and RSI is 50 to 70; EXIT when the crossover reverses |
| Risk Manager | stop 1.5 ATR, target 3 ATR, size so a stop-out costs at most 2 % of the account, max 3 trades, -5 % a day trips the kill switch |
| Executor | simulated broker (default, no keys), or Alpaca PAPER behind four checks; there is no live-trading address in the code |

```bash
python3 trade.py crypto check
python3 trade.py crypto backtest --days 30
python3 trade.py crypto run          # Ctrl+C to stop, `crypto kill` to sell all and stop
python3 trade.py crypto summary
```

Every trade goes to `trader/team/trades.csv`, with entry, exit, size,
stop-loss, take-profit, fees and slippage, P&L and which roles approved it.
The guide's 15-minute bars lost 43 to 44 % of the money in six months in
both test periods, mostly to fees: stops that close are smaller than the
trading costs. Daily bars were the only timeframe that made money in both
periods (+22 % in the year to 2025-10-17, +10 % in the year to 2026-10-16),
so they are the default. Holding Bitcoin did better in the first year
(+61 %) and worse in the second (-24 %). Keep it on paper.

## How it is built

```
trade.py               one command for everything
.claude/skills/        16 skills and their Python tools: 11 from the Trader skill pack + accounts, paper, daily, init, team
app/                   server.py (standard-library HTTP, 127.0.0.1 only) + index.html (no frameworks)
tests/                 unittest suite, fully offline; synthetic Yahoo charts in _synth.py
trader/                your data: holdings, prices, history, ledger (git-ignored)
.claude/hooks/         session-start hook: installs pdftotext in cloud sessions, creates trader/
scripts/schedule.sh    the daily schedule (cron)
.github/workflows/     CI on Python 3.9 and 3.13
scripts/update-skills.sh   pull upstream skill updates
```

- **Data:** Yahoo Finance's free chart endpoint (prices, dividends, FX), SEC
  EDGAR, the House Clerk, and Questrade's read-only API. All free, no paid
  keys.
- **Privacy:** the dashboard listens on 127.0.0.1 only. It rejects foreign
  Host headers and cross-site writes, and loads nothing from the internet.
  Your holdings stay in `trader/`, and API keys stay in `.env`. Git ignores both.
- **Tests:** `python3 -m unittest discover -s tests` runs 230+ tests offline
  in a few seconds. They cover CSV import, the Questrade token rotation,
  dividend-cut detection, the cap rules, the bot's entries, stops and exits,
  the crypto team's paper guard and kill switch, and the dashboard's
  security checks.

## Credits

- The 11 `trader-*` research and order skills are the
  [Trader skill pack](https://github.com/Jakeschincariol/trader-skill) by
  Jake Schincariol (MIT, see `.claude/skills/LICENSE-trader-skill`).
  Update them with `scripts/update-skills.sh`.
- The paper bot's signal comes from my
  [ATR-Based News-Triggered Stock System](https://github.com/Keneisha3/ATR-Based-News-Triggered-Stock-System).

## Fine print

**Not financial advice.** This is software that reads public, delayed data
and does arithmetic. It does not know your full situation, it cannot see the
future, and simulated results do not predict real ones. You can lose money.
Make your own decisions, and talk to a licensed professional if you need
advice.
