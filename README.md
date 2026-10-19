# Portfolio Tracker

A personal investing workbench for a Canadian investor, built on Claude Code
skills and plain Python. It looks after two real accounts with different
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
| **Runs a crypto bot team on fake money** | A Scanner, Analyst, Risk Manager and Executor trade 10 coins every 15 minutes (EMA crossover + RSI, 2 % max risk, stop-loss and take-profit on every trade). Simulated by default, or Alpaca's paper account. CSV log, daily summary against buy-and-hold, kill switch. [Beginner guide](docs/crypto-bot-team.md). |
| **Never trades for you** | Proposals are a to-do list. You place every real trade yourself in your broker's app. |

## Quick start

You need Python 3.9 or newer. There is nothing to pip install.

```bash
git clone https://github.com/Keneisha3/public-stock-trade-tracker.git
cd public-stock-trade-tracker
python3 app/server.py --open          # opens http://127.0.0.1:8765
```

The first screen sets things up. Pick **Try it with demo holdings** to see it
working, or **Set up my accounts** to start real. Then get your holdings in:

- **Wealthsimple:** export the holdings report as CSV from the web app and
  upload it on the dashboard (or `accounts.py import wealthsimple file.csv`).
- **Questrade:** in Questrade's App Hub, register a personal app with read
  access and generate a token, then run this once:
  `python3 .claude/skills/trader-accounts/accounts.py sync questrade --token YOUR_TOKEN`.
  The token rotates on every login and is kept in `trader/state/` (mode 600).
  After that, **Refresh everything** syncs it for you.
- Set cash balances on the dashboard.

Press **Refresh everything** once a day, or schedule the daily run (below).

Optional: set `SEC_USER_AGENT="Your Name you@example.com"` to include SEC
filings in the news. Install `pdftotext` (poppler) so the Congress tracker
can read disclosure PDFs.

## Using it with Claude

Open the folder in Claude Code. The skills load on their own, and the
session-start hook sets things up. Ask in plain words:

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

## The command line

```bash
S=.claude/skills
python3 $S/trader-init/init.py --with-medium --mix growth=50,medium=20,dividend=30
python3 $S/trader-accounts/accounts.py market                 # prices, dividends, USD/CAD
python3 $S/trader-accounts/accounts.py review                 # flags + proposals per account
python3 $S/trader-accounts/accounts.py review --contribute 1000
python3 $S/trader-daily/daily.py                              # the whole daily run
python3 $S/trader-paper/paper.py backtest                     # 5 years vs buy-and-hold
python3 $S/trader-paper/paper.py status                       # equity, trades, readiness
```

**Run it every weekday** after the close (macOS/Linux, `crontab -e`):

```
15 16 * * 1-5  cd /path/to/public-stock-trade-tracker && python3 .claude/skills/trader-daily/daily.py >/dev/null
```

## The strategies

Defaults, all overridable per account in `trader/accounts.json`:

| rule | growth (Questrade) | medium term | dividend (Wealthsimple) |
| --- | --- | --- | --- |
| max per stock | 20 % | 15 % | 12 % |
| cash target / max | 3 / 10 % | 3 / 10 % | 2 / 8 % |
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

## The crypto bot team

Four roles trade 10 big coins every 15 minutes, on fake money only:

| role | job |
| --- | --- |
| Scanner | checks the data and spots a fresh EMA 9/21 crossover |
| Analyst | BUY only if price is above the 50-bar EMA and RSI is 50 to 70; EXIT when the crossover reverses |
| Risk Manager | stop 1.5 ATR, target 3 ATR, size so a stop-out costs at most 2 % of the account, max 3 trades, -5 % a day trips the kill switch |
| Executor | simulated broker (default, no keys), or Alpaca PAPER behind four checks; there is no live-trading address in the code |

```bash
python3 .claude/skills/trader-team/team.py check
python3 .claude/skills/trader-team/team.py backtest --days 30
python3 .claude/skills/trader-team/team.py run          # Ctrl+C to stop, `kill` to sell all and stop
python3 .claude/skills/trader-team/team.py summary
```

Every trade goes to `trader/team/trades.csv`, with entry, exit, size,
stop-loss, take-profit, fees and slippage, P&L and which roles approved it.
On 15-minute bars, fees and slippage are a large share of each trade's risk.
The log says so on every trade, and it is the first thing to look at when
you review the results.

## How it is built

```
.claude/skills/        16 skills: 11 from the Trader skill pack + accounts, paper, daily, init, team
app/                   server.py (standard-library HTTP, 127.0.0.1 only) + index.html (no frameworks)
tests/                 unittest suite, fully offline; synthetic Yahoo charts in _synth.py
trader/                your data: holdings, prices, history, ledger (git-ignored)
.claude/hooks/         session-start hook: installs pdftotext in the cloud, creates trader/
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
