# Crypto bot team: beginner guide (paper money only)

**Not financial advice. Paper money only.** This bot is for learning how an
automated trading system works. It cannot trade real money: there is no
real-money trading address anywhere in its code, and it refuses to trade
unless everything says "paper".

## What it is

Four "team members" (small Python files) work together every 15 minutes:

1. **Scanner** checks 10 big coins (BTC, ETH, SOL, XRP, DOGE, LTC, BCH, LINK,
   AVAX, DOT) and picks the ones that might be starting a move.
2. **Analyst** decides if a pick is a real setup: the 9-bar average just
   crossed above the 21-bar average, the price is above the 50-bar average,
   and RSI is between 50 and 70.
3. **Risk Manager** decides how much to buy, so that if the trade goes wrong
   you lose at most 2 % of the (fake) account. Every trade gets a stop-loss
   and a take-profit twice as far away.
4. **Executor** places the fake trade and writes it down in a spreadsheet
   (CSV) with who approved it.

There are two kinds of fake money:

| mode | what it is | what you need |
| --- | --- | --- |
| `sim` (default) | the bot keeps its own pretend $10,000 | nothing, start right away |
| `alpaca-paper` | Alpaca's paper-trading account (fake money, real order system) | a free Alpaca account and its PAPER keys |

Start with `sim`. Move to Alpaca paper later if you want to see real order
handling.

## Step 1: install Python

You need Python 3.9 or newer. Check in a terminal (Mac: Terminal app,
Windows: PowerShell):

```bash
python3 --version
```

If it says 3.9 or higher you are done. If not:

- **Mac:** install from https://www.python.org/downloads/ (the big yellow button).
- **Windows:** install from the same page and tick **"Add python.exe to PATH"**
  on the first screen. On Windows, type `python` instead of `python3` below.

There are no other packages to install. The bot only uses what comes with Python.

## Step 2: get the project

```bash
git clone https://github.com/Keneisha3/public-stock-trade-tracker.git
cd public-stock-trade-tracker
python3 .claude/skills/trader-init/init.py
```

The last line creates the `trader/` folder with the bot's settings in
`trader/team/config.json`.

## Step 3: check it and test it on the past

```bash
python3 .claude/skills/trader-team/team.py check
python3 .claude/skills/trader-team/team.py backtest --days 30
```

`check` confirms the setup and never trades. `backtest` runs the same rules
over the last 30 days with pretend money and prints how it would have done
against simply holding the coins. A backtest is a first look, not a promise.

## Step 4: run it

```bash
python3 .claude/skills/trader-team/team.py run
```

Leave the terminal open. Every 15 minutes it prints a line like:

```
[SIMULATED] 2026-10-20 14:30 UTC  equity $10,012.40  buy-and-hold $10,040.10  open 1  new 0  closed 0
[SIMULATED] BUY 0.0123 BTC @ 67,512  stop 66,880  target 68,776  risking $199.80
```

Every trade line starts with `[SIMULATED]` (or `[PAPER]` with Alpaca). If you
ever see anything else, stop the bot.

To stop it: press **Ctrl+C** (it keeps its positions and logs), or use the
kill switch below.

Prefer not to keep a terminal open? Run one cycle every 15 minutes with cron
(Mac/Linux, `crontab -e`):

```
*/15 * * * * cd /path/to/public-stock-trade-tracker && python3 .claude/skills/trader-team/team.py run --once >> trader/team/cron.log 2>&1
```

## The kill switch

```bash
python3 .claude/skills/trader-team/team.py kill      # sell every paper position, then stop
python3 .claude/skills/trader-team/team.py resume    # turn it back on
```

It also turns itself on when:
- the account loses 5 % in one day, or
- 5 cycles in a row fail (internet down, API errors).

The dashboard (`python3 app/server.py --open`) has a kill switch button too.

## Optional: Alpaca paper account

1. Sign up free at alpaca.markets. In the dashboard, switch to the **Paper**
   account (top left). Go to API Keys and click Generate. Paper keys start
   with `PK`.
2. In the project folder, copy the example file and open it in a text editor:
   ```bash
   cp .env.example .env
   ```
   Paste your key and secret into `.env`. Keep `TRADING_MODE=paper`.
   `.env` is git-ignored, so it never goes to GitHub. Never paste keys into
   a chat, an email or a code file.
