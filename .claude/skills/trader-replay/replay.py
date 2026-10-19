#!/usr/bin/env python3
"""What would $100 have done? A point-in-time replay of every strategy.

For each start (1 week, 2 weeks, 1 month and 6 months before the as-of date,
by default the latest Friday close), every strategy gets $100 CAD of cash and
runs forward one trading day at a time. A decision only uses data up to that
day's close; its trades fill at the next open. Nothing from the future is used.

  growth / medium / dividend   the account reviewer: reviews at the start and every
                               Friday, places its trims and buys
  stock bot                    the ATR paper bot (fractional shares)
  crypto team                  the 15-minute crypto bot team
  Pelosi copycat               buys what Nancy Pelosi disclosed buying, sells what she
                               disclosed selling, from the day each filing was POSTED
  benchmarks                   buy and hold S&P 500 (SPY), TSX 60 (XIU.TO), Bitcoin, cash

Costs: 1.5% currency conversion each way for USD assets, 5 bps slippage, the
bots' own fees, 15% US dividend withholding (TFSA). Dividends are paid on the
ex-date.

    python3 replay.py                       # as of the latest Friday close
    python3 replay.py --asof 2026-10-16 --cash 100
    python3 replay.py --skip crypto pelosi  # faster
    python3 replay.py --offline DIR         # chart-<SYM>.json, candles-<COIN>.json, pelosi/ files

Writes trader/replay/report.md and report.json. Not financial advice: a
replay of the past, with today's choice of watchlists (a hindsight bias of its own).
"""

import argparse
import bisect
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
for _f in ("trader-accounts", "trader-paper", "trader-team", "trader-pelosi", "trader-init"):
    sys.path.insert(0, os.path.join(SKILLS, _f))
import accounts as acc  # noqa: E402
import market as mk  # noqa: E402
import paper  # noqa: E402
import ptr  # noqa: E402
import team  # noqa: E402

WINDOWS = [("6 months", 182), ("1 month", 30), ("2 weeks", 14), ("1 week", 7)]
COSTS = {"fx_fee_pct": 1.5, "slippage_pct": 0.05, "us_withholding_pct": 15.0}
PELOSI_LOOKBACK_DAYS = 120  # filings already public at the start shape the starting basket


class ReplayError(Exception):
    pass


def _date(s):
    return datetime.date.fromisoformat(s)


# ---------------------------------------------------------------- point-in-time data

class Data:
    def __init__(self, charts, cfg):
        self.charts, self.cfg = charts, cfg
        self.dates = {s: [b["d"] for b in ch["bars"]] for s, ch in charts.items()}
        spy = charts.get("SPY")
        if not spy:
            raise ReplayError("no SPY prices: they set the trading calendar")
        self.days = self.dates["SPY"]

    def bar(self, sym, day):
        ds = self.dates.get(sym)
        if not ds:
            return None
        i = bisect.bisect_left(ds, day)
        return self.charts[sym]["bars"][i] if i < len(ds) and ds[i] == day else None

    def close(self, sym, day):
        """Last close on or before day (never after)."""
        ds = self.dates.get(sym)
        if not ds:
            return None
        i = bisect.bisect_right(ds, day) - 1
        return self.charts[sym]["bars"][i]["c"] if i >= 0 else None

    def upto(self, sym, day):
        """The chart as it looked at the close of `day`."""
        ch = self.charts[sym]
        i = bisect.bisect_right(self.dates[sym], day)
        if not i:
            return None
        bars = ch["bars"][:i]
        return {"symbol": sym, "name": ch.get("name", ""), "currency": ch["currency"], "price": bars[-1]["c"],
                "time": bars[-1]["d"], "bars": bars, "dividends": [x for x in ch["dividends"] if x[0] <= day]}

    def fx(self, day):
        return self.close("USDCAD=X", day) or 1.35

    def trading_day_on_or_before(self, day):
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0:
            raise ReplayError("no prices before %s" % day)
        return self.days[i]


