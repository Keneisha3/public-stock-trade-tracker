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


KINDS = {  # name: (signals, which fire, title)
    "sell": (mk.STRETCH_SIGNALS, mk.stretch_signals, "Sell signals: do stretched stocks fall behind?"),
    "dip": (mk.DIP_SIGNALS, mk.dip_signals, "Buying the dip: do beaten-down stocks catch up?"),
}


def events(chart, spy, member, first="2014-01-01", fire=mk.stretch_signals):
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
        fired = [x for x in fire(s) if i - last.get(x, -GAP) >= GAP]
        for x in fired:
            last[x] = i
        ex = []
        for n in (20, 62, 251):  # close of the 21st, 63rd and 252nd trading day after the entry open
            if i + 1 + n >= len(bars) or j + n >= len(sb):
                ex.append(None)  # not a full year of prices after this day yet
                continue
            r = closes[i + 1 + n] / opens[i + 1] - 1
            m = sb[j + n]["c"] / sb[j]["o"] - 1
            ex.append(round(100 * (r - m), 2))
        vols = [b.get("v") or 0 for b in bars[max(0, i - 59):i + 1]]
        dv = sum(c * v for c, v in zip(closes[max(0, i - 59):i + 1], vols)) / len(vols)  # dollars traded a day
        out.append((d, fired, ex[0], ex[1], ex[2], dv))
    return out


def summarize(rows, names=mk.STRETCH_SIGNALS):
    """{period: {signal or "all": {n, ex_1m, ex_3m, beat_3m_pct}}}"""
    out = {}
    for period, keep in (("training 2014-2022", lambda d: d < SPLIT), ("held out 2023 on", lambda d: d >= SPLIT)):
        groups = {"all": [r for r in rows if keep(r[0])]}
        for x in names:
            groups[x] = [r for r in groups["all"] if x in r[1]]
        out[period] = {k: ({"n": len(g), "ex_1m": round(statistics.mean(r[2] for r in g), 2),
                            "ex_3m": round(statistics.mean(r[3] for r in g), 2),
                            "median_3m": round(statistics.median(r[3] for r in g), 2),
                            "beat_3m_pct": round(100.0 * sum(r[3] > 0 for r in g) / len(g), 1)} if g else {"n": 0})
                       for k, g in groups.items()}
    return out


def verdicts(summary, kind="sell"):
    """Rule v15: a signal earns "consider trimming" only if flagged stocks trailed the S&P 500 by 2+
    points over 3 months in training AND trailed the baseline, and the held-out years agree in sign."""
    tr, ho = summary["training 2014-2022"], summary["held out 2023 on"]
    out = {}
    for x in KINDS[kind][0]:
        a, b, base = tr.get(x, {}), ho.get(x, {}), tr["all"]
        enough = a.get("n", 0) >= 30 and b.get("n", 0) >= 10
        if kind == "dip":  # rule v16: flagged stocks beat the S&P 500 by 2+ points and the baseline; held out agrees
            ok = enough and a["ex_3m"] >= 2 and a["ex_3m"] > base.get("ex_3m", 0) and b["ex_3m"] > 0
            out[x] = "buy" if ok else "info"
        else:
            ok = enough and a["ex_3m"] <= -2 and a["ex_3m"] < base.get("ex_3m", 0) and b["ex_3m"] < 0
            out[x] = "trim" if ok else "info"
    return out


CRASHES = (("2008 crash", "2007-10-01", "2009-06-30"), ("2020 crash", "2020-02-15", "2020-06-30"))


def crash_summary(rows, names=mk.DIP_SIGNALS, crashes=CRASHES):
    """Rule v17: each signal inside each crash window, and everything outside them. {period: {signal or
    "all": {n, ex_3m, ex_12m, beat_12m_pct}}} (12-month figures only where a full year followed)."""
    def stats(g):
        if not g:
            return {"n": 0}
        y = [r[4] for r in g if len(r) > 4 and r[4] is not None]
        return {"n": len(g), "ex_3m": round(statistics.mean(r[3] for r in g), 2),
                "ex_12m": round(statistics.mean(y), 2) if y else None,
                "beat_12m_pct": round(100.0 * sum(v > 0 for v in y) / len(y), 1) if y else None}
    inside = lambda d: any(a <= d <= b for _, a, b in crashes)  # noqa: E731
    out = {}
    periods = [(name, (lambda d, a=a, b=b: a <= d <= b)) for name, a, b in crashes] + \
        [("other years", lambda d: not inside(d))]
    for name, keep in periods:
        g = [r for r in rows if keep(r[0])]
        out[name] = {"all": stats(g)}
        out[name].update({x: stats([r for r in g if x in r[1]]) for x in names})
    return out


