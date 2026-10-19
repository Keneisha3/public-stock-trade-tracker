#!/usr/bin/env python3
"""Dated signals for the replay, each known from the day it became PUBLIC (the filing date):

  congress   every House member's disclosed stock trades (Periodic Transaction Reports on
             disclosures-clerk.house.gov), parsed with trader-pelosi's ptr.py
  insiders   company insiders' open-market purchases (Form 4, code P) from the SEC's
             quarterly "Insider Transactions Data Sets" (bulk TSV files since 2006)

    python3 signals.py congress --years 2015-2026 --out DIR      # needs pdftotext
    python3 signals.py insiders --quarters 2015q1-2026q3 --out DIR
    python3 signals.py info DIR

Each writes DIR/<name>.json.gz: {"source", "built", "rows": [...], "stats": {...}}. The
replay reads them with --signals DIR. A row is used only from its filing date on.
"""

import argparse
import bisect
import csv
import datetime
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-pelosi"))
import ptr  # noqa: E402

SEC_345 = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/%s_form345.zip"
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                      "NOV", "DEC"), 1)}


class SignalError(Exception):
    pass


def iso(text):
    """'31-MAR-2023', '2023-03-31' or '03/31/2023' -> '2023-03-31' (None if unreadable)."""
    t = (text or "").strip().upper()
    try:
        if len(t) == 11 and t[2] == "-" and t[6] == "-":
            return datetime.date(int(t[7:]), MONTHS[t[3:6]], int(t[:2])).isoformat()
        if len(t) >= 10 and t[4] == "-":
            return datetime.date.fromisoformat(t[:10]).isoformat()
        if len(t) == 10 and t[2] == "/":
            return datetime.date(int(t[6:]), int(t[:2]), int(t[3:5])).isoformat()
    except (ValueError, KeyError):
        return None
    return None


def yahoo(ticker):
    t = (ticker or "").strip().upper().replace(".", "-").replace("/", "-")
    return t if t and t.replace("-", "").isalnum() and len(t) <= 8 else None


def write(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- insiders (SEC Form 4 bulk data)

def _tsv(z, name):
    hits = [n for n in z.namelist() if n.upper().endswith(name)]
    if not hits:
        raise SignalError("no %s in the zip (%s)" % (name, ", ".join(z.namelist()[:8])))
    text = z.read(hits[0]).decode("utf-8", "replace")
    return csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)