class Portfolio:
    """$ in CAD; positions in their own currency. Every fill pays slippage, and USD pays FX."""

    def __init__(self, data, cash=100.0, account_type="TFSA"):
        self.data, self.cash, self.pos = data, float(cash), {}
        self.fees, self.trades, self.dividends_cad = 0.0, 0, 0.0
        self.fx_fees, self.slippage = 0.0, 0.0
        self.us_tax = COSTS["us_withholding_pct"] / 100.0 if account_type.upper() not in acc.NO_US_WITHHOLDING else 0
        self.log = []      # every fill, for the dashboard
        self.flow = {}     # ticker -> CAD paid in, CAD taken out (sales + dividends)
        self.curve = []    # [day, value at the close]
        self.cash_share = []

    def _ccy(self, sym):
        return (self.data.charts[sym]["currency"] or mk.native_currency(sym)).upper()

    def _to_cad(self, amount, ccy, day, buying):
        if ccy == "CAD":
            return amount, 0.0
        rate, fee = self.data.fx(day), COSTS["fx_fee_pct"] / 100.0
        gross = amount * rate
        return (gross * (1 + fee), gross * fee) if buying else (gross * (1 - fee), gross * fee)

    def fill(self, orders, day):
        """Fill orders decided before `day` at today's open; sells first. Returns the ones still waiting."""
        waiting = []
        for o in sorted(orders, key=lambda o: o["side"] != "sell"):
            b = self.data.bar(o["ticker"], day)
            if o["decided"] >= day or not b:
                waiting.append(o)
                continue
            slip = COSTS["slippage_pct"] / 100.0
            ccy = self._ccy(o["ticker"])
            if o["side"] == "sell":
                p = self.pos.get(o["ticker"])
                if not p:
                    continue
                q = min(o["shares"], p["shares"])
                px = b["o"] * (1 - slip)
                cad, fxfee = self._to_cad(q * px, ccy, day, False)
                self.cash += cad
                self._cost(fxfee, q * b["o"] * slip * (self.data.fx(day) if ccy == "USD" else 1))
                self.flow.setdefault(o["ticker"], [0.0, 0.0])[1] += cad
                p["shares"] -= q
                if p["shares"] <= 1e-9:
                    del self.pos[o["ticker"]]
            else:
                px = b["o"] * (1 + slip)
                q = o["shares"] if o.get("shares") else None
                if q is None:  # sized in CAD
                    rate = self.data.fx(day) * (1 + COSTS["fx_fee_pct"] / 100.0) if ccy == "USD" else 1.0
                    q = o["cad"] / (px * rate)
                cad, fxfee = self._to_cad(q * px, ccy, day, True)
                if cad > self.cash:
                    q *= self.cash / cad if cad else 0
                    cad, fxfee = self._to_cad(q * px, ccy, day, True)
                if q <= 0 or cad < 0.5:
                    continue
                self.cash -= cad
                self._cost(fxfee, q * b["o"] * slip * (self.data.fx(day) if ccy == "USD" else 1))
                self.flow.setdefault(o["ticker"], [0.0, 0.0])[0] += cad
                p = self.pos.setdefault(o["ticker"], {"shares": 0.0, "cost": 0.0, "currency": ccy})
                p["cost"] += q * px
                p["shares"] += q
            self.trades += 1
            self.log.append({"day": day, "side": o["side"], "ticker": o["ticker"], "shares": round(q, 6),
                             "price": round(px, 4), "currency": ccy, "cad": round(cad, 2)})
        return waiting

    def _cost(self, fx, slip):
        self.fx_fees += fx
        self.slippage += slip
        self.fees += fx + slip

    def mark(self, day):
        v = self.value(day)
        self.curve.append([day, round(v, 2)])
        self.cash_share.append(self.cash / v if v > 0 else 1.0)

    def pay_dividends(self, day):
        for sym, p in self.pos.items():
            for d, amt in self.data.charts[sym]["dividends"]:
                if d == day:
                    gross = amt * p["shares"] * (1 - (self.us_tax if p["currency"] == "USD" else 0))
                    cad, fxfee = self._to_cad(gross, p["currency"], day, False)
                    self.cash += cad
                    self.dividends_cad += cad
                    self._cost(fxfee, 0.0)
                    self.flow.setdefault(sym, [0.0, 0.0])[1] += cad

    def value(self, day):
        v = self.cash
        for sym, p in self.pos.items():
            px = self.data.close(sym, day) or 0.0
            v += px * p["shares"] * (self.data.fx(day) if p["currency"] == "USD" else 1.0)
        return v

    def doc(self, day):
        return {"cash": {"CAD": self.cash}, "as_of": day, "positions": [
            {"ticker": s, "shares": p["shares"], "currency": p["currency"],
             "avg_cost": p["cost"] / p["shares"] if p["shares"] else None,
             "last_price": self.data.close(s, day)} for s, p in self.pos.items()]}

    def result(self, day, start_cash):
        v = self.value(day)
        contrib = []
        for sym, (paid, back) in self.flow.items():
            p = self.pos.get(sym)
            now = (self.data.close(sym, day) or 0) * p["shares"] * (
                self.data.fx(day) if p["currency"] == "USD" else 1.0) if p else 0.0
            contrib.append({"ticker": sym, "pnl": round(back + now - paid, 2), "held": bool(p)})
        contrib.sort(key=lambda c: -c["pnl"])
        return {"value": round(v, 2), "return_pct": round(100.0 * (v / start_cash - 1), 2), "trades": self.trades,
                "fees": round(self.fees, 2), "fx_fees": round(self.fx_fees, 2), "slippage": round(self.slippage, 2),
                "dividends": round(self.dividends_cad, 2), "holdings": sorted(self.pos),
                "cash_left": round(self.cash, 2), "contrib": contrib, "curve": self.curve,
                "cash_drag_pct": round(100.0 * sum(self.cash_share) / len(self.cash_share), 1)
                if self.cash_share else None, "fills": self.log[-40:]}


