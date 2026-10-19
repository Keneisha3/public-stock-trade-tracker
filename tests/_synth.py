"""Synthetic Yahoo chart JSON for offline tests (deterministic, no network)."""

import datetime
import json
import math
import os

END = datetime.date(2026, 10, 16)  # a Friday


def trading_days(n, end=END):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= datetime.timedelta(days=1)
    return days[::-1]


def _ts(d):
    return int(datetime.datetime(d.year, d.month, d.day, 20, 0, tzinfo=datetime.timezone.utc).timestamp())


def chart(symbol, p0=100.0, growth=0.0, wiggle=0.01, currency="USD", n=1260, divs=None,
          name=None, end=END, gaps=None):
    """growth: total log-return over the n days; wiggle: daily +/- swing.

    divs: list of (date_iso, amount). gaps: {day_index: pct} lasting jumps
    (a gap of +8 lifts that close and every later one by 8%, like a breakout).
    """
    days = trading_days(n, end)
    closes, opens, highs, lows = [], [], [], []
    shift = 1.0
    for i, d in enumerate(days):
        base = p0 * math.exp(growth * i / max(n - 1, 1))
        if gaps and i in gaps:
            shift *= 1 + gaps[i] / 100.0
        c = base * shift * (1 + wiggle * math.sin(i * 1.3))
        o = closes[-1] if closes else c
        closes.append(round(c, 4))
        opens.append(round(o, 4))
        highs.append(round(max(o, c) * (1 + wiggle / 2), 4))
        lows.append(round(min(o, c) * (1 - wiggle / 2), 4))
    events = {}
    for d, amt in divs or []:
        dd = datetime.date.fromisoformat(d)
        events[str(_ts(dd))] = {"amount": amt, "date": _ts(dd)}
    return {"chart": {"result": [{
        "meta": {"currency": currency, "symbol": symbol, "regularMarketPrice": closes[-1],
                 "regularMarketTime": _ts(days[-1]), "longName": name or symbol},
        "timestamp": [_ts(d) for d in days],
        "events": {"dividends": events} if events else {},
        "indicators": {"quote": [{"open": opens, "high": highs, "low": lows, "close": closes,
                                  "volume": [1000000] * len(days)}]}}], "error": None}}


def quarterly(start, end, amount, step=0.0):
    """Quarterly dividends from start to end (iso dates), growing by step each payment."""
    out, d, a = [], datetime.date.fromisoformat(start), amount
    stop = datetime.date.fromisoformat(end)
    while d <= stop:
        out.append((d.isoformat(), round(a, 4)))
        a += step
        m = d.month + 3
        d = datetime.date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, min(d.day, 28))
    return out


def write(folder, symbol, doc):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "chart-%s.json" % symbol), "w") as fh:
        json.dump(doc, fh)
