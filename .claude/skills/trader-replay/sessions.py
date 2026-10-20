#!/usr/bin/env python3
"""Overseas sessions -> North American day trade, on PAPER.

Tokyo and Hong Kong have closed and London and Frankfurt are half way through their day by the time
New York opens. This reads how those markets moved, 15 minutes before the New York open, and decides
whether to buy a fund (SPY, QQQ or Canada's XIU.TO) at the open and sell it at the close.

    python3 sessions.py backtest --out DIR      # every version, about 2 years of hourly data
    python3 sessions.py today                   # this morning's read (before 9:15 a.m. New York)

Point in time: only hourly bars that had CLOSED by 9:15 a.m. New York time are used (daylight saving
handled), the trade fills at the open and closes at the close, with 0.05% slippage each way. Never
short; on a no-trade day the money sits in cash. Training is the first year, the last 365 days are
held out. Not financial advice; frequent trading in a TFSA risks being taxed as business income.
"""

import argparse
import bisect
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

HOURLY = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=1h"
MARKETS = {"Tokyo": "^N225", "Hong Kong": "^HSI", "London": "^FTSE", "Frankfurt": "^GDAXI"}
ASIA, EUROPE = ("Tokyo", "Hong Kong"), ("London", "Frankfurt")
SLIP = 0.05  # % each way
LEAD_MIN = 15  # decide this many minutes before the New York open
HOLDOUT_DAYS = 365

VERSIONS = [
    ("D1", "Asia closed up: day-trade SPY", {"markets": ASIA, "fund": "SPY", "above": 0.0}),
    ("D2", "Europe up so far: day-trade SPY", {"markets": EUROPE, "fund": "SPY", "above": 0.0}),
    ("D3", "All four up on average (0.25%+): day-trade SPY", {"markets": ASIA + EUROPE, "fund": "SPY", "above": 0.25}),
    ("D4", "Buy the dip: all four down 0.5%+ on average, day-trade SPY",
     {"markets": ASIA + EUROPE, "fund": "SPY", "below": -0.5}),
    ("D5", "All four up on average (0.25%+): day-trade the Nasdaq 100 (QQQ)",
     {"markets": ASIA + EUROPE, "fund": "QQQ", "above": 0.25}),
    ("D6", "All four up on average (0.25%+): day-trade the TSX 60 (XIU.TO)",
     {"markets": ASIA + EUROPE, "fund": "XIU.TO", "above": 0.25}),
]
FUNDS = ("SPY", "QQQ", "XIU.TO")


class SessionsError(Exception):
    pass


# ---------------------------------------------------------------- time

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(days=7 * (n - 1))


def ny_open_utc(day):
    """Epoch seconds of 9:30 a.m. New York time on `day` (YYYY-MM-DD). Daylight saving runs from the
    second Sunday of March to the first Sunday of November (UTC-4), otherwise UTC-5."""
    d = datetime.date.fromisoformat(day)
    summer = _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)
    t = datetime.datetime(d.year, d.month, d.day, 13 if summer else 14, 30, tzinfo=datetime.timezone.utc)
    return int(t.timestamp())


def decision_time(day):
    return ny_open_utc(day) - 60 * LEAD_MIN