def _review_days(days, start, asof):
    return {d for d in days if start <= d < asof and (d == start or _date(d).weekday() == 4)}


# ---------------------------------------------------------------- strategies

def run_account(data, strategy, watch, start, asof, cash, account_type):
    rules = dict(acc.RULES[strategy], min_trade=1)
    acct = {"id": strategy, "name": strategy, "strategy": strategy, "type": account_type, "fractional": True,
            "watchlist": watch, "rules": rules, "broker": ""}
    pf, pending, notes = Portfolio(data, cash, account_type), [], []
    days = [d for d in data.days if start <= d <= asof]
    reviews = _review_days(days, start, asof)
    for d in days:
        pf.pay_dividends(d)  # ex-date: only shares owned before today's open are paid
        pending = pf.fill(pending, d)
        pf.mark(d)
        if d not in reviews:
            continue
        syms = set(watch) | set(pf.pos)
        snap = {s: mk.metrics(data.upto(s, d), today=d) for s in syms if s in data.charts and data.upto(s, d)}
        r = acc.review_account(acct, pf.doc(d), {"symbols": snap, "fx": {"USDCAD": data.fx(d)}}, base="CAD")
        pending = [{"side": o["side"], "ticker": o["ticker"], "shares": o["shares"], "decided": d}
                   for o in r["proposals"]]
        if d == start:
            notes = [f["text"] for f in r["flags"]][:2]
    out = pf.result(asof, cash)
    out["notes"] = notes
    return out


def run_hold(data, weights, start, asof, cash):
    pf = Portfolio(data, cash)
    orders = [{"side": "buy", "ticker": s, "cad": cash * w * 0.999, "decided": start} for s, w in weights.items()
              if s in data.charts]
    for d in [d for d in data.days if start <= d <= asof]:
        pf.pay_dividends(d)
        orders = pf.fill(orders, d)
        pf.mark(d)
    return pf.result(asof, cash)


def run_stockbot(data, universe, start, asof, cash):
    fx0 = data.fx(start)
    usd0 = cash / (fx0 * (1 + COSTS["fx_fee_pct"] / 100.0))
    p = dict(paper.PARAMS, fractional=True, min_order=1)
    charts = {s: data.charts[s] for s in universe if s in data.charts}
    days, bars_by, regime = paper.prepare(charts, p)
    led = paper.new_ledger(usd0, p)
    for d in days:
        if start <= d <= asof:
            paper.step(led, d, bars_by, regime, p)
    if not led["trades"] and not led["positions"]:  # never traded: the money never left CAD
        return {"value": round(cash, 2), "return_pct": 0.0, "trades": 0, "fees": 0.0, "fx_fees": 0.0,
                "dividends": 0.0, "holdings": [], "cash_left": round(cash, 2), "contrib": [], "fills": [],
                "curve": [[d, round(cash, 2)] for d, _ in led["equity"]], "cash_drag_pct": 100.0,
                "win_rate_pct": None}
    eq = led["equity"][-1][1] if led["equity"] else usd0
    v = eq * data.fx(asof) * (1 - COSTS["fx_fee_pct"] / 100.0)
    by = {}
    for t in led["trades"]:
        by[t["ticker"]] = by.get(t["ticker"], 0.0) + t["pnl"] * data.fx(t["exit_day"])
    for t, pos in led["positions"].items():
        by[t] = by.get(t, 0.0) + ((data.close(t, asof) or pos["entry"]) - pos["entry"]) * pos["shares"] * data.fx(asof)
    fees_usd = sum(abs(t["shares"]) * (t["entry"] + t["exit"]) * paper.PARAMS["cost_bps"] / 1e4 for t in led["trades"])
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2),
            "trades": len(led["trades"]) + len(led["positions"]),
            "fees": round(fees_usd * data.fx(asof) + cash * 2 * COSTS["fx_fee_pct"] / 100.0, 2),
            "fx_fees": round(cash * 2 * COSTS["fx_fee_pct"] / 100.0, 2), "dividends": 0.0,
            "holdings": sorted(led["positions"]), "cash_left": None,
            "contrib": sorted(({"ticker": k, "pnl": round(x, 2), "held": k in led["positions"]} for k, x in by.items()),
                              key=lambda c: -c["pnl"]),
            "curve": [[d, round(e * data.fx(d), 2)] for d, e in led["equity"]],
            "fills": [{"day": t["exit_day"], "side": "round trip", "ticker": t["ticker"], "shares": t["shares"],
                       "price": t["exit"], "currency": "USD", "cad": round(t["pnl"] * data.fx(t["exit_day"]), 2)}
                      for t in led["trades"][-40:]],
            "win_rate_pct": paper.stats(led["equity"], led["trades"]).get("win_rate_pct")}


