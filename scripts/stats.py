#!/usr/bin/env python3
"""How sure can we be? Statistics on many rolling windows from one replay report.

    python3 scripts/stats.py OUT.md report.json     # report made with --rolling-spec 365,91,28

For every strategy: the gap to the S&P 500 in each window, its average, how often it was
positive, and a 90% confidence range from a block bootstrap (windows overlap, so whole
blocks of neighbouring windows are resampled together). Then a reality check: after trying
many strategies, how often would the BEST of them look this good by luck alone? (White's
reality check: every strategy's gaps are centred on zero, the bootstrap is rerun, and we
count how often the best centred average beats the best real one.)
"""

import json
import random
import sys

BENCH = {"S&P 500 (SPY)", "cash"}


def gaps(report):
    t = report["rolling"]["table"]
    spy = [x["return_pct"] for x in t["S&P 500 (SPY)"]["runs"]]
    out = {}
    for k, v in t.items():
        if k in BENCH or k.startswith("mine:"):
            continue
        r = [x["return_pct"] for x in v["runs"]]
        if len(r) == len(spy):
            out[k] = [a - b for a, b in zip(r, spy)]
    return out


def block_means(series, block, runs, rng):
    """Bootstrap means of `series` (dict of equal-length lists), the same blocks for all."""
    n = len(next(iter(series.values())))
    out = {k: [] for k in series}
    for _ in range(runs):
        idx = []
        while len(idx) < n:
            s0 = rng.randrange(0, max(1, n - block + 1))
            idx.extend(range(s0, min(n, s0 + block)))
        idx = idx[:n]
        for k, g in series.items():
            out[k].append(sum(g[i] for i in idx) / n)
    return out


def analyse(report, block=4, runs=5000, seed=11):
    g = gaps(report)
    if not g:
        return None
    rng = random.Random(seed)
    boot = block_means(g, block, runs, rng)
    rows = []
    for k, xs in g.items():
        b = sorted(boot[k])
        rows.append({"strategy": k, "windows": len(xs), "mean_gap": sum(xs) / len(xs),
                     "positive": sum(1 for x in xs if x > 0), "lo90": b[int(0.05 * runs)], "hi90": b[int(0.95 * runs) - 1]})
    rows.sort(key=lambda r: -r["mean_gap"])
    centred = {k: [x - sum(xs) / len(xs) for x in xs] for k, xs in g.items()}
    null = block_means(centred, block, runs, random.Random(seed + 1))
    best = rows[0]["mean_gap"]
    lucky = sum(1 for i in range(runs) if max(null[k][i] for k in null) >= best)
    return {"rows": rows, "best": rows[0]["strategy"], "reality_check_p": lucky / runs, "strategies": len(g),
            "block": block, "runs": runs, "horizon_days": report["rolling"]["horizon_days"],
            "step_days": report["rolling"]["step_days"], "asof": report["asof"]}


def render(a):
    L = ["# How sure can we be? %d rolling %d-day windows (a new one every %d days) to %s" % (
        a["rows"][0]["windows"], a["horizon_days"], a["step_days"], a["asof"]), "",
         "Gap to the S&P 500 per window. The range is a 90%% block-bootstrap confidence range of the average "
         "(blocks of %d neighbouring windows, %d resamples). A range above zero is evidence of a real edge." % (
             a["block"], a["runs"]), "",
         "| strategy | windows | average gap | 90% range | gap above zero |", "| --- | ---: | ---: | --- | ---: |"]
    for r in a["rows"]:
        L.append("| %s | %d | %+.1f pts | %+.1f to %+.1f | %d of %d |" % (
            r["strategy"], r["windows"], r["mean_gap"], r["lo90"], r["hi90"], r["positive"], r["windows"]))
    L += ["", "**Reality check:** with %d strategies compared, the best one (%s, %+.1f pts) would look at least "
          "this good by luck alone in %.0f%% of bootstrap runs%s." % (
              a["strategies"], a["best"], a["rows"][0]["mean_gap"], 100 * a["reality_check_p"],
              " (under 10%: probably a real edge)" if a["reality_check_p"] < 0.1 else
              " (10% or more: it could easily be luck)"), "",
          "_Windows overlap and come from one stretch of market history; not financial advice._"]
    return "\n".join(L) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[1], encoding="utf-8") as fh:
        a = analyse(json.load(fh))
    text = render(a) if a else "No rolling windows in that report.\n"
    with open(argv[0], "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
