---
name: trader-discover
description: >-
  Where stock ideas come from, saved every day so they can be tested later:
  every US-listed common stock (Nasdaq Trader directory), every TSX and TSX
  Venture company, every SEC filer, Russell 2000 / S&P 400 / S&P 600 fund
  holdings, plus idea lists: Yahoo Finance trending and screens (most active,
  gainers, undervalued growth...), tickers named in market news, companies on
  Motley Fool's public news pages, and Reddit / WallStreetBets mention counts.
  Ranks the ideas (liquid, above the 200-day average, 12-1 month momentum).
  Use when the user says "find new stocks", "what's trending", "what is Reddit
  buying", "what's in the news", "Motley Fool picks", "scan the whole market",
  "meme stocks", or "give me ideas".
argument-hint: "[snapshot | funnel [--deep] | show]"
---

# trader-discover

```bash
python3 trade.py discover snapshot            # every source, saved to trader/discover/archive/<date>.json.gz
python3 trade.py discover snapshot --only news,reddit
python3 trade.py discover funnel              # rank today's idea lists
python3 trade.py discover funnel --deep       # rank the whole market (thousands of charts: slow)
python3 trade.py discover show
```

The daily run takes a snapshot of the idea lists and shows the top 15 in the
briefing and on the dashboard. The GitHub workflow's `discover` mode archives
every source, the whole market included, to the `replay-results` branch each
weekday, so history builds up even when your computer is off.

## Say this plainly

- A list fetched today cannot be backtested: it says nothing about last year.
  The archive is what makes it testable later. After a few months, the replay
  can check, point in time, whether being in the news, on Reddit or on the
  Fool's pages predicted anything. Until then these are leads to research.
- Meme stocks and trending lists are where hype lives. Momentum and liquidity
  filters cut the worst of it, but a trending stock can drop 50 % in a week.
- Motley Fool's paid picks are not touched; only names on their public pages.
- Sources change their pages and APIs; a source that fails is reported and
  the others carry on.

**Not financial advice.**
