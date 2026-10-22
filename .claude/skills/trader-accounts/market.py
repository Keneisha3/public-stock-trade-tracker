#!/usr/bin/env python3
"""Market data for trader-accounts and trader-paper. Standard library only.

One request per symbol to Yahoo's free chart endpoint gives five years of
daily bars plus every dividend paid:

    https://query1.finance.yahoo.com/v8/finance/chart/ENB.TO?range=5y&interval=1d&events=div

From that this module works out what the account review needs: price, day
change, 1/3/6/12-month returns, distance from the 52-week high, the 200-day
average, annualised volatility, trailing-twelve-month dividends, dividend
growth and dividend cuts. FX (USD->CAD) comes from the same endpoint
(symbol USDCAD=X).

    python3 market.py ENB.TO AAPL --offline DIR      # print metrics
    python3 market.py ENB.TO --json
    python3 market.py VST --save DIR                 # also keep the raw charts, for --offline DIR later

Offline: --offline DIR reads DIR/chart-<SYMBOL>.json instead of the network
(the tests use it). Quotes are delayed and unofficial: good for a daily
review, never for placing an order.
"""

import argparse
import datetime
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; public-stock-trade-tracker/1.0)"
PAUSE = 0.4  # seconds between requests
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d&events=div"
# range=max quietly returns MONTHLY bars; dates give daily bars as far back as Yahoo has them
CHART_SINCE = "https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d&events=div"

# exchange (or MIC) -> Yahoo suffix
SUFFIX = {
    "TSX": ".TO", "XTSE": ".TO", "TSE": ".TO", "TO": ".TO",
    "TSXV": ".V", "TSX-V": ".V", "XTSX": ".V", "VN": ".V", "V": ".V", "CDNX": ".V",
    "NEO": ".NE", "NEOE": ".NE", "CBOE CANADA": ".NE", "CBOE CA": ".NE", "NE": ".NE",
    "CSE": ".CN", "XCNQ": ".CN", "CNSX": ".CN", "CN": ".CN",
}
CAD_SUFFIXES = (".TO", ".V", ".NE", ".CN")


class MarketError(Exception):
    pass