def market_close_utc(day):
    """4 p.m. New York on `day`, as epoch seconds."""
    try:
        from zoneinfo import ZoneInfo
        t = datetime.datetime.combine(_date(day), datetime.time(16, 0), ZoneInfo("America/New_York"))
        return int(t.timestamp())
    except Exception:
        return int(datetime.datetime.combine(_date(day), datetime.time(20, 0), datetime.timezone.utc).timestamp())


def run_crypto(candles, data, start, asof, cash, workdir):
    cfg = dict(team.DEFAULTS)
    fx0 = data.fx(start)
    usd0 = cash / (fx0 * (1 + COSTS["fx_fee_pct"] / 100.0))
    cfg.update(start_cash=usd0, broker="sim")
    t0, t1, iv = market_close_utc(start), market_close_utc(asof), cfg["interval_min"] * 60
    paths = team.Paths(workdir)
    for f in (paths.state, paths.trades, paths.events, paths.equity, paths.kill):
        if os.path.exists(f):
            os.remove(f)
    keys = {c: [b["t"] for b in bs] for c, bs in candles.items()}
    state = {"mode": "sim"}
    broker = team.executor.SimBroker(state, cfg)
    killed = None
    for now in range(t0 - t0 % iv, t1 + 1, iv):
        window = {}
        for c, bs in candles.items():
            i = bisect.bisect_right(keys[c], now - iv)  # bars that closed by `now`
            window[c] = bs[max(0, i - cfg["lookback_bars"]):i]
        if not any(window.values()):
            continue
        rep = team.cycle(state, window, now, broker, cfg, paths, log=lambda *a: None)
        if rep.get("killed"):
            killed = rep["killed"]
            break
    s = team.trade_log.summary(workdir)
    if not s["trades"] and not state.get("positions"):  # never traded: the money never left CAD
        btc_only = _btc_hold(candles, keys, t0, t1, iv, usd0, data, asof, cash)
        return {"value": round(cash, 2), "return_pct": 0.0, "trades": 0, "fees": 0.0, "fx_fees": 0.0,
                "dividends": 0.0, "holdings": [], "cash_left": round(cash, 2), "contrib": [], "curve": [],
                "cash_drag_pct": 100.0, "win_rate_pct": None, "killed": killed, "btc_hold": btc_only}
    prices = {}
    for c, bs in candles.items():
        i = bisect.bisect_right(keys[c], t1 - iv)
        if i:
            prices[c] = bs[i - 1]["c"]
    eq = broker.account(prices)["equity"]
    v = eq * data.fx(asof) * (1 - COSTS["fx_fee_pct"] / 100.0)
    btc_hold = _btc_hold(candles, keys, t0, t1, iv, usd0, data, asof, cash)
    rate = data.fx(asof)
    daily = {}
    for row in team.trade_log.read(paths.equity):
        daily[row["time"][:10]] = float(row["equity"]) * rate
    by = {}
    for t in team.trade_log.read(paths.trades):
        c = t["asset"].split("/")[0]
        by[c] = by.get(c, 0.0) + float(t["pnl"]) * rate
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2), "trades": s["trades"],
            "fees": round(s["fees_slippage"] * rate + cash * 2 * COSTS["fx_fee_pct"] / 100.0, 2),
            "fx_fees": round(cash * 2 * COSTS["fx_fee_pct"] / 100.0, 2), "dividends": 0.0,
            "holdings": sorted(state.get("positions", {})), "cash_left": None,
            "contrib": sorted(({"ticker": k, "pnl": round(x, 2), "held": k in state.get("positions", {})}
                               for k, x in by.items()), key=lambda c: -c["pnl"]),
            "curve": [[d, round(x, 2)] for d, x in sorted(daily.items())],
            "exit_reasons": s["exit_reasons"],
            "win_rate_pct": s["win_rate_pct"], "killed": killed, "btc_hold": btc_hold}


