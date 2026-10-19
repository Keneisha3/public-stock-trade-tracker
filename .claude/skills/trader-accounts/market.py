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


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise MarketError("%s answered HTTP %d" % (url.split("?")[0], e.code))
    except urllib.error.URLError as e:
        raise MarketError("could not reach %s: %s" % (url.split("/")[2], e.reason))


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


def get_chart(symbol, offline=None, range_="5y"):
    if offline:
        path = os.path.join(offline, "chart-%s.json" % symbol.upper())
        if not os.path.exists(path):
            raise MarketError("no offline chart file %s" % path)
        with open(path, encoding="utf-8") as fh:
            return parse_chart(fh.read(), symbol)
    return parse_chart(fetch(CHART % (urllib.parse.quote(symbol.upper()), range_)), symbol)


# ---------------------------------------------------------------- metrics

def _ret(closes, n):
    if len(closes) <= n or not closes[-1 - n]:
        return None
    return 100.0 * (closes[-1] / closes[-1 - n] - 1)


def _sum_divs(divs, start, end):
    return sum(a for d, a in divs if start < d <= end)


def _days_before(day, n):
    return (datetime.date.fromisoformat(day) - datetime.timedelta(days=n)).isoformat()


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
        "div_ttm": round(ttm, 4), "div_prev_ttm": round(prev_ttm, 4),
        "yield_pct": _r(100.0 * ttm / price) if price and ttm else 0.0,
        "div_growth_3y_pct": _r(growth3),
        "div_cut_pct": _r(cut_pct), "div_payments_ttm": len([1 for d, a in divs if d > _days_before(today, 365)]),
        "last_div_date": last_div,
        "spark": [round(c, 4) for c in closes[-252::5]],  # about one point a week for a year
    }


def _r(x, n=2):
    return None if x is None else round(x, n)


def refresh(symbols, offline=None, today=None, pause=PAUSE, fx_pairs=("USDCAD=X",)):
    """{symbols: {SYM: metrics}, fx: {USDCAD: rate}, errors: [...]}"""
    out, errors, fx = {}, [], {}
    todo = [s for s in dict.fromkeys(s.upper() for s in symbols if s)]
    for i, sym in enumerate(list(todo) + list(fx_pairs)):
        if i and pause and not offline:
            time.sleep(pause)
        try:
            ch = get_chart(sym, offline=offline, range_="1mo" if sym.endswith("=X") else "5y")
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
    a = ap.parse_args(argv)
    res = refresh(a.symbols, offline=a.offline, today=a.today, fx_pairs=())
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