def crash_verdicts(cs, names=mk.DIP_SIGNALS, crashes=CRASHES):
    """Rule v17: "buy in a crash" only if, in every crash, flagged stocks beat the S&P 500 over 12 months
    by 2+ points on average and beat that crash's baseline."""
    out = {}
    for x in names:
        ok = True
        for name, _, _ in crashes:
            a, base = cs[name].get(x, {}), cs[name]["all"]
            if not a.get("n") or a.get("ex_12m") is None or a["ex_12m"] < 2 or a["ex_12m"] <= (base.get("ex_12m") or 0):
                ok = False
        out[x] = "buy in a crash" if ok else "info"
    return out


def giants(rows, n=50):
    """{(day, dollar volume)} of the rows that were among the `n` most-traded stocks on their day: size
    as it was known then, not today's winners picked with hindsight."""
    by = {}
    for r in rows:
        if len(r) > 5:
            by.setdefault(r[0], []).append(r[5])
    keep = set()
    for d, dvs in by.items():
        for v in sorted(dvs, reverse=True)[:n]:
            keep.add((d, v))
    return keep


def render_crash(cs, verdict, stats, title="# Buying the dip in the 2008 and 2020 crashes"):
    names = mk.DIP_SIGNALS
    L = [title, "",
         "S&P 500 members on their member days since 2006 (membership rebuilt from 2005), checked every %d trading "
         "days; entry at the next open; the gap to the S&P 500 bought the same morning. %d stocks with prices, %d "
         "without. Companies that went to zero in 2008 have no prices, which flatters dip-buying then." % (
             STEP, stats["with_prices"], stats["missing"]), ""]
    for period, rows in cs.items():
        L += ["## " + period, "", "| signal | events | next 3 months vs S&P 500 | next 12 months | beat it (12 months) |",
              "| --- | ---: | ---: | ---: | ---: |"]
        for k in ["all"] + list(names):
            r = rows.get(k) or {}
            name = "every member-day (baseline)" if k == "all" else "%s %s" % (k, names[k])
            f = lambda v: ("%+.2f pts" % v) if v is not None else "-"  # noqa: E731
            L.append("| %s | %d | %s | %s | %s |" % (name, r.get("n", 0), f(r.get("ex_3m")), f(r.get("ex_12m")),
                                                    ("%.0f%%" % r["beat_12m_pct"]) if r.get("beat_12m_pct") is not None
                                                    else "-"))
        L.append("")
    L.append("**Rule v17 verdicts:** " + ", ".join("%s %s" % (k, v) for k, v in verdict.items()) +
             " (buy in a crash: beat the S&P 500 by 2+ points over 12 months, and the crash's baseline, in both "
             "crashes).")
    L += ["", "_Not financial advice._"]
    return "\n".join(L) + "\n"


def index_dips(spy, levels=(5, 10, 20), horizons=((63, "3 months"), (252, "12 months"))):
    """The S&P 500 itself: average return over each horizon after days it closed `level`% or more
    below its high so far (bought at the next open), beside any day. {label: {horizon: (n, avg %)}}."""
    bars = spy["bars"]
    out = {"any day": {}}
    hi = 0.0
    flags = []
    for i, b in enumerate(bars):
        hi = max(hi, b["c"])
        flags.append(100.0 * (b["c"] / hi - 1))
    for level in (None,) + tuple(levels):
        label = "any day" if level is None else "%d%%+ below its high" % level
        res = {}
        for n, name in horizons:
            rs = [100.0 * (bars[i + 1 + n]["c"] / bars[i + 1]["o"] - 1) for i in range(len(bars) - n - 2)
                  if bars[i + 1]["o"] and (level is None or flags[i] <= -level)]
            res[name] = (len(rs), round(statistics.mean(rs), 2) if rs else None)
        out[label] = res
    return out