def _btc_hold(candles, keys, t0, t1, iv, usd0, data, asof, cash):
    """Buy Bitcoin at the start close, hold to the as-of close (only if both prices exist)."""
    if "BTC" not in candles:
        return None
    a, b = bisect.bisect_right(keys["BTC"], t0 - iv), bisect.bisect_right(keys["BTC"], t1 - iv)
    if not a or not b or candles["BTC"][a - 1]["t"] < t0 - 2 * iv:  # no bar near the start: no answer
        return None
    v = usd0 * candles["BTC"][b - 1]["c"] / candles["BTC"][a - 1]["c"] * data.fx(asof) * (1 - COSTS["fx_fee_pct"] / 100.0)
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2),
            "curve": [], "trades": 1}


# ---------------------------------------------------------------- Pelosi

def pelosi_filings(years, offline=None, pdf_dir="trader/state/ptr-pdfs"):
    """[(filed, [rows])] for every Nancy Pelosi PTR in those years. Each row is one disclosed trade."""
    out, errors = [], []
    for y in years:
        try:
            idx = ptr.load_index(y, os.path.join(offline, "%dFD.zip" % y) if offline else None)
        except (ptr.PtrError, OSError) as e:
            errors.append("House index %d: %s" % (y, e))
            continue
        for f in ptr.select(idx, ["Nancy Pelosi"], "P"):
            try:
                if offline:
                    path = os.path.join(offline, "ptr-%s.txt" % f["doc_id"])
                    if not os.path.exists(path):
                        raise ptr.PtrError("no offline text for %s" % f["doc_id"])
                    with open(path, encoding="utf-8") as fh:
                        report = ptr.parse_ptr_text(fh.read(), filed=f["filed"])
                else:
                    _, report = ptr._fetch_and_read(f["doc_id"], f["year"], pdf_dir, f["filed"])
                if report is None:
                    raise ptr.PtrError("pdftotext is not installed")
                out.append((f["filed"], report["rows"]))
            except (ptr.PtrError, OSError) as e:
                errors.append("PTR %s: %s" % (f["doc_id"], e))
    return sorted(out, key=lambda x: x[0]), errors


def pelosi_signals(rows):
    """Bought stock or calls -> buy the stock. Sold stock or bought puts -> sell it."""
    buys, sells = [], []
    for r in rows:
        t = r.get("ticker")
        if not t:
            continue
        t = mk.yahoo_symbol(t)
        kind = (r.get("type") or "").upper()
        opt = r.get("option") or {}
        if opt.get("kind") == "put":
            (sells if kind.startswith("P") else buys).append(t)
        elif kind.startswith("P") or opt.get("exercised"):
            buys.append(t)
        elif kind.startswith("S"):
            sells.append(t)
    return buys, sells


def run_pelosi(data, filings, start, asof, cash):
    """Equal weight in what she disclosed buying; act only after each filing was posted."""
    basket, pf, pending = [], Portfolio(data, cash), []
    lookback = (_date(start) - datetime.timedelta(days=PELOSI_LOOKBACK_DAYS)).isoformat()
    used = []

    def apply(rows):
        b, s = pelosi_signals(rows)
        for t in b:
            if t not in basket and t in data.charts:
                basket.append(t)
        for t in s:
            if t in basket:
                basket.remove(t)

    for filed, rows in filings:  # what was already public at the start
        if lookback <= filed <= start:
            apply(rows)
            used.append(filed)
    days = [d for d in data.days if start <= d <= asof]
    done = set(used)
    for d in days:
        pf.pay_dividends(d)  # ex-date: only shares owned before today's open are paid
        pending = pf.fill(pending, d)
        pf.mark(d)
        new = [(f, r) for f, r in filings if f <= d and f not in done and f > start]
        if d != start and not new:
            continue
        for f, r in new:
            apply(r)
            done.add(f)
            used.append(f)
        if d == asof:
            break
        total = pf.value(d)
        pending = [{"side": "sell", "ticker": s, "shares": p["shares"], "decided": d}
                   for s, p in pf.pos.items() if s not in basket]
        if basket:
            target = total * 0.99 / len(basket)
            for s in basket:
                held = pf.pos.get(s)
                now_v = (held["shares"] * (data.close(s, d) or 0) *
                         (data.fx(d) if held and held["currency"] == "USD" else 1.0)) if held else 0.0
                if target - now_v > 1:
                    pending.append({"side": "buy", "ticker": s, "cad": target - now_v, "decided": d})
    out = pf.result(asof, cash)
    out["filings_used"] = sorted(set(used))
    out["basket"] = list(basket)
    return out


# ---------------------------------------------------------------- what went well, what did not

BENCH = ("S&P 500 (SPY)", "TSX 60 (XIU.TO)", "Bitcoin (hold)", "cash")


