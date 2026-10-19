# Daily use

Everything runs on your own computer: your data lives in `trader/` there and
never goes to GitHub.

## One-time setup (about 15 minutes)

```bash
git clone https://github.com/Keneisha3/public-stock-trade-tracker.git
cd public-stock-trade-tracker
python3 .claude/skills/trader-init/init.py
```

1. Edit `trader/accounts.json`: set each account's `"type"` (TFSA, RRSP,
   FHSA or Margin) and your target `"mix"`.
2. Get your holdings in:
   - Questrade: in App Hub, register a personal app (read access) and generate a token, then
     `python3 .claude/skills/trader-accounts/accounts.py sync questrade --token YOUR_TOKEN`
   - Wealthsimple: export the holdings report CSV, then
     `python3 .claude/skills/trader-accounts/accounts.py import wealthsimple holdings.csv`
   - Cash: `accounts.py cash wealthsimple 250` (and the same for questrade, with `--currency USD` for USD cash)
3. Optional: `export SEC_USER_AGENT="Your Name you@example.com"` in your shell
   profile, for SEC filings in the news.

## Make it run by itself

**Mac / Linux:**

```bash
scripts/schedule.sh            # shows what it adds
scripts/schedule.sh --install
```

This adds two scheduled jobs:

- **The daily run, weekdays at 5:30 p.m.:** Questrade sync, prices and dividends,
  the account review, value history, the stock paper bot, news, Congress filings and alerts.
- **The crypto bot team, every 15 minutes:** paper money only.

On a Mac, if nothing runs, give `cron` Full Disk Access (System Settings,
Privacy & Security). Remove the schedule with `scripts/schedule.sh --remove`.

**Windows:** open Task Scheduler and create two basic tasks:

1. Daily, weekdays 5:30 p.m. Program: `python`. Arguments:
   `.claude\skills\trader-daily\daily.py`. Start in: the project folder.
2. Every 15 minutes. Program: `python`. Arguments:
   `.claude\skills\trader-team\team.py run --once`. Start in: the project folder.

## Your 5 minutes a day

1. `python3 app/server.py --open`. The dashboard opens in your browser.
2. Read the **To do** list and the **Proposed trades**. Each one says why.
3. Decide. If you agree with a trade, place it yourself in the Questrade or
   Wealthsimple app. If not, skip it.
4. Glance at news on your holdings, new Congress filings, and the two paper
   bots against buy-and-hold.

**Once a week:** run `team.py summary` and look at the crypto team's losing
trades. Don't change the rules yet.

**Once a month:** put in your contribution. Use **Plan a contribution** on the
dashboard to see where it should go.

**After 2 to 4 weeks:** ask Claude to review the paper bots with the review
prompt in `docs/crypto-bot-team.md`. Test one change at a time.

Not financial advice. Nothing here places a real trade.
