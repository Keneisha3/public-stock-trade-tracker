#!/usr/bin/env python3
"""Discovery: where new stock ideas come from, saved every day so they can be tested later.

Two kinds of source:

  the whole market   every US-listed common stock (Nasdaq Trader symbol directory: Nasdaq,
                     NYSE, NYSE American, Cboe), every TSX and TSX Venture company (TMX
                     directory), every SEC filer with a ticker, and the holdings of the
                     Russell 2000, S&P 400 and S&P 600 funds (iShares)
  idea lists         Yahoo Finance trending tickers and predefined screens (most active,
                     gainers, losers, undervalued growth...), tickers named in market news
                     (Yahoo Finance and Google News RSS), companies on Motley Fool's public
                     news pages (their paid picks are not touched), Reddit / WallStreetBets
                     mention counts (ApeWisdom)

    python3 discover.py snapshot                 # fetch every source, save a dated snapshot
    python3 discover.py snapshot --only news,reddit
    python3 discover.py funnel                   # rank the idea lists: liquid, trending, strong
    python3 discover.py funnel --deep            # rank the WHOLE market (thousands of charts: slow)
    python3 discover.py show

Snapshots go to trader/discover/archive/<date>.json.gz. Nothing here can be backtested
until the archive has history: a list fetched today says nothing about last year. After a
few months, the replay can test "does being named in the news / on Reddit / by the Fool
predict anything?" point in time, from the snapshot dates. Ideas are leads, not advice.
"""

import argparse
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

UA = "Mozilla/5.0 (compatible; public-stock-trade-tracker/1.0)"
URLS = {
    "nasdaq_listed": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other_listed": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    "sec_tickers": "https://www.sec.gov/files/company_tickers.json",
    "tsx": "https://www.tsx.com/json/company-directory/search/tsx/%5E*",
    "tsxv": "https://www.tsx.com/json/company-directory/search/tsxv/%5E*",
    "ishares": "https://www.ishares.com/us/products/%s/%s/1467271812596.ajax?fileType=csv&fileName=%s_holdings&dataType=fund",
    "yahoo_trending": "https://query1.finance.yahoo.com/v1/finance/trending/US?count=50",
    "yahoo_screen": "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=%s&count=100",
    "yahoo_news": "https://finance.yahoo.com/news/rssindex",
    "google_news": "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en",
    "fool": ["https://www.fool.com/investing-news/", "https://www.fool.com/"],
    "apewisdom": "https://apewisdom.io/api/v1.0/filter/all-stocks/page/%d",
}
ISHARES = {"IWM": ("239710", "ishares-russell-2000-etf"), "IJH": ("239763", "ishares-core-sp-midcap-etf"),
           "IJR": ("239774", "ishares-core-sp-smallcap-etf")}
SCREENS = ["most_actives", "day_gainers", "day_losers", "undervalued_growth_stocks", "growth_technology_stocks",
           "aggressive_small_caps", "small_cap_gainers", "undervalued_large_caps"]
NEWS_QUERIES = ["stock market", "stocks to buy", "earnings beat", "analyst upgrade"]
MARKET = ("listed_us", "listed_tsx", "sec", "index_funds")          # the whole market
IDEAS = ("trending", "screens", "news", "fool", "reddit")          # idea lists


class DiscoverError(Exception):
    pass


def fetch(url, ua=UA, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404) or attempt == 2:
                raise DiscoverError("%s answered HTTP %d" % (url.split("?")[0], e.code))
        except (urllib.error.URLError, OSError) as e:
            if attempt == 2:
                raise DiscoverError("could not reach %s: %s" % (url.split("/")[2], e))
        time.sleep(2 + 3 * attempt)


# ---------------------------------------------------------------- parsers (pure, tested offline)

JUNK = re.compile(r"\b(warrants?|rights?|units?|preferred|depositary|notes? due|debentures?|% |trust pref)\b", re.I)


def parse_symdir(text, kind):
    """Nasdaq Trader symbol directory (pipe-separated) -> [(yahoo symbol, name)], common stocks only:
    no ETFs, test issues, warrants, rights, units or preferred shares."""
    lines = [x for x in text.splitlines() if x and not x.startswith("File Creation Time")]
    if not lines:
        return []
    head = lines[0].split("|")
    col = {h.strip(): i for i, h in enumerate(head)}
    sym_col = col.get("Symbol") if kind == "nasdaq" else col.get("ACT Symbol", col.get("CQS Symbol"))
    out = []
    for ln in lines[1:]:
        f = ln.split("|")
        if len(f) < len(head):
            continue
        name = f[col["Security Name"]]
        if f[col["ETF"]].strip() == "Y" or f[col.get("Test Issue", 0)].strip() == "Y" or JUNK.search(name):
            continue
        sym = f[sym_col].strip()
        if not sym or "$" in sym or (len(sym) > 5 and "." not in sym):
            continue
        out.append((sym.replace(".", "-").replace("/", "-"), name.strip()))
    return out


