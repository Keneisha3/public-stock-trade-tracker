#!/usr/bin/env python3
"""Canadian Depositary Receipts (CDRs): US companies that trade in Canadian dollars on Cboe Canada,
currency-hedged, so a TFSA can hold them without converting CAD to USD (no 1.5% bank conversion,
no Norbert's gambit) and in small amounts.

    python3 cdr.py verify --out DIR      # which candidate symbols really trade (Yahoo), and how each
                                         # CDR's return compared with holding the US shares
    python3 cdr.py show AAPL GOOGL       # the CDR for each ticker, from cdr.json

Only symbols that the verify step found trading, in CAD, with recent prices are used (cdr.json).
A hedged CDR follows the US share's US-dollar return, not its Canadian-dollar return, minus a small
hedging cost: it differs from holding the US shares whenever the US dollar moves. Not financial advice.
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

MAP = os.path.join(HERE, "cdr.json")
MIN_BARS = 120  # about six months of trading: a real listing, not a placeholder quote
# US ticker -> Yahoo symbols to try (Cboe Canada listings end in .NE). Only verified ones are kept.
CANDIDATES = {
    "AAPL": ["AAPL.NE"], "MSFT": ["MSFT.NE"], "AMZN": ["AMZN.NE"], "GOOGL": ["GOOG.NE", "GOOGL.NE"],
    "META": ["META.NE", "FB.NE"], "NVDA": ["NVDA.NE"], "TSLA": ["TSLA.NE"], "NFLX": ["NFLX.NE"],
    "COST": ["COST.NE"], "JPM": ["JPM.NE"], "V": ["VISA.NE", "V.NE"], "MA": ["MA.NE", "MAST.NE"],
    "BRK-B": ["BRK.NE"], "HD": ["HD.NE"], "WMT": ["WMT.NE"], "DIS": ["DIS.NE"], "CRM": ["CRM.NE"],
    "AMD": ["AMD.NE"], "INTC": ["INTC.NE"], "AVGO": ["AVGO.NE"], "UNH": ["UNH.NE"], "PFE": ["PFE.NE"],
    "BAC": ["BAC.NE"], "GS": ["GS.NE"], "XOM": ["XOM.NE"], "CVX": ["CVX.NE"], "KO": ["KO.NE"],
    "PEP": ["PEP.NE"], "MCD": ["MCD.NE"], "UBER": ["UBER.NE"], "NKE": ["NKE.NE"], "ABBV": ["ABBV.NE"],
    "LLY": ["LLY.NE"], "TSM": ["TSM.NE"], "ADBE": ["ADBE.NE"], "ORCL": ["ORCL.NE"], "CSCO": ["CSCO.NE"],
    "IBM": ["IBM.NE"], "PG": ["PG.NE"], "JNJ": ["JNJ.NE"], "BA": ["BA.NE", "BOEI.NE"], "PYPL": ["PYPL.NE"],
    "SBUX": ["SBUX.NE"], "QCOM": ["QCOM.NE"], "TXN": ["TXN.NE"], "AMAT": ["AMAT.NE"], "LRCX": ["LRCX.NE"],
    "MU": ["MU.NE"], "BABA": ["BABA.NE"], "UNP": ["UNP.NE"], "CAT": ["CAT.NE"], "HON": ["HON.NE"],
}


def _ret(bars, a, b):
    """Total price return % from the close on/after `a` to the close on/before `b`."""
    xs = [x for x in bars if a <= x["d"] <= b]
    return 100.0 * (xs[-1]["c"] / xs[0]["c"] - 1) if len(xs) > 1 and xs[0]["c"] else None


def compare(cdr, us, fx, since=None):
    """How a CDR did against its US share over the days both traded: {"days", "cdr_pct", "us_usd",
    "us_cad", "hedge_cost_per_year"} (returns in %, the cost is how far the CDR fell short of the
    US-dollar return, per year)."""
    first_us = us["bars"][0]["d"] if us["bars"] else "9999"
    days = sorted(x["d"] for x in cdr["bars"] if x["d"] >= first_us and (not since or x["d"] >= since))
    if len(days) < 60:  # the listings and the FX rate are dated a little differently: match on/before
        return None
    a, b = days[0], days[-1]

    def last(bars, day):  # the last close on or before `day`
        xs = [x["c"] for x in bars if x["d"] <= day]
        return xs[-1] if xs else None
    vals = [(last(cdr["bars"], d), last(us["bars"], d), last(fx["bars"], d)) for d in (a, b)]
    if not all(v for pair in vals for v in pair):
        return None
    (c0, u0, f0), (c1, u1, f1) = vals
    r_cdr, r_usd, r_fx = 100.0 * (c1 / c0 - 1), 100.0 * (u1 / u0 - 1), 100.0 * (f1 / f0 - 1)
    years = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days / 365.25
    r_cad = 100.0 * ((1 + r_usd / 100) * (1 + r_fx / 100) - 1)
    cost = 100.0 * (((1 + r_usd / 100) / (1 + r_cdr / 100)) ** (1 / years) - 1) if years > 0 else None
    return {"from": a, "to": b, "days": len(days), "cdr_pct": round(r_cdr, 2), "us_usd": round(r_usd, 2),
            "us_cad": round(r_cad, 2), "hedge_cost_per_year": None if cost is None else round(cost, 2)}


def verify(get=None, today=None, log=print):
    """Try every candidate; keep the ones that trade in CAD, with 6+ months of prices and a price in the
    last 10 days.
    Returns ({us ticker: cdr symbol}, rows for the report)."""
    get = get or (lambda s, r: mk.get_chart(s, range_=r))
    today = today or datetime.date.today().isoformat()
    fresh = (datetime.date.fromisoformat(today) - datetime.timedelta(days=10)).isoformat()
    try:
        fx = get("USDCAD=X", "5y")
    except mk.MarketError as e:
        raise SystemExit("cdr: no USD/CAD rate: %s" % e)
    found, rows = {}, []
    for us, cands in sorted(CANDIDATES.items()):
        for sym in cands:
            try:
                ch = get(sym, "5y")
            except mk.MarketError:
                continue
            if (ch.get("currency") or "").upper() != "CAD" or len(ch["bars"]) < MIN_BARS or ch["bars"][-1]["d"] < fresh:
                continue  # a symbol Yahoo answers with a day or two of prices is not a real, trading CDR
            try:
                usc = get(us, "5y")
            except mk.MarketError as e:
                log("cdr: %s: %s" % (us, e))
                break
            found[us] = sym
            ds = [x["d"] for x in ch["bars"]]
            rows.append(dict(compare(ch, usc, fx) or {}, us=us, cdr=sym, name=ch.get("name", ""),
                             bars=len(ds), first_bar=ds[0], last_bar=ds[-1]))
            break
    return found, rows


def render(found, rows):
    L = ["# Canadian Depositary Receipts (CDRs) for the copycat's picks", "",
         "%d of %d US companies have a CDR that trades in Canadian dollars on Cboe Canada. A CDR is "
         "currency-hedged: it follows the US share in US dollars, minus a small hedging cost, so it differs from "
         "holding the US shares whenever the US dollar moves against the Canadian dollar." % (
             len(found), len(CANDIDATES)), "",
         "| company | CDR | since | CDR return | US share, USD | US share, CAD | CDR shortfall a year |",
         "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for r in rows:
        if "cdr" in r and r.get("days"):
            L.append("| %s | %s | %s | %+.1f%% | %+.1f%% | %+.1f%% | %+.2f pts |" % (
                r["us"], r["cdr"], r["from"], r["cdr_pct"], r["us_usd"], r["us_cad"], r["hedge_cost_per_year"] or 0))
        elif "cdr" in r:
            L.append("| %s | %s | (too little history: %s bars from %s) | | | | |" % (
                r["us"], r["cdr"], r.get("bars"), r.get("first_bar")))
    L += ["", "_Not financial advice. Check the CDR's ratio and fees before buying._"]
    return "\n".join(L) + "\n"


def load(path=MAP):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("cdr", {})
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Canadian Depositary Receipts for US stocks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    s = sub.add_parser("show")
    s.add_argument("tickers", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        m = load()
        for t in a.tickers:
            print("%-6s %s" % (t.upper(), m.get(t.upper(), "no CDR found")))
        return 0
    found, rows = verify(log=lambda x: print(x, file=sys.stderr))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "cdr.json"), "w", encoding="utf-8") as fh:
        json.dump({"verified": datetime.date.today().isoformat(), "cdr": found, "rows": rows}, fh, indent=1)
    text = render(found, rows)
    with open(os.path.join(a.out, "cdr.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
