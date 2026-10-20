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
SEC_DAILY = "https://www.sec.gov/Archives/edgar/daily-index/%d/QTR%d/form.%s.idx"
SEC_DOC = "https://www.sec.gov/Archives/%s"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/%s"
EVENT_ITEMS = {"1.01": "material agreement", "1.03": "bankruptcy", "2.01": "acquisition or sale done",
               "2.02": "earnings results", "2.05": "restructuring costs", "2.06": "impairment",
               "4.02": "restatement", "5.02": "executive or director change", "7.01": "investor update",
               "8.01": "other news"}
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


# ---------------------------------------------------------------- insiders, fresh (EDGAR daily index)

def parse_daily_index(text):
    """EDGAR form.YYYYMMDD.idx -> [(form, company, cik, filed, path)] (columns are 2+ spaces apart)."""
    out, body = [], False
    for ln in text.splitlines():
        if ln.startswith("---"):
            body = True
            continue
        if not body or not ln.strip():
            continue
        parts = [p for p in __import__("re").split(r"\s{2,}", ln.strip()) if p]
        if len(parts) >= 5:
            out.append((parts[0], parts[1], parts[2], iso(parts[3][:4] + "-" + parts[3][4:6] + "-" + parts[3][6:8]),
                        parts[4]))
    return out


