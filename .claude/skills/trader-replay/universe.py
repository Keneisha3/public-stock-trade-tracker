#!/usr/bin/env python3
"""Point-in-time stock universes: who was in the index ON a given day.

Choosing from today's winners (NVDA, AVGO...) and replaying them into the past
is hindsight. Here every decision on day D may only pick from what was in the
S&P 500 on day D, from a membership history:

  sp500_members.json   [first day, last day] in the S&P 500 for every ticker
                       since 2014. Built from fja05680/sp500 (MIT licence,
                       (c) Farrell J. Aultman), "S&P 500 Historical Components
                       & Changes (Updated).csv", which goes back to 1996.

    python3 universe.py update              # rebuild from the latest CSV (network)
    python3 universe.py on 2020-03-20       # members that day
    python3 universe.py info

Canada has no free membership history: CANADA is a broad list of about 70
large TSX companies chosen as "the big ones today" (index members, not
picks), so a milder hindsight bias remains for the Canadian side. Yahoo also
has no prices for many companies that later left the market (bought out or
bankrupt), so those cannot be chosen: a residual survivorship bias that the
replay reports as "coverage".
"""

import bisect
import csv
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "sp500_members.json")
SOURCE = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
          "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")
SINCE = "2014-01-01"

CANADA = [  # large TSX companies (Yahoo symbols), as listed in 2026
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO", "MFC.TO", "SLF.TO", "GWO.TO", "POW.TO",
    "IFC.TO", "FFH.TO", "BN.TO", "BAM.TO", "X.TO", "IGM.TO", "EQB.TO",
    "ENB.TO", "TRP.TO", "PPL.TO", "KEY.TO", "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO", "TOU.TO", "ARX.TO",
    "FTS.TO", "EMA.TO", "H.TO", "AQN.TO", "CU.TO", "BEP-UN.TO", "BIP-UN.TO",
    "BCE.TO", "T.TO", "RCI-B.TO", "QBR-B.TO",
    "CNR.TO", "CP.TO", "TFII.TO", "WCN.TO", "CAE.TO", "STN.TO", "WSP.TO", "TIH.TO",
    "SHOP.TO", "CSU.TO", "OTEX.TO", "GIB-A.TO", "DSG.TO",
    "ATD.TO", "L.TO", "MRU.TO", "WN.TO", "DOL.TO", "CTC-A.TO", "QSR.TO", "MG.TO", "CCL-B.TO", "SAP.TO",
    "GIL.TO", "NTR.TO", "ABX.TO", "AEM.TO", "WPM.TO", "FNV.TO", "K.TO", "TECK-B.TO", "FM.TO", "CCO.TO",
    "REI-UN.TO", "CAR-UN.TO",
]


def yahoo(ticker):
    """S&P CSV ticker -> Yahoo symbol (BRK.B -> BRK-B)."""
    return ticker.strip().upper().replace(".", "-")


def build(csv_text, since=SINCE):
    """CSV of daily snapshots -> {ticker: [[first, last], ...]} from `since` on."""
    rows = [r for r in csv.DictReader(io.StringIO(csv_text)) if r["date"]]
    rows.sort(key=lambda r: r["date"])
    keep = [r for r in rows if r["date"] >= since]
    before = [r for r in rows if r["date"] < since]
    if before:  # the snapshot in force on `since`
        keep.insert(0, dict(before[-1], date=since))
    spans, open_ = {}, {}
    for r in keep:
        now = {yahoo(t) for t in r["tickers"].split(",") if t.strip()}
        for t in now - set(open_):
            open_[t] = r["date"]
        for t in set(open_) - now:
            spans.setdefault(t, []).append([open_.pop(t), r["date"]])
        last = r["date"]
    for t, first in open_.items():
        spans.setdefault(t, []).append([first, None])  # still a member at the last snapshot
    return {"source": SOURCE.replace("%26", "&").replace("%20", " "),
            "licence": "MIT, (c) Farrell J. Aultman (github.com/fja05680/sp500)",
            "since": since, "last_snapshot": last,
            "note": "a ticker is a member from `first` up to the day before `last` (null: still a member)",
            "members": {t: spans[t] for t in sorted(spans)}}


class Universe:
    """members_on(day) for the S&P 500, from sp500_members.json."""

    def __init__(self, doc=None, path=PATH):
        if doc is None:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        self.doc = doc
        self.spans = doc["members"]
        self._cache = {}
        self._days = sorted({d for sp in self.spans.values() for a, b in sp for d in (a, b) if d})

    def members_on(self, day):
        """Tickers in the index at the close of `day` (as the history knew it)."""
        key = self._days[max(0, bisect.bisect_right(self._days, day) - 1)] if self._days else day
        if key not in self._cache:
            self._cache[key] = frozenset(t for t, sp in self.spans.items()
                                         if any(a <= day and (b is None or day < b) for a, b in sp))
        return self._cache[key]

    def ever(self, start, end):
        """Every ticker that was a member at some point between start and end."""
        return sorted(t for t, sp in self.spans.items()
                      if any(a <= end and (b is None or b > start) for a, b in sp))


def load():
    return Universe() if os.path.exists(PATH) else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "info"
    if cmd == "update":
        req = urllib.request.Request(SOURCE, headers={"User-Agent": "public-stock-trade-tracker"})
        with urllib.request.urlopen(req, timeout=60) as r:
            doc = build(r.read().decode("utf-8"))
        with open(PATH, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"), sort_keys=True)
            fh.write("\n")
        print("wrote %s: %d tickers since %s, last snapshot %s" % (
            PATH, len(doc["members"]), doc["since"], doc["last_snapshot"]))
        return 0
    u = Universe()
    if cmd == "on":
        m = sorted(u.members_on(argv[1]))
        print("%d members on %s" % (len(m), argv[1]))
        print(" ".join(m))
        return 0
    print("S&P 500 history: %d tickers since %s, last snapshot %s; Canada list: %d" % (
        len(u.spans), u.doc["since"], u.doc["last_snapshot"], len(CANADA)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