def parse_sec_tickers(doc):
    return sorted({mk.yahoo_symbol(v["ticker"]) for v in (doc or {}).values() if v.get("ticker")})


def parse_tmx(doc, suffix):
    out = []
    for c in (doc or {}).get("results", []):
        for ins in c.get("instruments") or [{"symbol": c.get("symbol"), "name": c.get("name")}]:
            s = (ins.get("symbol") or "").strip().upper()
            if s and not re.search(r"\.(PR|DB|WT|NT|RT|U)\b", s):
                out.append(s.replace(".", "-") + suffix)
    return sorted(set(out))


def parse_ishares(text):
    """iShares holdings CSV (a few lines of preamble, then a 'Ticker,...' header) -> equity tickers."""
    lines = text.splitlines()
    start = next((i for i, x in enumerate(lines) if x.startswith("Ticker,")), None)
    if start is None:
        return []
    out = []
    for row in __import__("csv").DictReader(io.StringIO("\n".join(lines[start:]))):
        t = (row.get("Ticker") or "").strip().upper()
        if t and t != "-" and (row.get("Asset Class") or "Equity").strip() == "Equity" and t.replace(".", "").isalnum():
            out.append(t.replace(".", "-"))
    return sorted(set(out))


def parse_yahoo_quotes(doc):
    """Yahoo trending / screener JSON -> symbols."""
    fin = (doc or {}).get("finance") or {}
    out = []
    for res in fin.get("result") or []:
        for q in res.get("quotes") or []:
            s = q.get("symbol")
            if s and "=" not in s and "^" not in s and "-USD" not in s:
                out.append(s.upper())
    return out


EXCHANGE = re.compile(r"\((?:NASDAQ|NYSE|NYSEMKT|NYSE ?AMERICAN|NYSE ?ARCA|AMEX|CBOE|TSX|TSXV|OTC|OTCQX)\s*:\s*"
                      r"([A-Z][A-Z0-9.\-]{0,6})\)")
CASHTAG = re.compile(r"(?<![\w$])\$([A-Z]{1,5})(?![\w])")
TSX_TAG = re.compile(r"\((?:TSX|TSXV)\s*:\s*([A-Z][A-Z0-9.\-]{0,6})\)")


def tickers_in(text):
    """Tickers named the way articles name them: '(NASDAQ: NVDA)', '(TSX: RY)', '$TSLA'."""
    out = []
    for m in EXCHANGE.finditer(text or ""):
        t = m.group(1).replace(".", "-")
        out.append(t + (".TO" if "(TSX:" in m.group(0).replace(" ", "") else ".V" if "TSXV" in m.group(0) else ""))
    out += CASHTAG.findall(text or "")
    return out