def parse_form345(data):
    """One quarterly zip -> [[filed, ticker, owner_cik, role, shares, price, value], ...] for
    open-market purchases (Form 4 or 4/A, code P, acquired). role: 'officer', 'director',
    '10% owner' or 'other'."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        subs = {}
        for r in _tsv(z, "SUBMISSION.TSV"):
            if (r.get("DOCUMENT_TYPE") or "").strip() in ("4", "4/A"):
                subs[r["ACCESSION_NUMBER"]] = (iso(r.get("FILING_DATE")), yahoo(r.get("ISSUERTRADINGSYMBOL")))
        owners = {}
        for r in _tsv(z, "REPORTINGOWNER.TSV"):
            rel = (r.get("RPTOWNER_RELATIONSHIP") or "").lower()
            role = ("officer" if "officer" in rel else "director" if "director" in rel
                    else "10% owner" if ("tenpercent" in rel or "10" in rel) else "other")
            owners.setdefault(r["ACCESSION_NUMBER"], (r.get("RPTOWNERCIK") or "", role))
        out = []
        for r in _tsv(z, "NONDERIV_TRANS.TSV"):
            acc = r.get("ACCESSION_NUMBER")
            if acc not in subs or (r.get("TRANS_CODE") or "").strip() != "P" \
                    or (r.get("TRANS_ACQUIRED_DISP_CD") or "").strip() != "A":
                continue
            filed, ticker = subs[acc]
            try:
                shares = float(r.get("TRANS_SHARES") or 0)
                price = float(r.get("TRANS_PRICEPERSHARE") or 0)
            except ValueError:
                continue
            if not filed or not ticker or shares <= 0 or price <= 0:
                continue
            cik, role = owners.get(acc, ("", "other"))
            out.append([filed, ticker, cik, role, round(shares, 2), round(price, 4), round(shares * price, 2)])
        return out


def quarters(spec):
    """'2015q1-2016q2' -> ['2015q1', '2015q2', ..., '2016q2']."""
    a, _, b = spec.lower().partition("-")
    b = b or a
    y, q = int(a[:4]), int(a[-1])
    out = []
    while (y, q) <= (int(b[:4]), int(b[-1])):
        out.append("%dq%d" % (y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def build_insiders(qs, ua, log=print, http=None):
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    http = http or get
    rows, stats = [], {"quarters": {}, "errors": []}
    for q in qs:
        for attempt in range(3):
            try:
                got = parse_form345(http(SEC_345 % q))
                rows += got
                stats["quarters"][q] = len(got)
                log("%s: %d insider purchases" % (q, len(got)))
                break
            except urllib.error.HTTPError as e:
                if e.code == 404 or attempt == 2:
                    stats["errors"].append("%s: HTTP %s" % (q, e.code))
                    break
                time.sleep(5 * (attempt + 1))
            except (urllib.error.URLError, OSError, zipfile.BadZipFile, SignalError) as e:
                if attempt == 2:
                    stats["errors"].append("%s: %s" % (q, e))
                time.sleep(5 * (attempt + 1))
        time.sleep(0.5)  # the SEC asks for at most 10 requests a second
    rows.sort()
    return {"source": "SEC Insider Transactions Data Sets (Form 4, code P)", "built": _now(),
            "columns": ["filed", "ticker", "owner_cik", "role", "shares", "price", "value"],
            "rows": rows, "stats": stats}


# ---------------------------------------------------------------- Congress (House PTRs)

def build_congress(years, pdf_dir, log=print, workers=4):
    """Every House PTR in those years -> [[filed, member, ticker, side, low, high, traded, owner], ...].
    side: 'buy' (purchase, or call options bought) or 'sell' (sale, or puts bought)."""
    from concurrent.futures import ThreadPoolExecutor
    filings, stats = [], {"filings": 0, "read": 0, "unreadable": 0, "errors": []}
    for y in years:
        try:
            idx = ptr.load_index(y)
        except ptr.PtrError as e:
            stats["errors"].append("index %d: %s" % (y, e))
            continue
        got = ptr.select(idx, None, "P")
        filings += got
        log("%d: %d PTR filings" % (y, len(got)))
    stats["filings"] = len(filings)

    def one(f):
        for attempt in range(3):
            try:
                return f, ptr._fetch_and_read(f["doc_id"], f["year"], pdf_dir, f["filed"])[1], None
            except ptr.PtrError as e:
                err = str(e)
                if "HTTP 404" in err:
                    break
                time.sleep(2 * (attempt + 1))
        return f, None, err
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (f, report, err) in enumerate(pool.map(one, filings)):
            if err:
                stats["errors"].append("%s: %s" % (f["doc_id"], err))
                continue
            if not report or not report["rows"]:
                stats["unreadable"] += 1  # mostly scanned paper filings: no text to read
                continue
            stats["read"] += 1
            member = "%s %s" % (f["first"], f["last"])
            for r in report["rows"]:
                t = yahoo(r.get("ticker"))
                if not t:
                    continue
                kind = (r.get("type") or "").upper()
                opt = r.get("option") or {}
                if opt.get("kind") == "put":
                    side = "sell" if kind.startswith("P") else "buy"
                elif kind.startswith("P") or opt.get("exercised"):
                    side = "buy"
                elif kind.startswith("S"):
                    side = "sell"
                else:
                    continue
                rows.append([f["filed"], member, t, side, r.get("amount_low"), r.get("amount_high"),
                             r.get("date"), r.get("owner_name")])
            if i % 500 == 499:
                log("  %d of %d filings" % (i + 1, len(filings)))
    rows.sort(key=lambda r: (r[0] or "", r[2]))
    stats["errors"] = stats["errors"][:50]
    return {"source": "House Clerk Periodic Transaction Reports", "built": _now(),
            "columns": ["filed", "member", "ticker", "side", "low", "high", "traded", "owner"],
            "rows": [r for r in rows if r[0]], "stats": stats}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- point-in-time queries

class Signals:
    """Queries that only see rows filed on or before the day asked about."""

    def __init__(self, congress=None, insiders=None):
        self.congress = (congress or {}).get("rows") or []
        self.insiders = (insiders or {}).get("rows") or []
        self._cd = [r[0] for r in self.congress]
        self._id = [r[0] for r in self.insiders]

    @classmethod
    def load(cls, folder):
        def opt(name):
            p = os.path.join(folder, name)
            return read(p) if os.path.exists(p) else None
        return cls(opt("congress.json.gz"), opt("insiders.json.gz"))

    def __bool__(self):
        return bool(self.congress or self.insiders)

    @staticmethod
    def _since(day, days):
        return (datetime.date.fromisoformat(day) - datetime.timedelta(days=days)).isoformat()

    def congress_buys(self, day, days=90):
        """{ticker: {"members": n, "buys": n, "sells": n, "low": $}} from filings in (day-days, day]."""
        a, b = bisect.bisect_right(self._cd, self._since(day, days)), bisect.bisect_right(self._cd, day)
        out = {}
        for filed, member, t, side, low, high, traded, owner in self.congress[a:b]:
            x = out.setdefault(t, {"members": set(), "buys": 0, "sells": 0, "low": 0})
            if side == "buy":
                x["members"].add(member)
                x["buys"] += 1
                x["low"] += low or 0
            else:
                x["sells"] += 1
        return {t: dict(x, members=len(x["members"])) for t, x in out.items() if x["buys"] > x["sells"]}

    def insider_buys(self, day, days=60):
        """{ticker: {"insiders": n, "officers": n, "value": $}} from filings in (day-days, day]."""
        a, b = bisect.bisect_right(self._id, self._since(day, days)), bisect.bisect_right(self._id, day)
        out = {}
        for filed, t, cik, role, shares, price, value in self.insiders[a:b]:
            x = out.setdefault(t, {"owners": set(), "officers": set(), "value": 0.0})
            x["owners"].add(cik)
            if role == "officer":
                x["officers"].add(cik)
            x["value"] += value
        return {t: {"insiders": len(x["owners"]), "officers": len(x["officers"]), "value": round(x["value"], 2)}
                for t, x in out.items()}


def info(folder):
    s = Signals.load(folder)
    for name, rows in (("congress", s.congress), ("insiders", s.insiders)):
        if rows:
            print("%s: %d rows, filed %s to %s, %d tickers" % (name, len(rows), rows[0][0], rows[-1][0],
                                                               len({r[2 if name == "congress" else 1] for r in rows})))
        else:
            print("%s: none" % name)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build dated Congress and insider signals for the replay.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("congress")
    c.add_argument("--years", default="2015-%d" % datetime.date.today().year)
    c.add_argument("--out", required=True)
    c.add_argument("--pdf-dir", default=None)
    i = sub.add_parser("insiders")
    i.add_argument("--quarters", required=True, help="e.g. 2015q1-2026q3")
    i.add_argument("--out", required=True)
    i.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT") or "",
                   help="the SEC asks for 'Name email' (or set SEC_USER_AGENT)")
    n = sub.add_parser("info")
    n.add_argument("dir")
    a = ap.parse_args(argv)
    if a.cmd == "info":
        info(a.dir)
        return 0
    if a.cmd == "congress":
        lo, _, hi = a.years.partition("-")
        doc = build_congress(range(int(lo), int(hi or lo) + 1), a.pdf_dir or os.path.join(a.out, "ptr-pdfs"))
        write(os.path.join(a.out, "congress.json.gz"), doc)
    else:
        if not a.user_agent:
            print("signals: set SEC_USER_AGENT (or --user-agent) to 'Your Name you@example.com'", file=sys.stderr)
            return 2
        doc = build_insiders(quarters(a.quarters), a.user_agent)
        write(os.path.join(a.out, "insiders.json.gz"), doc)
    print(json.dumps(doc["stats"])[:2000])
    print("%d rows" % len(doc["rows"]))
    return 0 if doc["rows"] else 3


if __name__ == "__main__":
    sys.exit(main())