3. In `trader/team/config.json` set `"broker": "alpaca-paper"` and
   `"data": "alpaca"`.
4. Run `team.py check`. It should say "Alpaca PAPER account confirmed".
   If it refuses, read the reason: it is protecting you.

Alpaca does not support stop orders for crypto, so the bot watches the stops
itself every 15 minutes. A price can jump past a stop between checks, so a
loss can be a bit bigger than planned. Real trading has the same problem.

## Step 5: let it run for 2 to 4 weeks

- Do not change the rules after every loss.
- Keep every losing trade in the CSV.
- Do not raise the risk after a winning streak. The bot will not let you go above 2 %.
- Downtime, API errors and missed cycles are logged in `trader/team/events.csv`.

## Step 6: read the results

```bash
python3 .claude/skills/trader-team/team.py summary
python3 .claude/skills/trader-team/team.py summary --day 2026-10-21
```

You get: total trades, wins and losses, win rate, average win and loss, total
P&L, fees and slippage, max drawdown, the bot against holding the same coins,
errors and downtime. The full history is in `trader/team/trades.csv` (opens
in Excel or Google Sheets).

Then ask Claude in this project:

> Here is my PAPER trading CSV. Explain the results in beginner-friendly
> language. Compare the bot with buy-and-hold. Identify repeated patterns in
> the losing trades. Do not change the strategy just to make the past look
> better. Suggest 3 small improvements I can test separately, one at a time.

## Every file, in simple English

All in `.claude/skills/trader-team/`:

| file | what it does |
| --- | --- |
| `team.py` | The boss. Runs a cycle every 15 minutes, in this order: check the kill switch, check stops and targets, then Scanner, Analyst, Risk Manager, Executor, then save everything. Also the commands: check, run, status, summary, kill, resume, backtest, reset. |
| `candles.py` | Downloads 15-minute price bars ("candles") from Coinbase (no key needed) or Alpaca. Reads your `.env` file without ever printing your keys. |
| `scanner.py` | The Scanner. Skips coins with bad or old data and passes possible setups to the Analyst. |
| `analyst.py` | The Analyst. Works out the averages (EMA), RSI and ATR, and says BUY, EXIT or nothing, with the reasons written out. |
| `risk_manager.py` | The Risk Manager. Sets the stop-loss and take-profit and decides the size, or says no. Also the 5 %-a-day loss limit. |
| `executor.py` | The Executor. The simulated broker, and the Alpaca paper broker with its four safety checks. |
| `trade_log.py` | Writes the CSV files and builds the summary numbers. |
| `config.example.json` | Every setting with its default. Your copy lives in `trader/team/config.json`. |
| `SKILL.md` | Instructions for Claude, so you can ask in plain words ("how did the bot do?"). |

What it writes in `trader/team/` (git-ignored, stays on your computer):

| file | what is in it |
| --- | --- |
| `trades.csv` | one row per finished trade: open and close time, mode, coin, entry, exit, size, stop-loss, take-profit, fees and slippage estimate, profit or loss, why it closed, and which roles approved it |
| `equity.csv` | the account value and the buy-and-hold value after every cycle |
| `events.csv` | errors, downtime, missed cycles, kill switch |
| `state.json` | open positions and the fake cash |
| `KILL` | exists only while the kill switch is on |
| `backtest/` | the latest backtest, same files |

## Final checklist

- [ ] `team.py check` says SIMULATED mode (or Alpaca PAPER account confirmed)
- [ ] if using Alpaca: paper keys in `.env`, and `git check-ignore .env` prints `.env`
- [ ] backtest ran and you read the result against buy-and-hold
- [ ] the bot runs and every trade line says SIMULATED or PAPER
- [ ] `trades.csv` fills up and `summary` works
- [ ] you tried `kill` and `resume` once
- [ ] no real-money keys anywhere

## Safety rules

- Paper mode for at least 2 to 4 weeks. Even then, this project never trades real money.
- Never share API keys or secrets.
- Paper fills look better than real fills: real trading has slippage, fees,
  delays and thin order books.
- Claims like "$100 to $61,873" are unverified and not normal or expected.
- The goal is to learn how a system like this works and to test rules with
  fake money, not to get rich from a bot built in an hour.