def rss_text(xml_bytes):
    """Titles and descriptions of every item in an RSS or Atom feed."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("item", "entry"):
            parts = [(c.text or "") for c in el if c.tag.split("}")[-1] in ("title", "description", "summary")]
            out.append(re.sub(r"<[^>]+>", " ", " ".join(parts)))
    return out


FOOL_QUOTE = re.compile(r"/quote/(nasdaq|nyse|nysemkt|nyseamerican|tsx)/([a-z0-9.\-]{1,8})/", re.I)


def fool_tickers(html):
    """Motley Fool pages link every company they mention as /quote/<exchange>/<ticker>/."""
    out = []
    for ex, t in FOOL_QUOTE.findall(html or ""):
        out.append(t.upper().replace(".", "-") + (".TO" if ex.lower() == "tsx" else ""))
    return out + tickers_in(re.sub(r"<[^>]+>", " ", html or ""))


def parse_apewisdom(doc):
    return [{"symbol": r["ticker"].upper(), "mentions": int(r.get("mentions") or 0), "rank": r.get("rank")}
            for r in (doc or {}).get("results", []) if r.get("ticker")]


# ---------------------------------------------------------------- snapshot

def _json(url, ua=UA):
    return json.loads(fetch(url, ua).decode("utf-8", "replace"))


def gather(only=None, sec_ua=None, http=None, log=print):
    """{source: {"symbols": [...], "detail": {...}} or {"error": "..."}}."""
    get = http or (lambda url, ua=UA: fetch(url, ua))
    js = (lambda url, ua=UA: json.loads(get(url, ua).decode("utf-8", "replace")))
    out = {}

    def run(name, fn):
        if only and name not in only:
            return
        try:
            out[name] = fn()
            log("%-12s %d symbols" % (name, len(out[name]["symbols"])))
        except (DiscoverError, ValueError, KeyError, ET.ParseError) as e:
            out[name] = {"symbols": [], "error": str(e)[:300]}
            log("%-12s failed: %s" % (name, str(e)[:120]))

    def listed_us():
        rows = parse_symdir(get(URLS["nasdaq_listed"]).decode("latin-1"), "nasdaq") + \
            parse_symdir(get(URLS["other_listed"]).decode("latin-1"), "other")
        return {"symbols": sorted({s for s, _ in rows}), "detail": {"names": dict(rows)}}

    def listed_tsx():
        return {"symbols": sorted(set(parse_tmx(js(URLS["tsx"]), ".TO") + parse_tmx(js(URLS["tsxv"]), ".V")))}

    def sec():
        if not sec_ua:
            raise DiscoverError("no SEC user agent (SEC_USER_AGENT)")
        return {"symbols": parse_sec_tickers(js(URLS["sec_tickers"], sec_ua))}

    def index_funds():
        hold = {}
        for fund, (pid, slug) in ISHARES.items():
            try:
                hold[fund] = parse_ishares(get(URLS["ishares"] % (pid, slug, fund)).decode("utf-8", "replace"))
            except DiscoverError as e:
                hold[fund] = []
                log("  %s holdings: %s" % (fund, e))
        if not any(hold.values()):
            raise DiscoverError("every iShares holdings file failed")
        return {"symbols": sorted({t for v in hold.values() for t in v}), "detail": {k: len(v) for k, v in hold.items()}}

    def trending():
        return {"symbols": parse_yahoo_quotes(js(URLS["yahoo_trending"]))}

    def screens():
        detail = {}
        for scr in SCREENS:
            try:
                detail[scr] = parse_yahoo_quotes(js(URLS["yahoo_screen"] % scr))
            except (DiscoverError, ValueError) as e:
                detail[scr] = []
                log("  screen %s: %s" % (scr, e))
        if not any(detail.values()):
            raise DiscoverError("every Yahoo screen failed")
        return {"symbols": sorted({s for v in detail.values() for s in v}), "detail": detail}

    def news():
        counts = {}
        feeds = [URLS["yahoo_news"]] + [URLS["google_news"] % q.replace(" ", "+") for q in NEWS_QUERIES]
        for url in feeds:
            try:
                for text in rss_text(get(url)):
                    for t in tickers_in(text):
                        counts[t] = counts.get(t, 0) + 1
            except DiscoverError as e:
                log("  news feed: %s" % e)
        return {"symbols": sorted(counts, key=lambda t: -counts[t]), "detail": {"mentions": counts}}

    def fool():
        counts, last = {}, None
        for url in URLS["fool"]:
            try:
                for t in fool_tickers(get(url).decode("utf-8", "replace")):
                    counts[t] = counts.get(t, 0) + 1
            except DiscoverError as e:
                last = e
        if not counts and last:
            raise last
        return {"symbols": sorted(counts, key=lambda t: -counts[t]), "detail": {"mentions": counts}}

    def reddit():
        rows = []
        for page in (1, 2):
            rows += parse_apewisdom(js(URLS["apewisdom"] % page))
        return {"symbols": list(dict.fromkeys(r["symbol"] for r in rows)),
                "detail": {"mentions": {r["symbol"]: r["mentions"] for r in rows}}}

    for name, fn in (("listed_us", listed_us), ("listed_tsx", listed_tsx), ("sec", sec), ("index_funds", index_funds),
                     ("trending", trending), ("screens", screens), ("news", news), ("fool", fool), ("reddit", reddit)):
        run(name, fn)
    return out


def save_snapshot(base, sources, day=None):
    day = day or datetime.date.today().isoformat()
    folder = os.path.join(base, "discover", "archive")
    os.makedirs(folder, exist_ok=True)
    doc = {"date": day, "sources": sources}
    path = os.path.join(folder, "%s.json.gz" % day)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    return path


def load_snapshot(base, day=None):
    folder = os.path.join(base, "discover", "archive")
    names = sorted(f for f in os.listdir(folder) if f.endswith(".json.gz")) if os.path.isdir(folder) else []
    if day:
        names = [f for f in names if f[:10] <= day]
    if not names:
        return None
    with gzip.open(os.path.join(folder, names[-1]), "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- funnel

def candidates(snap, deep=False):
    """{symbol: [sources]}: the idea lists (and, deep, the whole market). When the snapshot has
    the exchange listings, idea-list symbols must be real listed stocks or funds there (pages
    and posts contain look-alike codes)."""
    srcs = (snap or {}).get("sources", {})
    listed = set()
    for name in ("listed_us", "listed_tsx"):
        listed |= set((srcs.get(name) or {}).get("symbols", []))
    funds = set((srcs.get("trending") or {}).get("symbols", [])) | set((srcs.get("screens") or {}).get("symbols", []))
    out = {}
    for name, src in srcs.items():
        if name in IDEAS or (deep and name in MARKET):
            for s in dict.fromkeys(src.get("symbols", [])):
                if name in IDEAS and listed and s not in listed and s not in funds:
                    continue
                out.setdefault(s, []).append(name)
    return out


def score(m):
    """Liquid (over $5M a day), over $5, above its 200-day average; ranked by 12-month return
    with the last month left out, the momentum that has held up in research."""
    if not m or not m.get("price") or m["price"] < 5 or not m.get("above_sma200"):
        return None
    if (m.get("dollar_volume") or 0) < 5e6:
        return None
    r12, r1 = m.get("ret_12m"), m.get("ret_1m")
    if r12 is None or r1 is None:
        return None
    return round((1 + r12 / 100.0) / (1 + r1 / 100.0) * 100 - 100, 2)


def funnel(snap, deep=False, offline=None, top=30, log=print, pause=0.15):
    pool = candidates(snap, deep)
    log("funnel: %d candidates%s" % (len(pool), " (whole market)" if deep else ""))
    rows, errors = [], 0
    for i, (sym, srcs) in enumerate(sorted(pool.items())):
        try:
            ch = mk.get_chart(sym, offline=offline, range_="2y")  # 12-month momentum needs a bit over a year
        except mk.MarketError:
            errors += 1
            continue
        m = mk.metrics(ch)
        bars = ch["bars"][-20:]
        m["dollar_volume"] = sum(b["c"] * (b.get("v") or 0) for b in bars) / len(bars) if bars else 0
        sc = score(m)
        if sc is not None:
            ideas = [s for s in srcs if s in IDEAS]
            rows.append({"symbol": sym, "name": m.get("name", ""), "momentum_12_1": sc, "sources": ideas or srcs,
                         "price": m["price"], "currency": m["currency"], "ret_1m": m["ret_1m"],
                         "dollar_volume_m": round(m["dollar_volume"] / 1e6, 1)})
        if pause and not offline:
            time.sleep(pause)
        if i % 500 == 499:
            log("  %d of %d" % (i + 1, len(pool)))
    rows.sort(key=lambda r: (-len(r["sources"]), -r["momentum_12_1"]) if not deep else -r["momentum_12_1"])
    return {"date": snap.get("date"), "deep": deep, "candidates": len(pool), "passed": len(rows),
            "no_data": errors, "ideas": rows[:top],
            "note": "Leads, not advice: liquid, above the 200-day average, ranked by 12-1 month momentum."}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Where stock ideas come from: snapshot the sources, rank the ideas.")
    ap.add_argument("--dir", default="trader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--only", help="comma list of: %s" % ", ".join(MARKET + IDEAS))
    s.add_argument("--json", action="store_true")
    f = sub.add_parser("funnel")
    f.add_argument("--deep", action="store_true", help="the whole market, not just the idea lists")
    f.add_argument("--top", type=int, default=30)
    f.add_argument("--offline", metavar="DIR")
    f.add_argument("--json", action="store_true")
    sub.add_parser("show")
    a = ap.parse_args(argv)
    if a.cmd == "snapshot":
        only = set(a.only.split(",")) if a.only else None
        ua = os.environ.get("SEC_USER_AGENT") or (mk_cfg_ua(a.dir))
        src = gather(only, sec_ua=ua, log=(lambda m: None) if a.json else print)
        path = save_snapshot(a.dir, src)
        if a.json:
            print(json.dumps({"saved": path, "counts": {k: len(v.get("symbols", [])) for k, v in src.items()},
                              "errors": {k: v["error"] for k, v in src.items() if v.get("error")}}))
        else:
            print("saved %s" % path)
        return 0 if any(v.get("symbols") for v in src.values()) else 3
    snap = load_snapshot(a.dir)
    if not snap:
        print("discover: no snapshot yet: run `discover.py snapshot` first", file=sys.stderr)
        return 2
    if a.cmd == "funnel":
        out = funnel(snap, a.deep, a.offline, a.top, log=(lambda m: None) if a.json else print)
        path = os.path.join(a.dir, "discover", "ideas.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        if a.json:
            print(json.dumps(out))
            return 0
        for r in out["ideas"]:
            print("%-8s %+7.1f%%  %-28s %s" % (r["symbol"], r["momentum_12_1"], ", ".join(r["sources"]), r["name"][:30]))
        print(out["note"])
        return 0
    for name, v in snap["sources"].items():
        print("%-12s %5d %s" % (name, len(v.get("symbols", [])), v.get("error", "")))
    return 0


def mk_cfg_ua(base):
    try:
        with open(os.path.join(base, "config.json"), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("sec_user_agent")
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