def render(summary, verdict, stats, kind="sell", index=None):
    names = KINDS[kind][0]
    L = ["# " + KINDS[kind][2], "",
         "Every S&P 500 member on its member days since 2014, checked every %d trading days; entry at the next "
         "open; the gap to the S&P 500 bought the same morning. %d stocks with prices, %d without (survivorship)."
         % (STEP, stats["with_prices"], stats["missing"]), ""]
    for period, rows in summary.items():
        L += ["## " + period, "", "| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for k in ["all"] + list(names):
            r = rows.get(k) or {}
            name = "every member-day (baseline)" if k == "all" else "%s %s" % (k, names[k])
            L.append("| %s | %d | %s | %s | %s | %s |" % (name, r.get("n", 0), *(
                ("%+.2f pts" % r[f]) if r.get("n") else "-" for f in ("ex_1m", "ex_3m", "median_3m")),
                ("%.0f%%" % r["beat_3m_pct"]) if r.get("n") else "-"))
        L.append("")
    if kind == "dip":
        L.append("**Rule v16 verdicts:** " + ", ".join("%s %s" % (k, v) for k, v in verdict.items()) +
                 " (buy: flagged stocks beat the S&P 500 by 2+ points over 3 months in training, beat the baseline, "
                 "and beat it in the held-out years too; info: no edge shown).")
    else:
        L.append("**Rule v15 verdicts:** " + ", ".join("%s %s" % (k, v) for k, v in verdict.items()) +
                 " (trim: flagged stocks trailed by 2+ points in training and the held-out years agree; info: shown "
                 "as risk only, never as a sell).")
    if index:
        L += ["", "## The S&P 500 itself (SPY since %s): buying on a dip vs any day" % index.get("first", "1993"), "",
              "| bought when | next 3 months | next 12 months |", "| --- | ---: | ---: |"]
        for label, res in index.items():
            if label == "first":
                continue
            L.append("| %s | %s | %s |" % (label, *("%+.1f%% (n=%d)" % (v[1], v[0]) if v[1] is not None else "-"
                                                  for v in (res["3 months"], res["12 months"]))))
    L += ["", "_Not financial advice._"]
    return "\n".join(L) + "\n"


def run(get, uni, log=print, kind="sell"):
    spy = get("SPY")
    rows, stats = [], {"with_prices": 0, "missing": 0}
    for t in sorted(uni.ever("2014-01-01", "2099-01-01")):
        try:
            ch = get(t)
        except mk.MarketError:
            stats["missing"] += 1
            continue
        stats["with_prices"] += 1
        rows += events(ch, spy, lambda d, t=t: t in uni.members_on(d), fire=KINDS[kind][1])
    s = summarize(rows, KINDS[kind][0])
    return s, verdicts(s, kind), stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Test the stretch (sell) signals on the S&P 500 since 2014.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--kind", choices=sorted(KINDS), default="sell")
    ap.add_argument("--crashes", action="store_true", help="dip signals in the 2008 and 2020 crashes (rule v17)")
    a = ap.parse_args(argv)
    get = lambda t: mk.get_chart(t, offline=a.offline, range_="max")  # noqa: E731
    if a.crashes:  # membership from 2005, rebuilt from the source (the bundled file starts in 2014)
        uni = univ.Universe(univ.build(mk.fetch(univ.SOURCE), since="2005-01-01"))
        spy, rows, stats = get("SPY"), [], {"with_prices": 0, "missing": 0}
        for t in sorted(uni.ever("2005-01-01", "2099-01-01")):
            try:
                ch = get(t)
            except mk.MarketError:
                stats["missing"] += 1
                continue
            stats["with_prices"] += 1
            rows += events(ch, spy, lambda d, t=t: t in uni.members_on(d), first="2006-01-01", fire=mk.dip_signals)
        cs = crash_summary(rows)
        v = crash_verdicts(cs)
        top = giants(rows)
        gs = crash_summary([r for r in rows if (r[0], r[5]) in top])
        gv = crash_verdicts(gs)
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "crashes.json"), "w", encoding="utf-8") as fh:
            json.dump({"summary": cs, "verdicts": v, "giants": gs, "giants_verdicts": gv, "stats": stats}, fh, indent=1)
        text = render_crash(cs, v, stats) + "\n" + render_crash(gs, gv, stats, title=(
            "# The giants only: the 50 most-traded S&P 500 companies on each day"))
        with open(os.path.join(a.out, "crashes.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        print(text)
        return 0
    s, v, stats = run(get, univ.load(), kind=a.kind)
    index = None
    if a.kind == "dip":
        spy = get("SPY")
        index = dict(index_dips(spy), first=spy["bars"][0]["d"][:4])
    name = "stretch" if a.kind == "sell" else "dips"
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": s, "verdicts": v, "stats": stats, "index": index}, fh, indent=1)
    text = render(s, v, stats, a.kind, index)
    with open(os.path.join(a.out, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