def _utc_date(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()


# ---------------------------------------------------------------- data

def parse_hourly(text, symbol):
    """Yahoo hourly chart JSON -> [(bar start epoch, close)], oldest first."""
    try:
        r = json.loads(text)["chart"]["result"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        raise SessionsError("Yahoo returned something unexpected for %s" % symbol)
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    return sorted((ts, c) for ts, c in zip(r.get("timestamp") or [], closes) if c is not None)


def load(offline=None, save=None, log=print):
    """({market: hourly bars}, {symbol: daily chart}) from Yahoo, or DIR/hourly-SYM.json and the
    usual chart-SYM.json files with offline=DIR."""
    hourly, daily = {}, {}
    for name, sym in MARKETS.items():
        path = os.path.join(offline or save or "", "hourly-%s.json" % sym)
        try:
            if offline:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            else:
                text = mk.fetch(HOURLY % sym.replace("^", "%5E"))
                if save:
                    os.makedirs(save, exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text)
            hourly[name] = parse_hourly(text, sym)
        except (OSError, mk.MarketError, SessionsError) as e:
            log("sessions: %s: %s" % (name, e))
    for sym in list(MARKETS.values()) + list(FUNDS):
        try:
            daily[sym] = mk.get_chart(sym, offline=offline, range_="2y", save=save)
        except mk.MarketError as e:
            log("sessions: %s" % e)
    return hourly, daily


# ---------------------------------------------------------------- the read

def move(bars, daily_chart, day):
    """How far a market had moved by the decision time on `day` (%): its last closed hourly bar that
    day against its previous day's close. None if it did not trade that day (holiday)."""
    cut = decision_time(day)
    i = bisect.bisect_right(bars, (cut - 3600, float("inf"))) - 1  # a bar starting at T has closed at T+1h
    if i < 0 or _utc_date(bars[i][0]) != day:
        return None
    prev = [b["c"] for b in daily_chart["bars"] if b["d"] < day]
    return 100.0 * (bars[i][1] / prev[-1] - 1) if prev and prev[-1] else None


def read(hourly, daily, day, markets):
    """{market: move %} for the markets that traded by the decision time, and their average."""
    got = {}
    for m in markets:
        if m in hourly and MARKETS[m] in daily:
            x = move(hourly[m], daily[MARKETS[m]], day)
            if x is not None:
                got[m] = round(x, 3)
    return got, (sum(got.values()) / len(got) if got else None)


def signal(avg, above=None, below=None):
    if avg is None:
        return False
    if above is not None:
        return avg > above
    return below is not None and avg < below


# ---------------------------------------------------------------- the backtest

def _stats(rets, days):
    v, peak, dd, curve = 1.0, 1.0, 0.0, []
    for d, r in zip(days, rets):
        v *= 1 + r / 100.0
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
        curve.append([d, round(100 * v, 2)])
    traded = [r for r in rets if r != 0.0]
    return {"return_pct": round(100 * (v - 1), 2), "trades": len(traded),
            "win_rate": round(100.0 * sum(r > 0 for r in traded) / len(traded), 1) if traded else None,
            "avg_trade_pct": round(sum(traded) / len(traded), 3) if traded else None,
            "max_dd_pct": round(100 * dd, 2), "curve": curve}


def backtest(hourly, daily, versions=VERSIONS, start=None, end=None):
    """Every version, plus two benchmarks per fund: day-trading it every day (open to close, no
    signal) and holding it (close to close). Returns {name: stats} over trading days in [start, end]."""
    out = {}
    for fund in FUNDS:
        ch = daily.get(fund)
        if not ch:
            continue
        bars = [b for b in ch["bars"] if (not start or b["d"] >= start) and (not end or b["d"] <= end)]
        if len(bars) < 2:
            continue
        days = [b["d"] for b in bars[1:]]
        hold = [100.0 * (b["c"] / a["c"] - 1) for a, b in zip(bars, bars[1:])]
        every = [100.0 * (b["c"] * (1 - SLIP / 100) / (b["o"] * (1 + SLIP / 100)) - 1) for b in bars[1:]]
        out["Hold %s" % fund] = _stats(hold, days)
        out["Day-trade %s every day" % fund] = _stats(every, days)
        for code, name, o in versions:
            if o["fund"] != fund:
                continue
            rets = []
            for b, e in zip(bars[1:], every):
                _, avg = read(hourly, daily, b["d"], o["markets"])
                rets.append(e if signal(avg, o.get("above"), o.get("below")) else 0.0)
            out["%s. %s" % (code, name)] = dict(_stats(rets, days), code=code, fund=fund)
    return out


def run(hourly, daily):
    """Training (the first part) and the held-out last 365 days, kept apart."""
    spy = (daily.get("SPY") or {}).get("bars") or []
    if not spy:
        raise SessionsError("no SPY prices")
    last = spy[-1]["d"]
    cut = (datetime.date.fromisoformat(last) - datetime.timedelta(days=HOLDOUT_DAYS)).isoformat()
    first = min(b[0] for bars in hourly.values() for b in bars[:1]) if hourly else None
    first = _utc_date(first) if first else spy[0]["d"]
    return {"first": first, "cut": cut, "last": last, "markets": MARKETS,
            "training": backtest(hourly, daily, start=first, end=cut),
            "test": backtest(hourly, daily, start=cut, end=last)}


def verdict(res):
    """Rule round 9: a version counts if, in training, it beats holding its fund AND day-trading it
    every day; the best of those is the pick."""
    tr = res["training"]
    ok = []
    for name, r in tr.items():
        if "code" not in r:
            continue
        hold, every = tr.get("Hold %s" % r["fund"]), tr.get("Day-trade %s every day" % r["fund"])
        if hold and every and r["return_pct"] > hold["return_pct"] and r["return_pct"] > every["return_pct"]:
            ok.append((r["return_pct"], name))
    return max(ok)[1] if ok else None


def render(res):
    pick = verdict(res)
    L = ["# Overseas sessions -> New York / Toronto day trade (paper)", "",
         "Read Tokyo and Hong Kong (closed) and London and Frankfurt (half way) at 9:15 a.m. New York time, "
         "using only hourly bars that had closed; buy at the open, sell at the close, 0.05%% slippage each way, "
         "never short. Training %s to %s; held-out test %s to %s." % (res["first"], res["cut"], res["cut"], res["last"]),
         "", "| version | training return | trades | win rate | worst drop | held-out year |",
         "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, r in res["training"].items():
        t = res["test"].get(name) or {}
        L.append("| %s%s | %+.1f%% | %d | %s | %.1f%% | %s |" % (
            name, " (pick)" if name == pick else "", r["return_pct"], r["trades"],
            "n/a" if r["win_rate"] is None else "%.0f%%" % r["win_rate"], r["max_dd_pct"],
            "n/a" if "return_pct" not in t else "%+.1f%%" % t["return_pct"]))
    L += ["", ("**Rule (written before the data):** a version counts only if it beat both holding its fund and "
               "day-trading it every day in training. Pick: %s." % pick) if pick else
          "**Rule (written before the data):** no version beat both holding its fund and day-trading it every day "
          "in training, so the overseas read did not add value here.",
          "", "_Paper only. Frequent trading in a TFSA risks being taxed as business income. Not financial advice._"]
    return "\n".join(L) + "\n"


def today(hourly, daily, day=None):
    """This morning's read for every version (only meaningful before 9:15 a.m. New York time)."""
    day = day or datetime.date.today().isoformat()
    out = []
    for code, name, o in VERSIONS:
        got, avg = read(hourly, daily, day, o["markets"])
        out.append({"code": code, "name": name, "moves": got, "average": None if avg is None else round(avg, 3),
                    "trade": signal(avg, o.get("above"), o.get("below"))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Overseas sessions -> North American day trade (paper).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--out", default="trader/replay")
    t = sub.add_parser("today")
    t.add_argument("--day")
    for p in (b, t):
        p.add_argument("--offline", metavar="DIR")
        p.add_argument("--save-data", metavar="DIR")
    a = ap.parse_args(argv)
    hourly, daily = load(a.offline, a.save_data, log=lambda m: print(m, file=sys.stderr))
    try:
        if a.cmd == "today":
            for x in today(hourly, daily, a.day):
                print("%s %-62s %s  %s" % (x["code"], x["name"], "TRADE" if x["trade"] else "cash ",
                                           ", ".join("%s %+.2f%%" % kv for kv in x["moves"].items()) or "no data"))
            print("Paper only. Not financial advice.")
            return 0
        res = run(hourly, daily)
    except SessionsError as e:
        print("sessions: %s" % e, file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "sessions.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    text = render(res)
    with open(os.path.join(a.out, "sessions.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