def yahoo_symbol(symbol, exchange=None):
    """Broker symbol (+ exchange) -> Yahoo symbol.

    BNS.TO -> BNS.TO, SHOP + TSX -> SHOP.TO, CTC.A + TSX -> CTC-A.TO,
    BRK.B -> BRK-B, XYZ.VN (Questrade's TSXV) -> XYZ.V.
    """
    s = str(symbol or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    if s.endswith("=X") or s.startswith("^"):
        return s
    suffix = ""
    for known in ("TO", "V", "VN", "NE", "CN"):
        if s.endswith("." + known):
            s, suffix = s[:-(len(known) + 1)], SUFFIX[known]
            break
    if not suffix and exchange:
        suffix = SUFFIX.get(str(exchange).strip().upper(), "")
    return s.replace(".", "-") + suffix


def native_currency(symbol):
    return "CAD" if str(symbol).upper().endswith(CAD_SUFFIXES) else "USD"


RETRY_WAITS = (3, 10)  # seconds before the 2nd and 3rd try when Yahoo throttles or hiccups
# Where Yahoo is blocked (a cloud session's network policy), charts fetched by the GitHub "prices"
# workflow mode are read from the public replay-results branch instead. MARKET_MIRROR="" turns it off.
MIRROR = os.environ.get("MARKET_MIRROR", "https://raw.githubusercontent.com/Keneisha3/public-stock-trade-tracker/"
                        "replay-results/prices/chart-%s.json")
_blocked = []  # set once Yahoo cannot be reached, so the next symbols go straight to the mirror


def fetch(url, timeout=25):
    """GET with retries on 429 / 5xx / network errors; query1 falls back to query2."""
    urls = [url, url.replace("//query1.", "//query2.")] if "//query1." in url else [url]
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt:
            time.sleep(RETRY_WAITS[attempt - 1])
        u = urls[min(attempt, len(urls) - 1)]
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = MarketError("%s answered HTTP %d" % (u.split("?")[0], e.code))
            if e.code != 429 and e.code < 500 and e.code != 403:
                raise last  # a real "no such symbol": retrying will not help
        except (urllib.error.URLError, OSError) as e:
            last = MarketError("could not reach %s: %s" % (u.split("/")[2], getattr(e, "reason", e)))
            if "Tunnel connection failed: 403" in str(last):
                raise last  # a network policy blocks the host: retrying will not help
    raise last


def _date(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date().isoformat()


def parse_chart(text, symbol):
    """Yahoo chart JSON -> {symbol, name, currency, price, time, bars, dividends}."""
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise MarketError("Yahoo returned something unexpected for %s" % symbol)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise MarketError("Yahoo has no data for %s: %s" % (symbol, err.get("description", "unknown symbol")))
    r = res[0]
    meta = r.get("meta", {})
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        def col(k):
            v = (q.get(k) or [None] * (i + 1))
            return v[i] if i < len(v) else None
        c = col("close")
        if c is None:
            continue
        o, h, l = col("open"), col("high"), col("low")
        bars.append({"d": _date(ts), "o": o if o is not None else c, "h": h if h is not None else c,
                     "l": l if l is not None else c, "c": c, "v": col("volume") or 0})
    divs = []
    for ev in ((r.get("events") or {}).get("dividends") or {}).values():
        if ev.get("amount") is not None and ev.get("date") is not None:
            divs.append((_date(ev["date"]), float(ev["amount"])))
    divs.sort()
    price = meta.get("regularMarketPrice")
    if price is None and bars:
        price = bars[-1]["c"]
    if price is None:
        raise MarketError("Yahoo has no price for %s" % symbol)
    t = meta.get("regularMarketTime")
    return {"symbol": symbol.upper(), "name": meta.get("longName") or meta.get("shortName") or "",
            "currency": (meta.get("currency") or native_currency(symbol)).upper(),
            "price": float(price), "time": _date(t) if t else (bars[-1]["d"] if bars else ""),
            "bars": bars, "dividends": divs}


EODHD = "https://eodhd.com/api/%s/%s.US?api_token=%s&fmt=json&from=%s"


def parse_eodhd(eod, divs, symbol):
    """EODHD end-of-day and dividend JSON -> the same chart dict as parse_chart. Paid data that
    includes companies no longer listed (Yahoo drops them), for an honest backtest."""
    bars = []
    for r in eod or []:
        try:
            c = float(r["close"])
            bars.append({"d": r["date"], "o": float(r.get("open") or c), "h": float(r.get("high") or c),
                         "l": float(r.get("low") or c), "c": c, "v": float(r.get("volume") or 0)})
        except (KeyError, TypeError, ValueError):
            continue
    if not bars:
        raise MarketError("EODHD has no prices for %s" % symbol)
    bars.sort(key=lambda b: b["d"])
    dv = sorted((d["date"], float(d.get("unadjustedValue") or d.get("value") or 0)) for d in (divs or [])
                if d.get("date"))
    return {"symbol": symbol.upper(), "name": "", "currency": "USD", "price": bars[-1]["c"], "time": bars[-1]["d"],
            "bars": bars, "dividends": [x for x in dv if x[1] > 0]}


def get_chart_eodhd(symbol, key, since="2014-01-01", http=None):
    """US symbols only. The key never appears in an error message."""
    get = http or (lambda url: fetch(url))
    sym = symbol.upper().replace("-", ".")
    try:
        eod = json.loads(get(EODHD % ("eod", sym, key, since)))
        try:
            divs = json.loads(get(EODHD % ("div", sym, key, since)))
        except (MarketError, ValueError):
            divs = []
    except (MarketError, ValueError) as e:
        raise MarketError(str(e).replace(key, "***") if key else str(e))
    return parse_eodhd(eod, divs, symbol)


def get_chart(symbol, offline=None, range_="5y", save=None):
    """One Yahoo chart. offline: read DIR/chart-SYM.json instead. save: also write the raw
    answer there, so a later run can use it with offline=DIR. When Yahoo cannot be reached at all,
    the copy the GitHub "prices" job saved (MIRROR) is used, marked chart["mirror"] = True: its
    last bar shows how old it is."""
    mirrored = False
    if offline:
        path = os.path.join(offline, "chart-%s.json" % symbol.upper())
        if not os.path.exists(path):
            raise MarketError("no offline chart file %s" % path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        try:
            if _blocked and MIRROR and range_ != "max":
                raise _blocked[0]
            if range_ == "max":  # every daily bar since 1990
                text = fetch(CHART_SINCE % (urllib.parse.quote(symbol.upper()), 631152000, int(time.time())))
            else:
                text = fetch(CHART % (urllib.parse.quote(symbol.upper()), range_))
        except MarketError as e:
            if not (MIRROR and range_ != "max" and "could not reach" in str(e)):
                raise
            if not _blocked:
                _blocked.append(e)
            try:
                text = fetch(MIRROR % urllib.parse.quote(symbol.upper()))
            except MarketError:
                raise MarketError("%s; no saved copy of %s either: run the GitHub replay workflow in "
                                  "mode 'prices' with tickers '%s'" % (e, symbol.upper(), symbol.upper()))
            mirrored = True
    chart = parse_chart(text, symbol)
    if mirrored:
        chart["mirror"] = True
    if save:
        os.makedirs(save, exist_ok=True)
        with open(os.path.join(save, "chart-%s.json" % symbol.upper()), "w", encoding="utf-8") as fh:
            fh.write(text)
    return chart


# ---------------------------------------------------------------- metrics

def _ret(closes, n):
    if len(closes) <= n or not closes[-1 - n]:
        return None
    return 100.0 * (closes[-1] / closes[-1 - n] - 1)


def _sum_divs(divs, start, end):
    return sum(a for d, a in divs if start < d <= end)


def _days_before(day, n):
    return (datetime.date.fromisoformat(day) - datetime.timedelta(days=n)).isoformat()


def stretch(closes):
    """How far a stock has run, from closes up to today (oldest first): {"above_sma200_pct": % above
    the 200-day average, "vol_1m_pct" and "vol_1y_pct": annualised volatility over 21 and 252 days,
    "vol_ratio": the two divided, "ret_1m", "ret_3m": %}. None where history is too short. Pure: the
    review and the stretch test (trader-replay/stretch.py) both use it."""
    out = {"above_sma200_pct": None, "vol_1m_pct": None, "vol_1y_pct": None, "vol_ratio": None,
           "ret_1m": _r(_ret(closes, 21)), "ret_3m": _r(_ret(closes, 63))}
    if len(closes) >= 200 and closes[-1]:
        sma = sum(closes[-200:]) / 200.0
        out["above_sma200_pct"] = _r(100.0 * (closes[-1] / sma - 1)) if sma else None
    rets = [math.log(b / a) for a, b in zip(closes[-253:-1], closes[-252:]) if a and b]
    if len(rets) >= 200:
        v1y = statistics.pstdev(rets) * math.sqrt(252)
        v1m = statistics.pstdev(rets[-21:]) * math.sqrt(252)
        out.update(vol_1m_pct=_r(100 * v1m), vol_1y_pct=_r(100 * v1y), vol_ratio=_r(v1m / v1y) if v1y else None)
    return out


STRETCH_SIGNALS = {  # rule v15: "sell when it gets really high, or volatility rises on the way up"
    "X1": "50%+ above its 200-day average",
    "X2": "up 25%+ in a month with volatility 1.5x its usual",
    "X3": "30%+ above its 200-day, volatility 1.5x its usual, and rising",
    "X4": "up 60%+ in 3 months",
}


def stretch_signals(s):
    """Which of STRETCH_SIGNALS fire for a stretch() result."""
    a, v, r1, r3 = s.get("above_sma200_pct"), s.get("vol_ratio"), s.get("ret_1m"), s.get("ret_3m")
    out = []
    if a is not None and a >= 50:
        out.append("X1")
    if r1 is not None and v is not None and r1 >= 25 and v >= 1.5:
        out.append("X2")
    if a is not None and v is not None and r1 is not None and a >= 30 and v >= 1.5 and r1 > 0:
        out.append("X3")
    if r3 is not None and r3 >= 60:
        out.append("X4")
    return out


def metrics(chart, today=None):
    """Everything the review needs, from one chart. Pure function."""
    bars = chart["bars"]
    closes = [b["c"] for b in bars]
    price = chart["price"]
    if closes:
        closes = closes[:-1] + [price] if bars[-1]["d"] == chart["time"] else closes + [price]
    today = today or chart["time"] or datetime.date.today().isoformat()
    prev = closes[-2] if len(closes) >= 2 else None
    last_year = closes[-252:]
    high = max(last_year) if last_year else price
    low = min(last_year) if last_year else price
    sma200 = sum(closes[-200:]) / len(closes[-200:]) if len(closes) >= 50 else None
    vol = None
    rets = [math.log(b / a) for a, b in zip(closes[-253:-1], closes[-252:]) if a and b]
    if len(rets) >= 40:
        vol = 100.0 * statistics.pstdev(rets) * math.sqrt(252)
    divs = chart.get("dividends") or []
    ttm = _sum_divs(divs, _days_before(today, 365), today)
    prev_ttm = _sum_divs(divs, _days_before(today, 730), _days_before(today, 365))
    old_ttm = _sum_divs(divs, _days_before(today, 1460), _days_before(today, 1095))
    growth3 = None
    if ttm > 0 and old_ttm > 0:
        growth3 = 100.0 * ((ttm / old_ttm) ** (1 / 3.0) - 1)
    recent = [a for d, a in divs if d > _days_before(today, 730)]
    cut_pct = None
    if len(recent) >= 3:
        before = statistics.median(recent[-5:-1])  # median ignores a one-off special
        if before > 0 and recent[-1] < before:
            cut_pct = 100.0 * (1 - recent[-1] / before)
    # a cut more than a few payments ago shows in the yearly totals instead; count it only when
    # the total AND the average payment both fell, so a schedule change (quarterly -> monthly)
    # or a payment landing a few days late is not a "cut"
    n_ttm = len([1 for d, a in divs if _days_before(today, 365) < d <= today])
    n_prev = len([1 for d, a in divs if _days_before(today, 730) < d <= _days_before(today, 365)])
    if ttm > 0 and prev_ttm > 0 and n_ttm and n_prev:
        drop_total = 1 - ttm / prev_ttm
        drop_each = 1 - (ttm / n_ttm) / (prev_ttm / n_prev)
        yearly = 100.0 * min(drop_total, drop_each)
        if yearly > 0 and (cut_pct is None or yearly > cut_pct):
            cut_pct = yearly
    last_div = divs[-1][0] if divs else None
    return {
        "symbol": chart["symbol"], "name": chart.get("name", ""), "currency": chart["currency"],
        "price": round(price, 4), "time": chart["time"],
        "prev_close": round(prev, 4) if prev else None,
        "day_pct": round(100.0 * (price / prev - 1), 2) if prev else None,
        "ret_1m": _r(_ret(closes, 21)), "ret_3m": _r(_ret(closes, 63)),
        "ret_6m": _r(_ret(closes, 126)), "ret_12m": _r(_ret(closes, 252)),
        "high_52w": round(high, 4), "low_52w": round(low, 4),
        "off_high_pct": _r(100.0 * (price / high - 1)) if high else None,
        "sma200": round(sma200, 4) if sma200 else None,
        "above_sma200": (price > sma200) if sma200 else None,
        "vol_pct": _r(vol),
        "stretch": stretch(closes),
        "div_ttm": round(ttm, 4), "div_prev_ttm": round(prev_ttm, 4),
        "yield_pct": _r(100.0 * ttm / price) if price and ttm else 0.0,
        "div_growth_3y_pct": _r(growth3),
        "div_cut_pct": _r(cut_pct), "div_payments_ttm": len([1 for d, a in divs if d > _days_before(today, 365)]),
        "last_div_date": last_div,
        "spark": [round(c, 4) for c in closes[-252::5]],  # about one point a week for a year
    }


def _r(x, n=2):
    return None if x is None else round(x, n)


def refresh(symbols, offline=None, today=None, pause=PAUSE, fx_pairs=("USDCAD=X",), save=None):
    """{symbols: {SYM: metrics}, fx: {USDCAD: rate}, errors: [...]}"""
    out, errors, fx = {}, [], {}
    todo = [s for s in dict.fromkeys(s.upper() for s in symbols if s)]
    for i, sym in enumerate(list(todo) + list(fx_pairs)):
        if i and pause and not offline:
            time.sleep(pause)
        try:
            ch = get_chart(sym, offline=offline, range_="1mo" if sym.endswith("=X") else "5y", save=save)
        except MarketError as e:
            errors.append(str(e))
            continue
        if sym.endswith("=X"):
            fx[sym[:-2]] = round(ch["price"], 6)
        else:
            out[sym] = metrics(ch, today=today)
    return {"symbols": out, "fx": fx, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Daily market metrics from Yahoo's free chart data.")
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--today")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", metavar="DIR", help="also write each raw chart to DIR/chart-SYM.json")
    a = ap.parse_args(argv)
    res = refresh(a.symbols, offline=a.offline, today=a.today, fx_pairs=(), save=a.save)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for s, m in res["symbols"].items():
            print("%-8s %10.2f %s  day %s%%  12m %s%%  yield %s%%  vol %s%%" % (
                s, m["price"], m["currency"], m["day_pct"], m["ret_12m"], m["yield_pct"], m["vol_pct"]))
        for e in res["errors"]:
            print("note: " + e, file=sys.stderr)
    return 0 if res["symbols"] else 1


if __name__ == "__main__":
    sys.exit(main())