def factors(data, start, asof, filings, candles_btc=None):
    """The market backdrop for one window, all measured from data known by `asof`."""
    spy0, spy1 = data.close("SPY", start), data.close("SPY", asof)
    fx0, fx1 = data.fx(start), data.fx(asof)
    ch = data.upto("SPY", asof)
    m = mk.metrics(ch, today=asof) if ch else {}
    out = {"spy_pct": round(100 * (spy1 / spy0 - 1), 2) if spy0 and spy1 else None,
           "usdcad_pct": round(100 * (fx1 / fx0 - 1), 2) if fx0 and fx1 else None,
           "spy_above_200d": m.get("above_sma200"),
           "pelosi_filings": [f for f, _ in filings if start < f <= asof]}
    tsx0, tsx1 = data.close("XIU.TO", start), data.close("XIU.TO", asof)
    if tsx0 and tsx1:
        out["tsx_pct"] = round(100 * (tsx1 / tsx0 - 1), 2)
    return out


def insights(row, fac, cash):
    """Plain-English notes per strategy: what helped, what hurt."""
    spy = (row.get("S&P 500 (SPY)") or {}).get("return_pct")
    tsx = (row.get("TSX 60 (XIU.TO)") or {}).get("return_pct")
    notes = {}
    for k, r in row.items():
        if k in ("start",) + BENCH or not isinstance(r, dict) or "return_pct" not in r:
            continue
        good, bad = [], []
        ref, ref_name = (tsx, "the TSX 60") if k == "dividend" else (spy, "the S&P 500")
        if ref is not None:
            d = r["return_pct"] - ref
            (good if d >= 0 else bad).append("%s %s by %.1f points (%+.1f%% vs %+.1f%%)" % (
                "beat" if d >= 0 else "trailed", ref_name, abs(d), r["return_pct"], ref))
        c = r.get("contrib") or []
        if c and c[0]["pnl"] > 0:
            good.append("best holding: %s %+.2f" % (c[0]["ticker"], c[0]["pnl"]))
        if c and c[-1]["pnl"] < 0:
            bad.append("worst holding: %s %+.2f" % (c[-1]["ticker"], c[-1]["pnl"]))
        fees = r.get("fees")
        if fees:
            share = 100.0 * fees / cash
            (bad if share >= 1 else good).append("costs took %.1f%% of the money (FX $%.2f)" % (
                share, r.get("fx_fees") or 0) if share >= 1 else "costs stayed small ($%.2f)" % fees)
        cd = r.get("cash_drag_pct")
        if cd is not None and cd >= 30:
            (bad if (spy or 0) > 0 else good).append(
                "sat %.0f%% in cash on average%s" % (cd, ": missed part of a rising market" if (spy or 0) > 0
                                                    else ", which cushioned a falling market"))
        if r.get("dividends"):
            good.append("collected $%.2f in dividends" % r["dividends"])
        if r.get("trades") == 0:
            bad.append("never traded: no signal fired in this window")
        if r.get("win_rate_pct") is not None and r.get("trades"):
            (good if r["win_rate_pct"] >= 50 else bad).append("win rate %.0f%%" % r["win_rate_pct"])
        if r.get("killed"):
            bad.append("kill switch fired: %s" % r["killed"])
        er = r.get("exit_reasons") or {}
        if er.get("stop-loss", 0) > er.get("take-profit", 0) * 2 and er.get("stop-loss", 0) >= 3:
            bad.append("stopped out %d times vs %d targets hit: stops too tight for the noise" % (
                er["stop-loss"], er.get("take-profit", 0)))
        if k == "Pelosi copycat" and not r.get("filings_used"):
            bad.append("no Pelosi filing in or before this window: stayed in cash")
        if k in ("growth", "medium", "stock bot", "Pelosi copycat") and fac.get("usdcad_pct") is not None \
                and abs(fac["usdcad_pct"]) >= 0.5:
            (good if fac["usdcad_pct"] > 0 else bad).append(
                "USD/CAD moved %+.1f%%, which %s US holdings in CAD" % (
                    fac["usdcad_pct"], "lifted" if fac["usdcad_pct"] > 0 else "cut"))
        notes[k] = {"going_well": good, "not_going_well": bad}
    return notes


def overall(results):
    """Across windows: who beat the S&P 500 most often, who led and lagged."""
    tally = {}
    for w, row in results.items():
        spy = (row.get("S&P 500 (SPY)") or {}).get("return_pct")
        ranked = sorted(((k, r["return_pct"]) for k, r in row.items()
                         if isinstance(r, dict) and "return_pct" in r and k not in BENCH), key=lambda x: -x[1])
        for k, ret in ranked:
            t = tally.setdefault(k, {"beat_spy": 0, "windows": 0, "returns": {}})
            t["windows"] += 1
            t["returns"][w] = ret
            if spy is not None and ret > spy:
                t["beat_spy"] += 1
    return tally


