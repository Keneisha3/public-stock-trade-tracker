#!/usr/bin/env python3
"""What the US government has bought stakes in, and whether buying after the news paid.

    python3 govstakes.py              # the list and each stock since the news (prices: Yahoo, or the
                                      # GitHub copy where Yahoo is blocked)
    python3 govstakes.py --offline DIR

Point in time: each stock is bought at the first open AFTER the day the news was first public (a
deal announced before the bell still counts from the next day: the conservative choice), and
compared with the S&P 500 bought the same morning. A second line waits 5 trading days, after the
first jump. Five deals is far too few to call this a strategy: it shows what happened, nothing more.
Not financial advice.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

LIST = os.path.join(HERE, "gov_stakes.json")
HORIZONS = (("1 month", 21), ("3 months", 63), ("6 months", 126), ("12 months", 252))


def load(path=LIST):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def event(stock, spy, day, wait=0):
    """Returns from the open of the first trading day after `day` (+ `wait` trading days) to each
    horizon's close, for the stock and SPY: {"entry": date, "since_pct", "spy_since_pct", horizon: (stock %, spy %)}."""
    bars = [b for b in stock["bars"] if b["d"] > day]
    if len(bars) <= wait:
        return None
    entry = bars[wait]
    sbars = {b["d"]: b for b in spy["bars"]}
    if entry["d"] not in sbars or not entry["o"]:
        return None
    s0, after = sbars[entry["d"]]["o"], [b for b in bars if b["d"] >= entry["d"]]
    spy_after = [b for b in spy["bars"] if b["d"] >= entry["d"]]
    out = {"entry": entry["d"], "entry_price": round(entry["o"], 2),
           "since_pct": round(100 * (after[-1]["c"] / entry["o"] - 1), 1),
           "spy_since_pct": round(100 * (spy_after[-1]["c"] / s0 - 1), 1)}
    for name, n in HORIZONS:
        if len(after) > n and len(spy_after) > n:
            out[name] = (round(100 * (after[n]["c"] / entry["o"] - 1), 1), round(100 * (spy_after[n]["c"] / s0 - 1), 1))
    jump = [b for b in stock["bars"] if b["d"] < day]
    if jump:
        out["jump_pct"] = round(100 * (entry["o"] / jump[-1]["c"] - 1), 1)  # what the news already moved it
    return out


def study(doc, get):
    spy = get("SPY")
    rows = []
    for s in doc["stakes"]:
        try:
            ch = get(s["ticker"])
        except mk.MarketError as e:
            rows.append(dict(s, error=str(e)))
            continue
        rows.append(dict(s, now=round(ch["price"], 2), mirror=bool(ch.get("mirror")),
                         at_news=event(ch, spy, s["first_public"]), week_later=event(ch, spy, s["first_public"], 5)))
    return rows


def render(rows):
    L = ["US government stakes: bought at the next open after the news, against the S&P 500 bought the same morning", ""]
    for r in rows:
        if r.get("error"):
            L.append("%-5s %s: no prices (%s)" % (r["ticker"], r["company"], r["error"]))
            continue
        a, w = r["at_news"] or {}, r["week_later"] or {}
        L.append("%-5s %-18s %s %s (%s), news %s" % (r["ticker"], r["company"], r["agency"], r["stake"], r["theme"],
                                                     r["first_public"]))
        if a:
            L.append("      next open %s at %s (already %+.1f%% from the close before the news); since: %+.1f%% vs S&P %+.1f%%"
                     % (a["entry"], a["entry_price"], a.get("jump_pct", 0), a["since_pct"], a["spy_since_pct"]))
            L.append("      " + ", ".join("%s %+.0f%% (S&P %+.0f%%)" % (n, a[n][0], a[n][1]) for n, _ in HORIZONS if n in a))
        if w:
            L.append("      a week later: since %+.1f%% vs S&P %+.1f%%" % (w["since_pct"], w["spy_since_pct"]))
    beat = [r for r in rows if r.get("at_news") and r["at_news"]["since_pct"] > r["at_news"]["spy_since_pct"]]
    got = [r for r in rows if r.get("at_news")]
    if got:
        L += ["", "%d of %d beat the S&P 500 since the news. Five deals are too few to call it an edge, the stocks "
              "swing hard, and the government can sell too. Not financial advice." % (len(beat), len(got))]
    if any(r.get("mirror") for r in rows):
        L.append("(Prices from the GitHub copy: Yahoo is blocked here. Its last bar is the date shown.)")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="US government stakes and how buying after the news did.")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = study(load(), lambda t: mk.get_chart(t, offline=a.offline, range_="2y"))
    print(json.dumps(rows, indent=1) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
