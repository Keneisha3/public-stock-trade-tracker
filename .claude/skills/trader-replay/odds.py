#!/usr/bin/env python3
"""How often has it happened? Base rates for the dip rule's two conditions, from daily history.

    python3 odds.py --out out            # needs Yahoo (the GitHub replay workflow, mode 'odds')

1. The S&P 500 (SPY, since 1993): how often it was 20%+ below its high, and, from a day it was
   4-8% below its high (about where it is now), how often it reached 20% below within 12 and 24 months.
2. Big stocks, today's giants and former giants (Citigroup, AIG, GE, Intel...: so the list is not
   only the winners): from a day the stock was 25-33% below its high, how often it reached 40% below
   within 12 months, and how often that happened while the S&P 500 was also 20%+ below its high
   (the dip rule's buy signal).

Counted over days, so neighbouring days overlap: read the shares as rough odds, not precise ones.
History, not a forecast. Not financial advice.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

YEAR = 252
GIANTS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "BRK-B", "JPM", "LLY", "V", "WMT",
          "ORCL", "XOM", "MA", "NFLX", "COST", "HD", "PG", "JNJ", "UNH", "KO", "BAC", "CSCO", "AMD", "ADBE",
          "CRM", "QCOM", "UBER",
          # former giants, so the list is not only today's survivors
          "INTC", "GE", "C", "AIG", "IBM", "PFE", "WFC", "T", "MO", "F"]


def drawdowns(bars):
    """[(date, fraction below the highest close so far)] (0 at a new high, -0.25 when 25% below)."""
    hi, out = 0.0, []
    for b in bars:
        hi = max(hi, b["c"])
        out.append((b["d"], b["c"] / hi - 1 if hi else 0.0))
    return out


def odds(dd, lo, hi, target, horizon=YEAR, gate=None):
    """From days `lo`..`hi` percent below the high, how often the drop reached `target` (e.g. -0.40) within
    `horizon` days; with `gate` (a date -> bool), only counting a day of the window where gate(date) holds.
    Returns (days, hits). Days without a full window ahead are left out."""
    n = k = 0
    for i in range(len(dd) - horizon):
        if lo <= -100 * dd[i][1] <= hi:
            n += 1
            k += any(x <= target and (gate is None or gate(d)) for d, x in dd[i + 1:i + 1 + horizon])
    return n, k


def bear_starts(dd, level=-0.20, reset=-0.05):
    """First day of each stretch 20%+ below the high (a new stretch only after recovering to within 5%)."""
    out, inside = [], False
    for d, x in dd:
        if x <= level and not inside:
            out.append(d)
            inside = True
        elif x > reset:
            inside = False
    return out


def pct(n, k):
    return "%.0f%%" % (100.0 * k / n) if n else "n/a"


def report(spy_dd, stocks):
    """Markdown. stocks: {ticker: drawdowns}."""
    bear = {d for d, x in spy_dd if x <= -0.20}
    now = spy_dd[-1]
    L = ["# How often has it happened?", "",
         "Daily closes since %s. History, not a forecast. Counted over days, so neighbouring days overlap: "
         "read these as rough odds. Not financial advice." % spy_dd[0][0], "",
         "## The S&P 500 (SPY)", "",
         "- Now (%s): %.1f%% below its high." % (now[0], -100 * now[1]),
         "- Share of days 20%%+ below its high: %s." % pct(len(spy_dd), len(bear)),
         "- Times it fell 20%%+ below its high: %s." % ", ".join(bear_starts(spy_dd)), ""]
    L += ["| from a day 4-8% below its high | days | reached 20% below |", "| --- | ---: | ---: |"]
    for label, h in (("within 12 months", YEAR), ("within 24 months", 2 * YEAR)):
        n, k = odds(spy_dd, 4, 8, -0.20, h)
        L.append("| %s | %d | %s |" % (label, n, pct(n, k)))
    L += ["", "## Big stocks: from a day 25-33% below the stock's high, within 12 months", "",
          "| stock | history from | days | reached 40% below | ...while the S&P 500 was 20%+ below its high | now below its high |",
          "| --- | --- | ---: | ---: | ---: | ---: |"]
    tn = tk = tj = 0
    for t, dd in sorted(stocks.items()):
        n, k = odds(dd, 25, 33, -0.40)
        _, j = odds(dd, 25, 33, -0.40, gate=lambda d: d in bear)
        tn, tk, tj = tn + n, tk + k, tj + j
        L.append("| %s | %s | %d | %s | %s | %.0f%% |" % (t, dd[0][0], n, pct(n, k), pct(n, j), -100 * dd[-1][1]))
    L.append("| **all of them** | | %d | **%s** | **%s** | |" % (tn, pct(tn, tk), pct(tn, tj)))
    L += ["", "_Not financial advice._"]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Base rates for the dip rule's conditions.")
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", help="folder with chart-*.json (tests)")
    ap.add_argument("--tickers", nargs="*", default=GIANTS)
    a = ap.parse_args(argv)
    get = lambda t: mk.get_chart(t, offline=a.offline, range_="max")  # noqa: E731
    spy_dd = drawdowns(get("SPY")["bars"])
    stocks = {}
    for t in a.tickers:
        try:
            stocks[t] = drawdowns(get(t)["bars"])
        except mk.MarketError as e:
            print("skipped %s: %s" % (t, e), file=sys.stderr)
    md = report(spy_dd, stocks)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "odds.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(a.out, "odds.json"), "w", encoding="utf-8") as fh:
        json.dump({"spy_now": spy_dd[-1], "bear_starts": bear_starts(spy_dd)}, fh)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
