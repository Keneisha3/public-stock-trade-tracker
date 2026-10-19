"""Candles: 15-minute price bars for the coins, and the .env key loader.

Two free sources, no paid plan needed:
  coinbase  https://api.exchange.coinbase.com/products/BTC-USD/candles  (no key at all)
  alpaca    https://data.alpaca.markets/v1beta3/crypto/us/bars          (keys optional)

A bar is {"t": start time in epoch seconds, "o", "h", "l", "c", "v"}.
Only CLOSED bars are used for decisions: a bar that is still forming
would change after the bot acted on it.
"""

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; public-stock-trade-tracker/1.0)"
COINBASE = "https://api.exchange.coinbase.com/products/%s-USD/candles?granularity=%d&start=%s&end=%s"
ALPACA_BARS = "https://data.alpaca.markets/v1beta3/crypto/us/bars"


class DataError(Exception):
    pass


# ---------------------------------------------------------------- .env

def load_env(*paths):
    """Read KEY=value lines from the first .env file found. Never prints values.
    Variables already set in the shell win over the file."""
    for path in paths:
        if path and os.path.isfile(path):
            out = {}
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip().replace("export ", "")
                    v = v.strip().strip('"').strip("'")
                    out[k] = os.environ.get(k, v)
            for k, v in os.environ.items():
                if k.startswith(("PAPER_", "TRADING_MODE", "APCA_")):
                    out[k] = v
            return out, path
    return {k: v for k, v in os.environ.items() if k.startswith(("PAPER_", "TRADING_MODE", "APCA_"))}, None


def mask(secret):
    s = str(secret or "")
    return (s[:2] + "..." + s[-2:]) if len(s) > 6 else "***"


# ---------------------------------------------------------------- HTTP

def http_json(url, headers=None, data=None, method="GET", timeout=20):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=h, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        raise DataError("%s answered HTTP %d %s" % (url.split("?")[0], e.code, detail))
    except urllib.error.URLError as e:
        raise DataError("could not reach %s: %s" % (url.split("/")[2], e.reason))
    except ValueError:
        raise DataError("%s did not return JSON" % url.split("?")[0])


def _iso(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(text):
    return int(datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=datetime.timezone.utc).timestamp())


# ---------------------------------------------------------------- sources

def fetch_coinbase(coin, start, end, interval_min=15, http=http_json, pause=0.15):
    """Coinbase gives at most 300 candles a call, newest first: page through the window."""
    step = 300 * interval_min * 60
    bars, t = {}, int(start)
    while t < end:
        stop = min(end, t + step)
        for attempt in range(3):
            try:
                rows = http(COINBASE % (coin, interval_min * 60, _iso(t), _iso(stop)))
                break
            except DataError as e:
                if attempt == 2 or not any(code in str(e) for code in ("429", "HTTP 5")):
                    raise
                time.sleep(2 + 3 * attempt)  # Coinbase throttles bursts: back off and retry
        if isinstance(rows, dict):
            raise DataError("Coinbase: %s" % rows.get("message", "unexpected answer for %s" % coin))
        for r in rows:  # [time, low, high, open, close, volume]
            bars[int(r[0])] = {"t": int(r[0]), "o": float(r[3]), "h": float(r[2]), "l": float(r[1]),
                               "c": float(r[4]), "v": float(r[5])}
        t = stop
        if pause and t < end:
            time.sleep(pause)
    return [bars[k] for k in sorted(bars)]


def _timeframe(interval_min):
    """Alpaca's names: 15Min, 1Hour, 6Hour, 1Day."""
    if interval_min % 1440 == 0:
        return "%dDay" % (interval_min // 1440)
    if interval_min % 60 == 0:
        return "%dHour" % (interval_min // 60)
    return "%dMin" % interval_min


def fetch_alpaca(coins, start, end, interval_min=15, http=http_json, keys=None):
    headers = {}
    if keys and keys.get("PAPER_API_KEY") and keys.get("PAPER_API_SECRET"):
        headers = {"APCA-API-KEY-ID": keys["PAPER_API_KEY"], "APCA-API-SECRET-KEY": keys["PAPER_API_SECRET"]}
    out = {c: [] for c in coins}
    token = None
    while True:
        q = {"symbols": ",".join("%s/USD" % c for c in coins), "timeframe": _timeframe(interval_min),
             "start": _iso(start), "end": _iso(end), "limit": 10000, "sort": "asc"}
        if token:
            q["page_token"] = token
        doc = http(ALPACA_BARS + "?" + urllib.parse.urlencode(q), headers=headers)
        for sym, rows in (doc.get("bars") or {}).items():
            c = sym.split("/")[0]
            for r in rows:
                out.setdefault(c, []).append({"t": _epoch(r["t"]), "o": float(r["o"]), "h": float(r["h"]),
                                              "l": float(r["l"]), "c": float(r["c"]), "v": float(r.get("v", 0))})
        token = doc.get("next_page_token")
        if not token:
            break
    return out


def fetch(coins, source, start, end, interval_min=15, http=http_json, keys=None):
    """({coin: bars}, [errors]). One bad coin never stops the others."""
    errors, out = [], {}
    if source == "alpaca":
        try:
            got = fetch_alpaca(coins, start, end, interval_min, http=http, keys=keys)
        except DataError as e:
            return {}, [str(e)]
        for c in coins:
            if got.get(c):
                out[c] = got[c]
            else:
                errors.append("no Alpaca bars for %s/USD (not listed there?)" % c)
        return out, errors
    for c in coins:
        try:
            out[c] = fetch_coinbase(c, start, end, interval_min, http=http)
            if not out[c]:
                errors.append("no Coinbase candles for %s-USD" % c)
                del out[c]
        except DataError as e:
            errors.append(str(e))
    return out, errors


def closed_only(bars, now, interval_min=15):
    """Drop the bar that is still forming."""
    return [b for b in bars if b["t"] + interval_min * 60 <= now]