def parse_form4(text, filed):
    """One Form 4 submission (.txt with the XML inside) -> rows like parse_form345's."""
    import re
    import xml.etree.ElementTree as ET
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", text or "", re.S)
    if not m:
        return []
    try:
        doc = ET.fromstring(m.group(0))
    except ET.ParseError:
        return []
    if (doc.findtext("documentType") or "").strip() not in ("4", "4/A"):
        return []
    ticker = yahoo(doc.findtext("issuer/issuerTradingSymbol"))
    cik = (doc.findtext("reportingOwner/reportingOwnerId/rptOwnerCik") or "").strip()
    rel = doc.find("reportingOwner/reportingOwnerRelationship")

    def flag(name):
        return (rel.findtext(name) if rel is not None else "") in ("1", "true", "True")
    role = "officer" if flag("isOfficer") else "director" if flag("isDirector") else \
        "10% owner" if flag("isTenPercentOwner") else "other"
    out = []
    for t in doc.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if (t.findtext("transactionCoding/transactionCode") or "").strip() != "P" or \
                (t.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") or "").strip() != "A":
            continue
        try:
            shares = float(t.findtext("transactionAmounts/transactionShares/value") or 0)
            price = float(t.findtext("transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        if ticker and shares > 0 and price > 0:
            out.append([filed, ticker, cik, role, round(shares, 2), round(price, 4), round(shares * price, 2)])
    return out


def build_insiders_recent(since, until, ua, tickers=None, log=print, http=None, pause=0.13):
    """Form 4 open-market purchases filed from `since` to `until`, read one by one from the EDGAR
    daily index (the quarterly bulk files arrive months late). tickers: only these issuers."""
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    http = http or get
    ciks = None
    if tickers:
        doc = json.loads(http(SEC_TICKERS))
        want = {t.upper() for t in tickers}
        ciks = {str(v["cik_str"]) for v in doc.values() if yahoo(v.get("ticker")) in want}
    rows, stats = [], {"days": 0, "filings": 0, "errors": []}
    d = datetime.date.fromisoformat(since)
    end = datetime.date.fromisoformat(until)
    while d <= end:
        if d.weekday() < 5:
            q = (d.month - 1) // 3 + 1
            try:
                idx = parse_daily_index(http(SEC_DAILY % (d.year, q, d.strftime("%Y%m%d"))))
                stats["days"] += 1
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
                idx = []
                if "404" not in str(e):
                    stats["errors"].append("%s: %s" % (d, e))
            seen = set()
            for form, company, cik, filed, path in idx:
                if form not in ("4", "4/A") or path in seen or (ciks is not None and cik not in ciks):
                    continue
                seen.add(path)
                try:
                    rows += parse_form4(http(SEC_DOC % path), filed)
                    stats["filings"] += 1
                except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
                    stats["errors"].append("%s: %s" % (path, e))
                if pause:
                    time.sleep(pause)  # the SEC asks for at most 10 requests a second
            if stats["days"] % 20 == 0:
                log("%s: %d filings read, %d purchases" % (d, stats["filings"], len(rows)))
        d += datetime.timedelta(days=1)
    rows.sort()
    stats["errors"] = stats["errors"][:50]
    return {"source": "SEC EDGAR daily index, Form 4 (code P)", "built": _now(), "since": since, "until": until,
            "columns": ["filed", "ticker", "owner_cik", "role", "shares", "price", "value"], "rows": rows, "stats": stats}


# ---------------------------------------------------------------- news events (SEC 8-K)

def effective_day(filed, accepted):
    """The first day the market could trade on a filing: the filing day if the SEC accepted it
    before 4 p.m. New York time, otherwise the next calendar day (the replay then waits for
    the next trading day)."""
    t = (accepted or "")[11:16]
    if t and t >= "16:00":
        return (datetime.date.fromisoformat(filed) + datetime.timedelta(days=1)).isoformat()
    return filed


def parse_submissions(doc, ticker, since="2015-01-01"):
    """One data.sec.gov submissions JSON (the 'recent' block or an extra file) -> 8-K rows
    [effective, ticker, items, filed]."""
    block = (doc.get("filings") or {}).get("recent") if "filings" in doc else doc
    block = block or {}
    out = []
    for form, filed, acc, items in zip(block.get("form", []), block.get("filingDate", []),
                                       block.get("acceptanceDateTime", []), block.get("items", [])):
        if form not in ("8-K", "8-K/A") or not filed or filed < since:
            continue
        out.append([effective_day(filed, acc), ticker, items or "", filed])
    return out


def build_events(tickers, ua, since="2015-01-01", log=print, http=None, pause=0.12):
    """Every 8-K (company news filed with the SEC: earnings, deals, executive changes...) for these
    tickers since `since`, from data.sec.gov submissions, dated to when the market could act."""
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    http = http or get
    names = json.loads(http(SEC_TICKERS))
    cik = {}
    for v in names.values():
        t = yahoo(v.get("ticker"))
        if t and t not in cik:
            cik[t] = "CIK%010d.json" % int(v["cik_str"])
    rows, stats = [], {"tickers": 0, "no_cik": 0, "errors": []}
    for i, t in enumerate(sorted(set(tickers))):
        if t not in cik:
            stats["no_cik"] += 1
            continue
        try:
            doc = json.loads(http(SEC_SUBMISSIONS % cik[t]))
            got = parse_submissions(doc, t, since)
            for f in (doc.get("filings") or {}).get("files", []):
                if (f.get("filingTo") or "9999") >= since:
                    got += parse_submissions(json.loads(http(SEC_SUBMISSIONS % f["name"])), t, since)
                    time.sleep(pause)
            rows += got
            stats["tickers"] += 1
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
            stats["errors"].append("%s: %s" % (t, e))
        time.sleep(pause)  # the SEC asks for at most 10 requests a second
        if i % 100 == 99:
            log("  %d tickers, %d 8-Ks" % (i + 1, len(rows)))
    rows.sort()
    stats["errors"] = stats["errors"][:50]
    return {"source": "SEC EDGAR submissions (8-K)", "built": _now(), "since": since,
            "columns": ["effective", "ticker", "items", "filed"], "rows": rows, "stats": stats}


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

    def __init__(self, congress=None, insiders=None, events=None):
        self.congress = (congress or {}).get("rows") or []
        self.insiders = (insiders or {}).get("rows") or []
        self.events = (events or {}).get("rows") or []
        self._cd = [r[0] for r in self.congress]
        self._id = [r[0] for r in self.insiders]
        self._ed = [r[0] for r in self.events]

    @classmethod
    def load(cls, folder):
        def opt(name):
            p = os.path.join(folder, name)
            return read(p) if os.path.exists(p) else None
        ins = opt("insiders.json.gz")
        recent = opt("insiders_recent.json.gz")
        if recent:  # the daily-index rows fill the months the quarterly files do not cover yet
            have = {tuple(r) for r in (ins or {}).get("rows", [])}
            last = max((r[0] for r in (ins or {}).get("rows", [])), default="")
            rows = list((ins or {}).get("rows", [])) + [r for r in recent["rows"] if r[0] > last and tuple(r) not in have]
            ins = {"rows": sorted(rows)}
        return cls(opt("congress.json.gz"), ins, opt("events.json.gz"))

    def __bool__(self):
        return bool(self.congress or self.insiders or self.events)

    def news(self, day, days=3, item=None):
        """{ticker: [items...]} for 8-Ks the market could act on in (day-days, day]. item: e.g.
        '2.02' (earnings) to keep only those."""
        a, b = bisect.bisect_right(self._ed, self._since(day, days)), bisect.bisect_right(self._ed, day)
        out = {}
        for eff, t, items, filed in self.events[a:b]:
            if item and item not in items.split(","):
                continue
            out.setdefault(t, []).append(eff)
        return out

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

    def congress_rows(self, day, days=90, side="buy"):
        """The raw rows filed in (day-days, day] on one side."""
        a, b = bisect.bisect_right(self._cd, self._since(day, days)), bisect.bisect_right(self._cd, day)
        return [r for r in self.congress[a:b] if r[3] == side]

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
    for name, rows in (("congress", s.congress), ("insiders", s.insiders), ("events", s.events)):
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
    r = sub.add_parser("insiders-recent")
    r.add_argument("--since", required=True)
    r.add_argument("--until", default=datetime.date.today().isoformat())
    r.add_argument("--out", required=True)
    r.add_argument("--sp500", action="store_true", help="only companies that were ever in the S&P 500")
    r.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT") or "")
    ev = sub.add_parser("events")
    ev.add_argument("--out", required=True)
    ev.add_argument("--since", default="2015-01-01")
    ev.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT") or "")
    n = sub.add_parser("info")
    n.add_argument("dir")
    a = ap.parse_args(argv)
    if a.cmd == "info":
        info(a.dir)
        return 0
    if a.cmd == "events":
        if not a.user_agent:
            print("signals: set SEC_USER_AGENT (or --user-agent) to 'Your Name you@example.com'", file=sys.stderr)
            return 2
        import universe
        doc = build_events(list(universe.Universe().spans), a.user_agent, a.since)
        write(os.path.join(a.out, "events.json.gz"), doc)
        print(json.dumps(doc["stats"])[:1500])
        print("%d rows" % len(doc["rows"]))
        return 0 if doc["rows"] else 3
    if a.cmd == "insiders-recent":
        if not a.user_agent:
            print("signals: set SEC_USER_AGENT (or --user-agent) to 'Your Name you@example.com'", file=sys.stderr)
            return 2
        tickers = None
        if a.sp500:
            import universe
            tickers = list(universe.Universe().spans)
        doc = build_insiders_recent(a.since, a.until, a.user_agent, tickers)
        write(os.path.join(a.out, "insiders_recent.json.gz"), doc)
        print(json.dumps(doc["stats"])[:1500])
        print("%d rows" % len(doc["rows"]))
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
