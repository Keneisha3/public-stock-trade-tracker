#!/usr/bin/env python3
"""Tune the dip rule (rule v19): which cutoffs for "a giant on sale" held up?

    python3 tune.py --out DIR [--offline DIR]     # the GitHub replay workflow, mode 'tune-dips'

Who: the 50 most-traded S&P 500 members on each day (size as known then; membership from 2005).
Every 5th trading day, closes up to that day only; entry at the next open; outcome = the 12-month
return minus the S&P 500's bought the same morning. One event per stock per 21 trading days per rule.

Grid: X (stock below its 52-week high) x M (S&P 500 below its all-time high) x T (any, or below its
200-day average): 84 rules. Chosen on 2006-2018 only, by the average of per-year averages (100+
events in 3+ years); then 2019 on (the 2020 and 2022 bear markets) is reported once. The chosen rule is
written to dip_rule.json with its verdict; picks.py and the daily briefing read that file.
Trying 84 rules and keeping the best flatters the training number: only the held-out one counts.
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

STEP, GAP, YEAR = 5, 21, 252
TRAIN = ("2006-01-01", "2019-01-01")
HELD = ("2019-01-01", "2099-01-01")
XS = (20, 25, 30, 35, 40, 45, 50)
MS = (0, 10, 15, 20, 25, 30)
TS = ("any", "below200")
V18 = {"stock_off": 40, "market_off": 20, "trend": "any"}
MIN_EVENTS, MIN_YEARS, MIN_HELD = 100, 3, 30


def spy_drawdown(spy):
    """{day: % below the S&P 500's highest close so far}."""
    out, hi = {}, 0.0
    for b in spy["bars"]:
        hi = max(hi, b["c"])
        out[b["d"]] = 100.0 * (b["c"] / hi - 1) if hi else 0.0
    return out


def samples(chart, spy, dd, member, first="2006-01-01"):
    """[(day, % below 52-week high, below its 200-day, 12-month excess % or None, dollar volume,
    S&P 500 % below its high)] every STEP-th member day. Reads closes up to the day only."""
    bars = chart["bars"]
    closes, opens, dates = [b["c"] for b in bars], [b["o"] for b in bars], [b["d"] for b in bars]
    sb = spy["bars"]
    sidx = {b["d"]: i for i, b in enumerate(sb)}
    out = []
    for i in range(YEAR, len(bars) - 1, STEP):
        d = dates[i]
        if d < first or not member(d) or dates[i + 1] not in sidx or not opens[i + 1] or not closes[i]:
            continue
        j = sidx[dates[i + 1]]
        off = 100.0 * (closes[i] / max(closes[i - YEAR + 1:i + 1]) - 1)
        below = closes[i] < sum(closes[i - 199:i + 1]) / 200.0
        ex = None
        n = YEAR - 1
        if i + 1 + n < len(bars) and j + n < len(sb) and sb[j]["o"]:
            ex = round(100.0 * ((closes[i + 1 + n] / opens[i + 1] - 1) - (sb[j + n]["c"] / sb[j]["o"] - 1)), 2)
        vols = [b.get("v") or 0 for b in bars[i - 59:i + 1]]
        dv = sum(c * v for c, v in zip(closes[i - 59:i + 1], vols)) / 60.0
        out.append((d, round(off, 2), below, ex, dv, round(dd.get(d, 0.0), 2)))
    return out


def giants(by_stock, n=50):
    """{ticker: [samples]} keeping only the samples that were among the n most-traded on their day."""
    day = {}
    for t, rows in by_stock.items():
        for r in rows:
            day.setdefault(r[0], []).append(r[4])
    cut = {d: sorted(v, reverse=True)[min(n, len(v)) - 1] for d, v in day.items()}
    return {t: [r for r in rows if r[4] >= cut[r[0]]] for t, rows in by_stock.items()}


def fires(r, rule):
    return (r[1] <= -rule["stock_off"] and r[5] <= -rule["market_off"]
            and (rule["trend"] == "any" or r[2]))


def evaluate(by_stock, rule, span):
    """{"n", "mean", "years", "score" (average of per-year averages), "beat" (% of events)} for the rule's
    events with a known 12-month outcome inside `span`."""
    ex, per = [], {}
    for rows in by_stock.values():
        last = None
        for k, r in enumerate(rows):
            if not (span[0] <= r[0] < span[1]) or not fires(r, rule):
                continue
            if last is not None and k - last < GAP // STEP:
                continue
            last = k
            if r[3] is None:
                continue
            ex.append(r[3])
            per.setdefault(r[0][:4], []).append(r[3])
    if not ex:
        return {"n": 0, "mean": None, "years": 0, "score": None, "beat": None}
    return {"n": len(ex), "mean": round(statistics.mean(ex), 2), "years": len(per),
            "score": round(statistics.mean(statistics.mean(v) for v in per.values()), 2),
            "beat": round(100.0 * sum(x > 0 for x in ex) / len(ex))}


def baseline(by_stock, market_off, span):
    """Every giant-day with an outcome in `span` on days the S&P 500 was market_off% or more below its high."""
    ex = [r[3] for rows in by_stock.values() for r in rows
          if span[0] <= r[0] < span[1] and r[3] is not None and r[5] <= -market_off]
    return round(statistics.mean(ex), 2) if ex else None


def grid():
    return [{"stock_off": x, "market_off": m, "trend": t} for x in XS for m in MS for t in TS]


def choose(results):
    """The rule picked on training numbers only (rule v19)."""
    ok = [r for r in results if r["train"]["n"] >= MIN_EVENTS and r["train"]["years"] >= MIN_YEARS]
    if not ok:
        return None
    return max(ok, key=lambda r: (r["train"]["score"], -r["rule"]["market_off"], r["rule"]["stock_off"]))


def verdict(held, base):
    if held["n"] < MIN_HELD:
        return "not enough evidence"
    return "buy" if held["mean"] >= 2 and held["mean"] > (base if base is not None else 0) else "info"


def tune(by_stock):
    g = giants(by_stock)
    results = [{"rule": rule, "train": evaluate(g, rule, TRAIN)} for rule in grid()]
    best = choose(results)
    out = {"results": results, "chosen": None}
    if best:
        held = evaluate(g, best["rule"], HELD)
        base = baseline(g, best["rule"]["market_off"], HELD)
        out["chosen"] = dict(best["rule"], train=best["train"], held_out=held, held_out_baseline=base,
                             verdict=verdict(held, base))
    v18h = evaluate(g, V18, HELD)
    out["v18"] = dict(V18, held_out=v18h, held_out_baseline=baseline(g, 20, HELD),
                      verdict=verdict(v18h, baseline(g, 20, HELD)))
    return out


def describe(rule):
    s = "%d%%+ below its 52-week high" % rule["stock_off"]
    if rule["trend"] == "below200":
        s += " and below its 200-day average"
    if rule["market_off"]:
        s += ", on a day the S&P 500 is %d%%+ below its high" % rule["market_off"]
    return s


def render(out):
    L = ["# Tuning the dip rule (rule v19)", "",
         "The 50 most-traded S&P 500 companies on each day. Chosen on 2006-2018, checked once on 2019 on. "
         "Numbers: the next 12 months against the S&P 500, in points.", ""]
    c = out["chosen"]
    if c:
        L += ["**Chosen on training years:** %s." % describe(c), "",
              "| | events | vs S&P 500 (12 months) | beat it | baseline |", "| --- | ---: | ---: | ---: | ---: |",
              "| training 2006-2018 | %d | %+.2f (per-year average %+.2f) | %s%% | |" % (
                  c["train"]["n"], c["train"]["mean"], c["train"]["score"], c["train"]["beat"]),
              "| held out 2019 on | %d | %s | %s | %s |" % (
                  c["held_out"]["n"], "%+.2f" % c["held_out"]["mean"] if c["held_out"]["mean"] is not None else "n/a",
                  "%s%%" % c["held_out"]["beat"] if c["held_out"]["beat"] is not None else "n/a",
                  "%+.2f" % c["held_out_baseline"] if c["held_out_baseline"] is not None else "n/a"),
              "", "**Verdict: %s.**" % c["verdict"], ""]
    v = out["v18"]
    L += ["For comparison, rule v18 (%s) on the held-out years: %d events, %s (baseline %s): %s." % (
        describe(v), v["held_out"]["n"],
        "%+.2f" % v["held_out"]["mean"] if v["held_out"]["mean"] is not None else "n/a",
        "%+.2f" % v["held_out_baseline"] if v["held_out_baseline"] is not None else "n/a", v["verdict"]), "",
        "## Every rule on the training years (ranked)", "",
        "| stock below its high | S&P 500 below its high | trend | events | years | per-year average | average | beat it |",
        "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in sorted(out["results"], key=lambda r: -(r["train"]["score"] if r["train"]["score"] is not None else -1e9)):
        t, u = r["train"], r["rule"]
        L.append("| %d%% | %s | %s | %d | %d | %s | %s | %s |" % (
            u["stock_off"], "%d%%" % u["market_off"] if u["market_off"] else "any", u["trend"], t["n"], t["years"],
            "%+.2f" % t["score"] if t["score"] is not None else "n/a",
            "%+.2f" % t["mean"] if t["mean"] is not None else "n/a", "%s%%" % t["beat"] if t["beat"] is not None else "n/a"))
    L += ["", "Trying 84 rules and keeping the best flatters its training number; only the held-out row counts. "
          "Companies that vanished from Yahoo have no prices, which flatters dip-buying.", "", "_Not financial advice._"]
    return "\n".join(L) + "\n"


def rule_file(out):
    """What dip_rule.json holds: the chosen rule if it earned "buy", else v18 marked as the fallback."""
    c = out["chosen"]
    if c and c["verdict"] == "buy":
        return {"stock_off": c["stock_off"], "market_off": c["market_off"], "trend": c["trend"],
                "source": "rule v19 (tuned)", "verdict": "buy", "held_out": c["held_out"]}
    return dict(V18, source="rule v18 (the tuned rule did not pass: %s)" % (c["verdict"] if c else "none chosen"),
                verdict="info", held_out=out["v18"]["held_out"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tune the dip rule on 2006-2018, check it on 2019 on.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--members", help="membership CSV (tests); default: rebuilt from the source since 2005")
    a = ap.parse_args(argv)
    get = lambda t: mk.get_chart(t, offline=a.offline, range_="max")  # noqa: E731
    if a.members:
        with open(a.members, encoding="utf-8") as fh:
            uni = univ.Universe(univ.build(fh.read(), since="2005-01-01"))
    else:
        uni = univ.Universe(univ.build(mk.fetch(univ.SOURCE), since="2005-01-01"))
    spy = get("SPY")
    dd = spy_drawdown(spy)
    by = {}
    for t in sorted(uni.ever("2005-01-01", "2099-01-01")):
        try:
            ch = get(t)
        except mk.MarketError:
            continue
        by[t] = samples(ch, spy, dd, lambda d, t=t: t in uni.members_on(d))
    out = tune(by)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "tune.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(a.out, "dip_rule.json"), "w", encoding="utf-8") as fh:
        json.dump(rule_file(out), fh, indent=1)
    text = render(out)
    with open(os.path.join(a.out, "tune.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
