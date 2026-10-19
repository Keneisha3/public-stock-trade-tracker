#!/usr/bin/env python3
"""Combine replay reports from several as-of dates into a walk-forward table with a
held-out test.

    python3 scripts/walkforward.py OUT.md report-2019-10-18.json ... report-2026-10-16.json

Training and test never mix:

  training   the longest window (24 months) of every period that ENDS at least 12 months
             before the latest as-of date. Settings are chosen here and only here.
  test       the last 12 months, 6 months and 1 month before the latest as-of date (from
             the latest report). Nothing is chosen on them; they show how the choices did.

The latest period's 24-month window straddles both, so it is used for neither.
Each new run moves the line: the most recent 12 months are always the test.
"""

import datetime
import json
import sys

KEYS = ["growth", "medium", "dividend", "stock bot", "momentum", "dual momentum", "insider buys", "congress buys",
        "blend", "core + dual", "VIX agent"]
BENCH = ["S&P 500 (SPY)", "Nasdaq 100 (QQQ)", "S&P 500 equal weight (RSP)", "TSX 60 (XIU.TO)"]
NAMES = {"growth": "Growth (Questrade)", "medium": "Medium term", "dividend": "Dividend (Wealthsimple)",
         "stock bot": "Stock bot", "VIX agent": "VIX agent", "momentum": "Momentum (top 20 S&P 500)",
         "dual momentum": "Dual momentum (funds)", "insider buys": "Insider buying", "congress buys": "Congress buying",
         "blend": "Blend (dual + momentum + Congress)", "core + dual": "Half Nasdaq 100, half dual momentum"}
TEST_WINDOWS = ["12 months", "6 months", "1 month"]
HOLDOUT_DAYS = 365


def pct(x):
    return "n/a" if x is None else "%+.1f%%" % x


def split(reports):
    """(training reports, latest report, the day the held-out test starts)."""
    reports = sorted(reports, key=lambda r: r["asof"])
    last = reports[-1]
    cut = (datetime.date.fromisoformat(last["asof"]) - datetime.timedelta(days=HOLDOUT_DAYS)).isoformat()
    return [r for r in reports if r["asof"] <= cut], last, cut


def _ret(r, win, k):
    return ((r["results"].get(win) or {}).get(k) or {}).get("return_pct")


def table(reports):
    reports = sorted(reports, key=lambda r: r["asof"])
    win = reports[0]["windows"][0]
    train, last, cut = split(reports)
    L = ["# Walk-forward with a held-out test", "",
         "Chosen only from what was in the S&P 500 each day (plus index funds and a Canadian list). "
         "**Training:** %s windows ending %s. **Test (never used to choose anything):** the last %s before %s, "
         "all after %s." % (win, ", ".join(r["asof"] for r in train) or "none", ", ".join(TEST_WINDOWS), last["asof"], cut),
         "", "## Training periods (gap to the S&P 500 in brackets)", "",
         "| strategy | " + " | ".join(r["asof"] for r in train) + " | beat S&P 500 | average gap |",
         "| --- |" + " ---: |" * (len(train) + 2)]
    for k in KEYS + BENCH:
        cells, gaps = [], []
        for r in train:
            x, spy = _ret(r, win, k), _ret(r, win, "S&P 500 (SPY)")
            if x is None:
                cells.append("n/a")
                continue
            gap = None if spy is None or k == "S&P 500 (SPY)" else x - spy
            if gap is not None:
                gaps.append(gap)
            cells.append(pct(x) + ("" if gap is None else " (%+.1f)" % gap))
        if all(c == "n/a" for c in cells):
            continue
        L.append("| %s | %s | %s | %s |" % (NAMES.get(k, k), " | ".join(cells),
                                            "–" if k == "S&P 500 (SPY)" else "%d of %d" % (sum(g > 0 for g in gaps), len(gaps)),
                                            "–" if not gaps else "%+.1f pts" % (sum(gaps) / len(gaps))))
    tw = [w for w in TEST_WINDOWS if w in last["results"]]
    L += ["", "## Held-out test: the last %s to %s (gap to the S&P 500 in brackets)" % (", ".join(tw), last["asof"]), "",
          "| strategy | " + " | ".join(tw) + " |", "| --- |" + " ---: |" * len(tw)]
    for k in KEYS + BENCH:
        cells = []
        for w in tw:
            x, spy = _ret(last, w, k), _ret(last, w, "S&P 500 (SPY)")
            cells.append("n/a" if x is None else pct(x) + ("" if spy is None or k == "S&P 500 (SPY)" else " (%+.1f)" % (x - spy)))
        if any(c != "n/a" for c in cells):
            L.append("| %s | %s |" % (NAMES.get(k, k), " | ".join(cells)))
    L += ["", "The %s window ending %s is half training, half test, so it is used for neither (see report-%s.md)." % (
        win, last["asof"], last["asof"])]
    L += ["", "## Rolling 3-month windows inside each period (beat the S&P 500 / windows)", "",
          "| strategy | " + " | ".join(r["asof"] for r in reports) + " |", "| --- |" + " ---: |" * len(reports)]
    for k in KEYS:
        cells = []
        for r in reports:
            t = ((r.get("rolling") or {}).get("table") or {}).get(k)
            cells.append("%s of %s" % (t["beat_spy"], t["windows"]) if t else "n/a")
        if any(c != "n/a" for c in cells):
            L.append("| %s | %s |" % (NAMES[k], " | ".join(cells)))
    L += scenarios(train, last, win)
    L += ["", "## Coverage and self-checks", ""]
    for r in reports:
        cov = r["results"][win].get("coverage") or {}
        bad = [c["name"] for c in r.get("checks", []) if not c["ok"]]
        L.append("- %s: %s of %s index members priced; self-checks %s" % (
            r["asof"], cov.get("priced", "?"), cov.get("members", "?"), "all passed" if not bad else "FAILED: " + ", ".join(bad)))
    L += ["", "_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._"]
    return "\n".join(L) + "\n"


def scenarios(train, last, win):
    """Every setting of every agent: average gap to the S&P 500 over the training periods,
    then its gap in the held-out last 12 months. Choose on the training column only."""
    rows = {}

    def gaps(r, w, slot):
        spy = _ret(r, w, "S&P 500 (SPY)")
        for sc in r.get("scenarios", []):
            res = (sc.get("results") or {}).get(w)
            if res is not None and spy is not None:
                rows.setdefault((sc["strategy"], sc["name"]), {}).setdefault(slot, []).append(res["return_pct"] - spy)
    for r in train:
        gaps(r, win, "train")
    if "12 months" in last["results"]:
        gaps(last, "12 months", "test")
    L = ["", "## Settings: chosen on the training periods, checked on the held-out last 12 months", "",
         "Average gap to the S&P 500. Pick on the training column only; the test column is the check.", "",
         "| agent | setting | training (%s) | test: last 12 months |" % win, "| --- | --- | ---: | ---: |"]

    def avg(xs):
        return sum(xs) / len(xs) if xs else None
    for (st, name), g in sorted(rows.items(), key=lambda kv: (kv[0][0], -(avg(kv[1].get("train", [])) or -1e9))):
        a, b = avg(g.get("train", [])), avg(g.get("test", []))
        L.append("| %s | %s | %s | %s |" % (st, name, "n/a" if a is None else "%+.1f pts" % a,
                                             "n/a" if b is None else "%+.1f pts" % b))
    return L


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reports = []
    for path in argv[1:]:
        with open(path, encoding="utf-8") as fh:
            reports.append(json.load(fh))
    text = table(reports)
    with open(argv[0], "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
