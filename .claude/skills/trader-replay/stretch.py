#!/usr/bin/env python3
"""Do "sell when it gets really high, or when volatility rises on the way up" signals work?

    python3 stretch.py --out DIR [--offline DIR]

Every S&P 500 member on the days it was a member (2014 on), checked every 5th trading day with
market.stretch() on closes up to that day only; a signal (market.STRETCH_SIGNALS, at most one event
per stock per month) is followed from the NEXT open for 1 and 3 months against the S&P 500 bought the
same morning. The baseline is every member-day checked. Training 2014-2022, held out 2023 on (rule v15).
Companies that left the index and vanished from Yahoo are missing (survivorship): the flagged stocks
that later collapsed are the likeliest to be missing, which makes "keep holding" look better than it was.
Not financial advice.
"""

import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
sys.path.insert(0, HERE)
import market as mk  # noqa: E402
import universe as univ  # noqa: E402

SPLIT = "2023-01-01"
STEP, GAP = 5, 21


def events(chart, spy, member, first="2014-01-01"):
    """[(day, signals, excess 1m %, excess 3m %)] for one stock: every STEP-th day it was a member,
    with the signals that fired (deduplicated per signal to one per GAP days)."""
    bars = chart["bars"]
    closes, opens, dates = [b["c"] for b in bars], [b["o"] for b in bars], [b["d"] for b in bars]
    sidx = {b["d"]: i for i, b in enumerate(spy["bars"])}
    sb = spy["bars"]
    last, out = {}, []
    for i in range(252, len(bars) - 64, STEP):
        d = dates[i]
        if d < first or not member(d) or dates[i + 1] not in sidx or not opens[i + 1]:
            continue
        j = sidx[dates[i + 1]]
        if j + 62 >= len(sb) or not sb[j]["o"]:
            continue
        s = mk.stretch(closes[max(0, i - 260):i + 1])
        fired = [x for x in mk.stretch_signals(s) if i - last.get(x, -GAP) >= GAP]
        for x in fired:
            last[x] = i
        ex = []
        for n in (20, 62):  # close of the 21st and 63rd trading day after the entry open
            r = closes[i + 1 + n] / opens[i + 1] - 1
            m = sb[j + n]["c"] / sb[j]["o"] - 1
            ex.append(round(100 * (r - m), 2))
        out.append((d, fired, ex[0], ex[1]))
    return out


def summarize(rows):
    """{period: {signal or "all": {n, ex_1m, ex_3m, beat_3m_pct}}}"""
    out = {}
    for period, keep in (("training 2014-2022", lambda d: d < SPLIT), ("held out 2023 on", lambda d: d >= SPLIT)):
        groups = {"all": [r for r in rows if keep(r[0])]}
        for x in mk.STRETCH_SIGNALS:
            groups[x] = [r for r in groups["all"] if x in r[1]]
        out[period] = {k: ({"n": len(g), "ex_1m": round(statistics.mean(r[2] for r in g), 2),
                            "ex_3m": round(statistics.mean(r[3] for r in g), 2),
                            "median_3m": round(statistics.median(r[3] for r in g), 2),
                            "beat_3m_pct": round(100.0 * sum(r[3] > 0 for r in g) / len(g), 1)} if g else {"n": 0})
                       for k, g in groups.items()}
    return out


def verdicts(summary):
    """Rule v15: a signal earns "consider trimming" only if flagged stocks trailed the S&P 500 by 2+
    points over 3 months in training AND trailed the baseline, and the held-out years agree in sign."""
    tr, ho = summary["training 2014-2022"], summary["held out 2023 on"]
    out = {}
    for x in mk.STRETCH_SIGNALS:
        a, b, base = tr.get(x, {}), ho.get(x, {}), tr["all"]
        ok = (a.get("n", 0) >= 30 and b.get("n", 0) >= 10 and a["ex_3m"] <= -2 and a["ex_3m"] < base.get("ex_3m", 0)
              and b["ex_3m"] < 0)
        out[x] = "trim" if ok else "info"
    return out


def render(summary, verdict, stats):
    L = ["# Sell signals: do stretched stocks fall behind?", "",
         "Every S&P 500 member on its member days since 2014, checked every %d trading days; entry at the next "
         "open; the gap to the S&P 500 bought the same morning. %d stocks with prices, %d without (survivorship)."
         % (STEP, stats["with_prices"], stats["missing"]), ""]
    for period, rows in summary.items():
        L += ["## " + period, "", "| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for k in ["all"] + list(mk.STRETCH_SIGNALS):
            r = rows.get(k) or {}
            name = "every member-day (baseline)" if k == "all" else "%s %s" % (k, mk.STRETCH_SIGNALS[k])
            L.append("| %s | %d | %s | %s | %s | %s |" % (name, r.get("n", 0), *(
                ("%+.2f pts" % r[f]) if r.get("n") else "-" for f in ("ex_1m", "ex_3m", "median_3m")),
                ("%.0f%%" % r["beat_3m_pct"]) if r.get("n") else "-"))
        L.append("")
    L.append("**Rule v15 verdicts:** " + ", ".join("%s %s" % (k, v) for k, v in verdict.items()) +
             " (trim: flagged stocks trailed by 2+ points in training and the held-out years agree; info: shown "
             "as risk only, never as a sell).")
    L += ["", "_Not financial advice._"]
    return "\n".join(L) + "\n"


def run(get, uni, log=print):
    spy = get("SPY")
    rows, stats = [], {"with_prices": 0, "missing": 0}
    for t in sorted(uni.ever("2014-01-01", "2099-01-01")):
        try:
            ch = get(t)
        except mk.MarketError:
            stats["missing"] += 1
            continue
        stats["with_prices"] += 1
        rows += events(ch, spy, lambda d, t=t: t in uni.members_on(d))
    s = summarize(rows)
    return s, verdicts(s), stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Test the stretch (sell) signals on the S&P 500 since 2014.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", metavar="DIR")
    a = ap.parse_args(argv)
    s, v, stats = run(lambda t: mk.get_chart(t, offline=a.offline, range_="max"), univ.load())
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "stretch.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": s, "verdicts": v, "stats": stats}, fh, indent=1)
    text = render(s, v, stats)
    with open(os.path.join(a.out, "stretch.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
