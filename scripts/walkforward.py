#!/usr/bin/env python3
"""Combine replay reports from several as-of dates into one walk-forward table.

    python3 scripts/walkforward.py OUT.md report-2018-10-19.json report-2020-10-16.json ...

For every strategy and period: its return over the longest window, the S&P 500's,
the gap, and how often it beat the S&P 500 in the rolling 3-month windows. A
strategy worth keeping beats the index in most periods, including the bad ones.
"""

import json
import sys

KEYS = ["growth", "medium", "dividend", "stock bot", "VIX agent"]
BENCH = ["S&P 500 (SPY)", "Nasdaq 100 (QQQ)", "S&P 500 equal weight (RSP)", "TSX 60 (XIU.TO)"]
NAMES = {"growth": "Growth (Questrade)", "medium": "Medium term", "dividend": "Dividend (Wealthsimple)",
         "stock bot": "Stock bot", "VIX agent": "VIX agent"}


def pct(x):
    return "n/a" if x is None else "%+.1f%%" % x


def table(reports):
    reports = sorted(reports, key=lambda r: r["asof"])
    win = reports[0]["windows"][0]
    L = ["# Walk-forward: %s windows ending on %d different dates" % (win, len(reports)), "",
         "Each period: $100 for the %s before the as-of close, chosen only from what was in the S&P 500 "
         "that day (plus index funds and a Canadian list). Cell: return (gap to the S&P 500)." % win, "",
         "| strategy | " + " | ".join(r["asof"] for r in reports) + " | beat S&P 500 | average gap |",
         "| --- |" + " ---: |" * (len(reports) + 2)]
    for k in KEYS + BENCH:
        cells, beat, gaps = [], 0, []
        for r in reports:
            row = r["results"][win]
            x, spy = (row.get(k) or {}).get("return_pct"), (row.get("S&P 500 (SPY)") or {}).get("return_pct")
            if x is None:
                cells.append("n/a")
                continue
            gap = None if spy is None else x - spy
            if gap is not None and k != "S&P 500 (SPY)":
                gaps.append(gap)
                beat += gap > 0
            cells.append(pct(x) + ("" if gap is None or k == "S&P 500 (SPY)" else " (%+.1f)" % gap))
        L.append("| %s | %s | %s | %s |" % (NAMES.get(k, k), " | ".join(cells),
                                            "–" if k == "S&P 500 (SPY)" else "%d of %d" % (beat, len(gaps)),
                                            "–" if not gaps else "%+.1f pts" % (sum(gaps) / len(gaps))))
    L += ["", "## Rolling 3-month windows inside each period (beat the S&P 500 / windows)", "",
          "| strategy | " + " | ".join(r["asof"] for r in reports) + " |", "| --- |" + " ---: |" * len(reports)]
    for k in KEYS:
        cells = []
        for r in reports:
            t = ((r.get("rolling") or {}).get("table") or {}).get(k)
            cells.append("%s of %s" % (t["beat_spy"], t["windows"]) if t else "n/a")
        L.append("| %s | %s |" % (NAMES[k], " | ".join(cells)))
    L += ["", "## Coverage and self-checks", ""]
    for r in reports:
        cov = r["results"][win].get("coverage") or {}
        bad = [c["name"] for c in r.get("checks", []) if not c["ok"]]
        L.append("- %s: %s of %s index members priced; self-checks %s" % (
            r["asof"], cov.get("priced", "?"), cov.get("members", "?"), "all passed" if not bad else "FAILED: " + ", ".join(bad)))
    L += ["", "_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._"]
    return "\n".join(L) + "\n"


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
