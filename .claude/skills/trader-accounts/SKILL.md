---
name: trader-accounts
description: >-
  Your real accounts. Pulls holdings from Questrade (read-only API, rotating
  refresh token) or a Wealthsimple / any broker holdings CSV, values everything
  in CAD with live USD/CAD, and reviews each account against its own strategy:
  aggressive growth (Questrade, US stocks: momentum, trend, stop from cost,
  trim winners over the cap), medium term (6 to 24 months, trend-following,
  sells broken trends) and steady dividend (Wealthsimple: yield band, dividend
  growth, cut detection, volatility, US withholding in a TFSA, projected
  monthly income). Proposes trims and buys, splits new contributions toward
  your target mix, and records daily value history. Places nothing. Use when
  the user says "review my portfolio", "check my Questrade", "check my
  Wealthsimple", "import my holdings", "where should my next $500 go", "how
  are my accounts doing", "what should I trim", "dividend income", "is my
  growth account too concentrated", or "rebalance my accounts".
argument-hint: "[review | import ACCOUNT FILE | sync | market | --contribute AMOUNT]"
---

# trader-accounts

The account reviewer for the user's real money: one aggressive growth account
(Questrade, US stocks), one steady dividend account (Wealthsimple), and
optionally a medium-term one. Every account is judged by its own strategy's
rules, not one rule for everything.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/accounts.py" market                    # prices, dividends, USD/CAD -> trader/market.json
python3 "${CLAUDE_SKILL_DIR}/accounts.py" review                    # the full review
python3 "${CLAUDE_SKILL_DIR}/accounts.py" review --contribute 500   # where new money goes
python3 "${CLAUDE_SKILL_DIR}/accounts.py" review --account wealthsimple
python3 "${CLAUDE_SKILL_DIR}/accounts.py" import wealthsimple ~/Downloads/holdings-report.csv
python3 "${CLAUDE_SKILL_DIR}/accounts.py" cash wealthsimple 250 --currency CAD
python3 "${CLAUDE_SKILL_DIR}/accounts.py" sync questrade            # read-only API
python3 "${CLAUDE_SKILL_DIR}/accounts.py" snapshot                  # today's value -> trader/history.json
```

If `trader/accounts.json` does not exist, run `/trader-init` first.

## Getting the holdings in

**Questrade (API, read-only).** Questrade web > App Hub > Personal apps >
register a personal app with read access to accounts > Generate new token.
The user runs `accounts.py sync questrade --token TOKEN` themselves, or sets
`QUESTRADE_REFRESH_TOKEN` in their shell. Never ask for the token in chat; if
they paste one, tell them to revoke it in App Hub and make a new one. Each
login rotates the token and the new one is kept in
`trader/state/questrade-<id>.json` (mode 600), so the next sync needs nothing.
If they have several Questrade accounts, put the number in `accounts.json` as
`"questrade_account_number"`. Questrade's API does not place orders for
personal apps, which suits this pack: it only reads.

**Wealthsimple (CSV).** Wealthsimple has no public API. In the web app:
Activity (or Account) > Export / Statements > holdings report, CSV. Then
`accounts.py import wealthsimple FILE`. If the report covers several
accounts, add `--filter "TFSA"` (matches the account name or number). Set the
cash with `accounts.py cash wealthsimple AMOUNT`.

**Any broker.** The importer finds the header row itself and understands the
usual columns (Symbol, Exchange, Quantity, Average Cost or Book Value,
Currency). TSX symbols become Yahoo symbols (`CTC.A` on TSX -> `CTC-A.TO`).

## The three strategies (defaults, all overridable in accounts.json `rules`)

| rule | growth | medium | dividend |
| --- | --- | --- | --- |
| max position % | 20 | 15 | 12 |
| trim when over cap by | 5 pts | 4 pts | 3 pts |
| cash target / max % | 3 / 10 | 3 / 10 | 2 / 8 |
| stop from your cost | -25 % | -20 % | -30 % |
| review when off 52w high | -30 % | -25 % | -25 % |
| other | laggard: 12m < -10 % and below cost | trend broken: under 200-day avg and 6m < 0 | yield 2 to 8 %, no cut over 10 %, 3y dividend growth, vol under 30 % |

Scores (0 to 100) rank holdings inside one account: momentum and trend for
growth and medium, yield sweet spot, dividend growth, no cuts and low
volatility for dividend. They are heuristics on public data, not forecasts.
Say so when you show them.

## How to run a review with the user

1. Make sure the data is fresh: `market` (once a day is enough).
2. Run `review` and read it to the user plainly: the total, today's change,
   the mix against their target, then per account the ACTION lines first,
   then the proposals.
3. For each proposal, explain the reason in one sentence. A trim locks in
   part of a gain and keeps one stock from sinking the account; a buy tops up
   a holding under its target. Never average down into a stock that hit its
   stop: the tool will not propose it, and you should not either.
4. For a stop flag, do not tell them to sell. Ask what changed in the
   company since they bought it, and suggest `/trader-news` and
   `/trader-analyst` on that ticker before they decide.
5. New money: `review --contribute AMOUNT` splits it toward the target mix
   (`"mix"` in accounts.json) and then inside each account.
6. Watchlists: when the tool says cash has nowhere to go, help the user add
   ideas to that account's `"watchlist"` (US growth names for Questrade,
   Canadian dividend payers like banks, pipelines, utilities, telcos for
   Wealthsimple). They get scored like holdings.

Canadian specifics the review already handles, so point them out when they
show up: US dividends in a TFSA lose 15 % to US withholding (an RRSP does
not); converting CAD to USD at the broker costs about 1.5 to 2.5 %, Norbert's
gambit is cheaper for large amounts; frequent trading in a TFSA can make CRA
treat the gains as business income.

## The safety rule

**Not financial advice.** This is arithmetic on delayed public data. Nothing
here places a trade: Questrade's personal API is read-only and Wealthsimple
has no API. The user places every trade themselves in their broker's app,
and only after they say yes to it. Never pressure, never promise returns,
and remind them that a review is a starting point for their own decision.