# ---------------------------------------------------------------- the whole replay

def watchlists(base):
    import init
    w = {k: list(v) for k, v in init.WATCH.items()}
    cfg = acc.read_json(os.path.join(base, "accounts.json"), {}) or {}
    for a in cfg.get("accounts", []):
        if a.get("watchlist") and a.get("strategy") in w:
            w[a["strategy"]] = list(a["watchlist"])
    return {k: [mk.yahoo_symbol(s) for s in v] for k, v in w.items()}


def latest_friday(days):
    for d in reversed(days):
        if _date(d).weekday() == 4:
            return d
    return days[-1]


def replay(base="trader", asof=None, cash=100.0, skip=(), offline=None, account_type="TFSA", log=print):
    watch = watchlists(base)
    universe = [mk.yahoo_symbol(s) for s in paper.universe(os.path.join(base, "paper", "config.json"))]
    errors = []
    filings = []
    if "pelosi" not in skip:
        this_year = datetime.date.today().year if not asof else _date(asof).year
        filings, errs = pelosi_filings([this_year - 1, this_year], offline=offline,
                                       pdf_dir=os.path.join(base, "state", "ptr-pdfs"))
        errors += errs
    pelosi_syms = sorted({t for _, rows in filings for t in pelosi_signals(rows)[0]})
    syms = sorted(set(["SPY", "XIU.TO", "USDCAD=X"]) | {s for v in watch.values() for s in v} | set(universe)
                  | set(pelosi_syms))
    charts = {}
    for s in syms:
        try:
            charts[s] = mk.get_chart(s, offline=offline, range_="2y")
        except mk.MarketError as e:
            errors.append(str(e))
    if "SPY" not in charts:
        raise ReplayError("no SPY prices, so no trading calendar. Data problems: %s"
                          % "; ".join(errors[:3] or ["none reported"]))
    data = Data(charts, {})
    asof = data.trading_day_on_or_before(asof) if asof else latest_friday(data.days)
    candles = {}
    if "crypto" not in skip:
        cfg = dict(team.DEFAULTS)
        first = (_date(asof) - datetime.timedelta(days=max(n for _, n in WINDOWS) + 4)).isoformat()
        t0 = market_close_utc(first) - (cfg["lookback_bars"] + 4) * cfg["interval_min"] * 60
        if offline:
            for c in cfg["coins"]:
                p = os.path.join(offline, "candles-%s.json" % c)
                if os.path.exists(p):
                    with open(p) as fh:
                        candles[c] = json.load(fh)
        else:
            candles, errs = team.candles.fetch(cfg["coins"], cfg["data"], t0, market_close_utc(asof) + 900,
                                               cfg["interval_min"])
            errors += errs
    results = {}
    for label, n in WINDOWS:
        start = data.trading_day_on_or_before((_date(asof) - datetime.timedelta(days=n)).isoformat())
        log("replaying %s (from the close of %s)..." % (label, start))
        row = {"start": start}
        for strat in ("growth", "medium", "dividend"):
            row[strat] = run_account(data, strat, watch[strat], start, asof, cash, account_type)
        row["stock bot"] = run_stockbot(data, universe, start, asof, cash)
        if candles:
            c = run_crypto(candles, data, start, asof, cash, os.path.join(base, "replay", "crypto-" + label.replace(" ", "")))
            row["crypto team"] = c
            if c.get("btc_hold"):
                row["Bitcoin (hold)"] = c["btc_hold"]
        if "pelosi" not in skip:
            row["Pelosi copycat"] = run_pelosi(data, filings, start, asof, cash)
        row["S&P 500 (SPY)"] = run_hold(data, {"SPY": 1.0}, start, asof, cash)
        row["TSX 60 (XIU.TO)"] = run_hold(data, {"XIU.TO": 1.0}, start, asof, cash)
        row["cash"] = {"value": round(cash, 2), "return_pct": 0.0}
        row["factors"] = factors(data, start, asof, filings)
        row["insights"] = insights(row, row["factors"], cash)
        results[label] = row
    out = {"asof": asof, "cash": cash, "account_type": account_type, "costs": COSTS, "results": results,
           "overall": overall(results), "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "errors": errors, "pelosi_filings": [f for f, _ in filings], "watchlists": watch,
           "note": "Point-in-time replay: decisions use data up to each day's close, fills at the next open. "
                   "Watchlists are today's, which is a hindsight bias. Not financial advice."}
    folder = os.path.join(base, "replay")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    text = render(out)
    with open(os.path.join(folder, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return out, text


ORDER = ["growth", "medium", "dividend", "stock bot", "crypto team", "Pelosi copycat",
         "S&P 500 (SPY)", "TSX 60 (XIU.TO)", "Bitcoin (hold)", "cash"]
LABELS = {"growth": "Growth reviewer (Questrade)", "medium": "Medium-term reviewer",
          "dividend": "Dividend reviewer (Wealthsimple)", "stock bot": "Stock bot (ATR, paper)",
          "crypto team": "Crypto bot team (paper)"}


def _p(x):
    return "n/a" if x is None else "%+.1f%%" % x


def render(out):
    wins = [w for w, _ in WINDOWS if w in out["results"]]
    L = ["# $%g replay, as of the close on %s" % (out["cash"], out["asof"]), "",
         "Each cell: value at the close on %s (return). Starts: %s." % (
             out["asof"], ", ".join("%s = %s" % (w, out["results"][w]["start"]) for w in wins)), "",
         "| strategy | " + " | ".join(wins) + " |", "| --- |" + " ---: |" * len(wins)]
    for k in ORDER:
        cells = []
        for w in wins:
            r = out["results"][w].get(k)
            cells.append("$%.2f (%+.1f%%)" % (r["value"], r["return_pct"]) if r else "n/a")
        if any(c != "n/a" for c in cells):
            if k == "Pelosi copycat":
                L.append("| **%s** | " % "Pelosi copycat (separate)" + " | ".join(cells) + " |")
            else:
                L.append("| %s | " % LABELS.get(k, k) + " | ".join(cells) + " |")
    L += ["", "## Details", ""]
    for w in wins:
        r = out["results"][w]
        L.append("**%s** (from %s)" % (w, r["start"]))
        for k in ORDER[:6]:
            x = r.get(k)
            if not x:
                continue
            bits = ["%s trades" % x.get("trades", 0)]
            if x.get("fees") is not None:
                bits.append("costs $%.2f" % x["fees"])
            if x.get("dividends"):
                bits.append("dividends $%.2f" % x["dividends"])
            if x.get("win_rate_pct") is not None:
                bits.append("win rate %s%%" % x["win_rate_pct"])
            if x.get("holdings"):
                bits.append("holds " + ", ".join(x["holdings"][:8]))
            if x.get("killed"):
                bits.append("kill switch: " + x["killed"])
            if k == "Pelosi copycat":
                bits.append("filings used: %s" % (", ".join(x["filings_used"]) or "none yet"))
            L.append("- %s: %s" % (LABELS.get(k, k), "; ".join(bits)))
        L.append("")
    L += ["## What is going well, what is not", ""]
    for k, t in sorted(out.get("overall", {}).items(), key=lambda kv: -kv[1]["beat_spy"]):
        L.append("- **%s** beat the S&P 500 in %d of %d windows" % (LABELS.get(k, k), t["beat_spy"], t["windows"]))
    L.append("")
    for w in wins:
        r = out["results"][w]
        f = r.get("factors") or {}
        L.append("### %s: the backdrop" % w)
        L.append("S&P 500 %s, TSX 60 %s, USD/CAD %s, S&P 500 %s its 200-day average, Pelosi filings posted: %d" % (
            _p(f.get("spy_pct")), _p(f.get("tsx_pct")), _p(f.get("usdcad_pct")),
            "above" if f.get("spy_above_200d") else "below", len(f.get("pelosi_filings") or [])))
        for k, n in (r.get("insights") or {}).items():
            L.append("- **%s**: + %s / - %s" % (LABELS.get(k, k), "; ".join(n["going_well"]) or "nothing stood out",
                                                 "; ".join(n["not_going_well"]) or "nothing stood out"))
        L.append("")
    if out["errors"]:
        L.append("## Data problems")
        L += ["- " + e for e in out["errors"][:15]]
        L.append("")
    L.append("_%s_" % out["note"])
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Point-in-time replay of every strategy with $100.")
    ap.add_argument("--dir", default="trader")
    ap.add_argument("--asof", help="YYYY-MM-DD (default: the latest Friday close)")
    ap.add_argument("--cash", type=float, default=100.0)
    ap.add_argument("--account-type", default="TFSA")
    ap.add_argument("--skip", nargs="*", default=[], choices=["crypto", "pelosi"])
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        out, text = replay(a.dir, a.asof, a.cash, a.skip, a.offline, a.account_type,
                           log=lambda m: print(m, file=sys.stderr))
    except (ReplayError, mk.MarketError) as e:
        print("replay: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1) if a.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
