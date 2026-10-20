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

Currency: US stocks trade in US dollars and Canadian ones in Canadian dollars,
as in a real Questrade or Wealthsimple account; each strategy's $100 CAD worth
starts in the currency it trades, so nothing is converted per trade. A 1.5%
fee applies only if a buy needs a currency the account has run out of. Values
are reported in CAD at each day's rate, so USD/CAD moves still count.
Costs: 5 bps slippage, the bots' own fees, 15% US dividend withholding (TFSA).
Dividends are paid on the ex-date, in the stock's own currency.

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
sys.path.insert(0, HERE)
import accounts as acc  # noqa: E402
import market as mk  # noqa: E402
import paper  # noqa: E402
import universe as univ  # noqa: E402
import signals as sigs  # noqa: E402
import ptr  # noqa: E402
import team  # noqa: E402
import vix  # noqa: E402

WINDOWS = [("12 months", 365), ("6 months", 182), ("3 months", 91), ("1 month", 30), ("2 weeks", 14), ("1 week", 7)]
CRYPTO_MAX_DAYS = 182  # 15-minute crypto history past 6 months is slow to fetch and replay
CRYPTO_LONG_DAYS = 365  # hourly and slower bars are cheap: a full year
ROLLING = {"horizon_days": 91, "step_days": 30, "count": 12}  # 3-month windows, a new one each month
COSTS = {"fx_fee_pct": 1.5, "slippage_pct": 0.05, "us_withholding_pct": 15.0}
PELOSI_LOOKBACK_DAYS = 120  # filings already public at the start shape the starting basket


class ReplayError(Exception):
    pass


def _date(s):
    return datetime.date.fromisoformat(s)


def _gap(a, b):
    return (_date(b) - _date(a)).days


# ---------------------------------------------------------------- point-in-time data

class Data:
    def __init__(self, charts, cfg):
        self.charts, self.cfg = charts, cfg
        self.dates = {s: [b["d"] for b in ch["bars"]] for s, ch in charts.items()}
        self._metrics, self._sums = {}, {}
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
        """The chart as it looked at the close of `day` (the last 300 bars: all that metrics reads)."""
        ch = self.charts[sym]
        i = bisect.bisect_right(self.dates[sym], day)
        if not i:
            return None
        bars = ch["bars"][max(0, i - 300):i]
        return {"symbol": sym, "name": ch.get("name", ""), "currency": ch["currency"], "price": bars[-1]["c"],
                "time": bars[-1]["d"], "bars": bars, "dividends": [x for x in ch["dividends"] if x[0] <= day]}

    def metrics(self, sym, day):
        """mk.metrics as of the close of `day`, cached: many runs review the same days."""
        key = (sym, day)
        if key not in self._metrics:
            ch = self.upto(sym, day) if sym in self.charts else None
            self._metrics[key] = mk.metrics(ch, today=day) if ch else None
        return self._metrics[key]

    def _prefix(self, sym):
        """Prefix sums of closes, log returns and squared log returns, for O(1) screening."""
        if sym not in self._sums:
            import math
            c = [b["c"] for b in self.charts[sym]["bars"]]
            sc, sr, sq = [0.0], [0.0, 0.0], [0.0, 0.0]
            for x in c:
                sc.append(sc[-1] + x)
            for a, b in zip(c, c[1:]):
                r = math.log(b / a) if a > 0 and b > 0 else 0.0
                sr.append(sr[-1] + r)
                sq.append(sq[-1] + r * r)
            self._sums[sym] = (c, sc, sr, sq)
        return self._sums[sym]

    def yield_ttm(self, sym, day):
        """Trailing 12-month dividend yield (%) at the close of `day`."""
        px = self.close(sym, day)
        if not px:
            return 0.0
        a = (_date(day) - datetime.timedelta(days=365)).isoformat()
        return 100.0 * sum(x for d, x in self.charts[sym]["dividends"] if a < d <= day) / px

    def quick(self, sym, day, lookback, skip=0):
        """Cheap point-in-time stats for screening: {ret, above200, vol} or None (too little history).
        skip: leave out the last `skip` days of the return (12-1 momentum skips the last month)."""
        if sym not in self.charts:
            return None
        i = bisect.bisect_right(self.dates[sym], day) - 1
        if i < max(lookback, 200) or (self.dates[sym][i] < day and _gap(self.dates[sym][i], day) > 7):
            return None  # not enough history, or no longer trading
        c, sc, sr, sq = self._prefix(sym)
        if not c[i - lookback]:
            return None
        n = 126
        mean = (sr[i + 1] - sr[i + 1 - n]) / n
        var = max(0.0, (sq[i + 1] - sq[i + 1 - n]) / n - mean * mean)
        return {"ret": 100.0 * (c[i - skip] / c[i - lookback] - 1), "above200": c[i] > (sc[i + 1] - sc[i - 199]) / 200,
                "vol": 100.0 * (var * 252) ** 0.5}

    def fx(self, day):
        return self.close("USDCAD=X", day) or 1.35

    def trading_day_on_or_before(self, day):
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0:
            raise ReplayError("no prices before %s" % day)
        return self.days[i]


class Portfolio:
    """Cash and positions in their own currency, the way a Questrade or Wealthsimple account
    holds them: a US stock is bought with US dollars and sold back into US dollars, a Canadian
    one in Canadian dollars, with no conversion. A conversion (and its fee) happens only when
    a buy needs a currency the account has run out of. Values are reported in CAD."""

    def __init__(self, data, cash=100.0, account_type="TFSA", split=None, start=None, fx_fee=None):
        self.data, self.pos = data, {}
        self.fx_fee = COSTS["fx_fee_pct"] if fx_fee is None else fx_fee  # % per conversion: 1.5 bank, ~0.1 Norbert's gambit
        self.cash_by = {"CAD": 0.0, "USD": 0.0}
        split = split or {"CAD": 1.0}
        tot = sum(split.values()) or 1.0
        for ccy, w in split.items():  # $cash CAD worth, already sitting in each currency
            self.cash_by[ccy] = float(cash) * w / tot / (data.fx(start) if ccy == "USD" else 1.0)
        self.fees, self.trades, self.dividends_cad = 0.0, 0, 0.0
        self.fx_fees, self.slippage = 0.0, 0.0
        self.us_tax = COSTS["us_withholding_pct"] / 100.0 if account_type.upper() not in acc.NO_US_WITHHOLDING else 0
        self.log = []      # every fill, for the dashboard
        self.flow = {}     # ticker -> CAD paid in, CAD taken out (sales + dividends), at each day's rate
        self.curve = []    # [day, value at the close]
        self.cash_share = []

    def _ccy(self, sym):
        return (self.data.charts[sym]["currency"] or mk.native_currency(sym)).upper()

    def _rate(self, ccy, day):
        return self.data.fx(day) if ccy == "USD" else 1.0

    def cash_cad(self, day):
        return self.cash_by["CAD"] + self.cash_by["USD"] * self.data.fx(day)

    def _ensure(self, ccy, amount, day):
        """Make `amount` of `ccy` available, converting a shortfall from the other currency
        (paying the FX fee). Returns how much of `ccy` is there afterwards."""
        short = amount - self.cash_by[ccy]
        other = "CAD" if ccy == "USD" else "USD"
        if short > 1e-9 and self.cash_by[other] > 1e-9:
            fee, rate = self.fx_fee / 100.0, self.data.fx(day)
            per = (rate if ccy == "USD" else 1.0 / rate) * (1 + fee)  # other-currency cost of 1 unit of ccy
            got = min(short, self.cash_by[other] / per)
            self.cash_by[other] -= got * per
            self.cash_by[ccy] += got
            self._cost(got * per * self._rate(other, day) * fee / (1 + fee), 0.0)
        return self.cash_by[ccy]

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
            rate = self._rate(ccy, day)
            if o["side"] == "sell":
                p = self.pos.get(o["ticker"])
                if not p:
                    continue
                q = min(o["shares"], p["shares"])
                px = b["o"] * (1 - slip)
                self.cash_by[ccy] += q * px
                cad = q * px * rate
                self._cost(0.0, q * b["o"] * slip * rate)
                self.flow.setdefault(o["ticker"], [0.0, 0.0])[1] += cad
                p["shares"] -= q
                if p["shares"] <= 1e-9:
                    del self.pos[o["ticker"]]
            else:
                px = b["o"] * (1 + slip)
                q = o["shares"] if o.get("shares") else o["cad"] / rate / px  # sized in CAD at today's rate
                have = self._ensure(ccy, q * px, day)
                if q * px > have:
                    q = have / px
                if q <= 0 or q * px * rate < 0.5:
                    continue
                self.cash_by[ccy] -= q * px
                cad = q * px * rate
                self._cost(0.0, q * b["o"] * slip * rate)
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
        self.cash_share.append(self.cash_cad(day) / v if v > 0 else 1.0)

    def pay_dividends(self, day):
        for sym, p in self.pos.items():
            for d, amt in self.data.charts[sym]["dividends"]:
                if d == day:
                    net = amt * p["shares"] * (1 - (self.us_tax if p["currency"] == "USD" else 0))
                    self.cash_by[p["currency"]] += net  # paid in the stock's own currency
                    cad = net * self._rate(p["currency"], day)
                    self.dividends_cad += cad
                    self.flow.setdefault(sym, [0.0, 0.0])[1] += cad

    def value(self, day):
        v = self.cash_cad(day)
        for sym, p in self.pos.items():
            px = self.data.close(sym, day) or 0.0
            v += px * p["shares"] * self._rate(p["currency"], day)
        return v

    def doc(self, day):
        return {"cash": dict(self.cash_by), "as_of": day, "positions": [
            {"ticker": s, "shares": p["shares"], "currency": p["currency"],
             "avg_cost": p["cost"] / p["shares"] if p["shares"] else None,
             "last_price": self.data.close(s, day)} for s, p in self.pos.items()]}

    def result(self, day, start_cash):
        v = self.value(day)
        contrib = []
        for sym, (paid, back) in self.flow.items():
            p = self.pos.get(sym)
            now = (self.data.close(sym, day) or 0) * p["shares"] * self._rate(p["currency"], day) if p else 0.0
            contrib.append({"ticker": sym, "pnl": round(back + now - paid, 2), "held": bool(p)})
        contrib.sort(key=lambda c: -c["pnl"])
        return {"value": round(v, 2), "return_pct": round(100.0 * (v / start_cash - 1), 2), "trades": self.trades,
                "fees": round(self.fees, 2), "fx_fees": round(self.fx_fees, 2), "slippage": round(self.slippage, 2),
                "dividends": round(self.dividends_cad, 2), "holdings": sorted(self.pos),
                "cash_left": round(self.cash_cad(day), 2), "cash_by": {k: round(x, 2) for k, x in self.cash_by.items()},
                "contrib": contrib, "curve": self.curve,
                "cash_drag_pct": round(100.0 * sum(self.cash_share) / len(self.cash_share), 1)
                if self.cash_share else None, "fills": self.log[-40:]}


def currency_split(data, weights, day):
    """{'USD': w, 'CAD': w} for symbols {sym: weight}: the money starts where it will be spent."""
    out = {}
    for s, w in weights.items():
        if s in data.charts and w > 0:
            ccy = (data.charts[s]["currency"] or mk.native_currency(s)).upper()
            out[ccy] = out.get(ccy, 0.0) + w
    return out or {"CAD": 1.0}


def _held_values(data, shares, day):
    out = {}
    for t, q in shares.items():
        px = data.close(t, day)
        if px and q > 0:
            out[t] = q * px * (data.fx(day) if (data.charts[t]["currency"] or "USD").upper() == "USD" else 1.0)
    return out


def _review_days(days, start, asof, every=7):
    """The start, then the first trading day at least `every` calendar days after the last review."""
    out, last = set(), None
    for d in days:
        if start <= d < asof and (last is None or (_date(d) - _date(last)).days >= every):
            out.add(d)
            last = d
    return out


# ---------------------------------------------------------------- strategies

def _seed_orders(data, shares, start, cash):
    """Buy today's mix (share counts) in the same proportions at the first open after `start`."""
    vals = _held_values(data, shares, start)
    tot = sum(vals.values())
    return [{"side": "buy", "ticker": t, "cad": cash * 0.995 * v / tot, "decided": start} for t, v in vals.items()] \
        if tot else []


def run_mix(data, shares, start, asof, cash, account_type="TFSA"):
    """Your current holdings, in today's proportions, bought at the start and simply held."""
    pf = Portfolio(data, cash, account_type, currency_split(data, _held_values(data, shares, start), start), start)
    orders = _seed_orders(data, shares, start, cash)
    for d in [d for d in data.days if start <= d <= asof]:
        pf.pay_dividends(d)
        orders = pf.fill(orders, d)
        pf.mark(d)
    return pf.result(asof, cash)


SHORTLIST = {"growth": 20, "medium": 20, "dividend": 25}  # names the reviewer scores at each review


def candidates(uni, strategy, day):
    """What a strategy may choose from on `day`: index members that day, plus index funds
    and the Canadian list. The dividend account is Canadian: TSX names and Canadian income funds."""
    if strategy == "dividend":
        return set(univ.CANADA) | set(univ.ETFS["canada_income"])
    out = set(uni.members_on(day)) | set(univ.EQUITY_ETFS)
    if strategy == "medium":
        out |= set(univ.CANADA) | {s for v in univ.ETFS.values() for s in v}
    return out


def shortlist(data, strategy, day, rules, uni, k=None):
    """The scanner: rank every candidate with cheap point-in-time stats and pass the best
    to the reviewer. growth: strongest momentum above the 200-day average. medium: best
    momentum per unit of volatility, above the 200-day average, volatility under 45%.
    dividend: yield 2-8% and volatility under 30%, highest yield first."""
    k = k or SHORTLIST[strategy]
    mm = int(rules.get("momentum_months") or (6 if strategy == "medium" else 3))
    rows = []
    for sym in candidates(uni, strategy, day):
        q = data.quick(sym, day, 21 * mm)
        if not q:
            continue
        if strategy == "growth":
            if q["above200"]:
                rows.append((q["ret"], sym))
        elif strategy == "medium":
            if q["above200"] and q["vol"] < 45:
                rows.append((q["ret"] / max(q["vol"], 5.0), sym))
        else:
            y = data.yield_ttm(sym, day)
            if 2.0 <= y <= 8.0 and q["vol"] < 30:
                rows.append((y, sym))
    rows.sort(reverse=True)
    return [sym for _, sym in rows[:k]]


def coverage(data, uni, day):
    """How many index members that day have prices we can use (the rest are mostly companies
    that later left the market: the survivorship bias that remains)."""
    m = uni.members_on(day)
    priced = sum(1 for sym in m if data.quick(sym, day, 21))
    return {"day": day, "members": len(m), "priced": priced, "pct": round(100.0 * priced / len(m), 1) if m else None}


def run_account(data, strategy, watch, start, asof, cash, account_type, overrides=None, seed=None, uni=None):
    """uni: a point-in-time universe; the watchlist is then rebuilt at every review by the scanner."""
    rules = dict(acc.RULES[strategy], min_trade=1)
    rules.update(overrides or {})
    fixed = list(watch or []) if uni is not None else []  # e.g. your own holdings: always scored
    if uni is not None:
        watch = sorted(set(shortlist(data, strategy, start, rules, uni)) | set(watch or []))
    acct = {"id": strategy, "name": strategy, "strategy": strategy, "type": account_type, "fractional": True,
            "watchlist": watch, "rules": rules, "broker": ""}
    split = currency_split(data, _held_values(data, seed, start) if seed else {t: 1.0 for t in watch}, start)
    pf, pending, notes = Portfolio(data, cash, account_type, split, start), [], []
    days = [d for d in data.days if start <= d <= asof]
    reviews = _review_days(days, start, asof, int(rules.get("review_every_days") or 7))
    if seed:  # start from your current mix; the rules take over at the first review after that
        pending = _seed_orders(data, seed, start, cash)
        reviews.discard(start)
    for d in days:
        pf.pay_dividends(d)  # ex-date: only shares owned before today's open are paid
        pending = pf.fill(pending, d)
        pf.mark(d)
        if d not in reviews:
            continue
        if uni is not None and d != start:
            acct["watchlist"] = watch = sorted(set(shortlist(data, strategy, d, rules, uni)) | set(fixed))
        syms = set(watch) | set(pf.pos)
        snap = {s: data.metrics(s, d) for s in syms if s in data.charts}
        snap = {s: m for s, m in snap.items() if m}
        r = acc.review_account(acct, pf.doc(d), {"symbols": snap, "fx": {"USDCAD": data.fx(d)}}, base="CAD")
        pending = [{"side": o["side"], "ticker": o["ticker"], "shares": o["shares"], "decided": d}
                   for o in r["proposals"]]
        if d == start:
            notes = [f["text"] for f in r["flags"]][:2]
    out = pf.result(asof, cash)
    out["notes"] = notes
    return out


def run_targets(data, start, asof, cash, choose, every=28, split=None, fx_fee=None):
    """Equal weight in whatever choose(day) returns (a name listed twice gets two shares), or the
    weights it returns as {ticker: weight}; rebalanced every `every` days. choose sees only data
    up to that day's close; trades fill at the next open."""
    pf, pending = Portfolio(data, cash, split=split or {"USD": 1.0}, start=start, fx_fee=fx_fee), []
    days = [d for d in data.days if start <= d <= asof]
    reviews = _review_days(days, start, asof, every)
    picks_log = []
    for d in days:
        pf.pay_dividends(d)
        pending = pf.fill(pending, d)
        pf.mark(d)
        if d not in reviews:
            continue
        picked = choose(d)
        if isinstance(picked, dict):
            w = {t: x for t, x in picked.items() if x > 0 and data.close(t, d)}
        else:
            picked = [t for t in picked if data.close(t, d)]
            w = {t: picked.count(t) for t in dict.fromkeys(picked)}
        picks_log.append([d, sorted(w)])
        total = pf.value(d) * 0.995
        tw = sum(w.values())
        share = {t: total * x / tw for t, x in w.items()} if tw else {}
        target = list(share)
        pending = []
        for t, p in pf.pos.items():
            px = data.close(t, d) or 0.0
            now = px * p["shares"] * (data.fx(d) if p["currency"] == "USD" else 1.0)
            if t not in share:
                pending.append({"side": "sell", "ticker": t, "shares": p["shares"], "decided": d})
            elif now > share[t] * 1.2 and px:  # trim a winner that grew 20% past its share
                pending.append({"side": "sell", "ticker": t, "decided": d,
                                "shares": (now - share[t]) / (px * (data.fx(d) if p["currency"] == "USD" else 1.0))})
        for t in target:
            held, each = pf.pos.get(t), share[t]
            now = (data.close(t, d) or 0) * held["shares"] * (data.fx(d) if held["currency"] == "USD" else 1.0) \
                if held else 0.0
            if each - now > max(1.0, 0.2 * each) or (not held and each > 1.0):
                pending.append({"side": "buy", "ticker": t, "cad": each - now, "decided": d})
    out = pf.result(asof, cash)
    out["picks"] = picks_log[-40:]
    return out


MOMENTUM_DEFAULT = {"n": 20, "months": 12, "skip": 1, "trend": True, "every": 28, "buffer": 2, "market": False}


def run_momentum(data, uni, start, asof, cash, **opts):
    """Cross-sectional momentum, the textbook way: the n S&P 500 members (that day) with the
    best return over `months` leaving out the last `skip` month, above their 200-day average,
    equal weight, rebalanced every `every` days. A holding stays while it ranks in the top
    n x buffer (less turnover). market: hold IEF (bonds) while SPY is under its 200-day average."""
    o = dict(MOMENTUM_DEFAULT, **opts)
    held = []

    def choose(d):
        if o["market"]:
            q = data.quick("SPY", d, 21)
            if q and not q["above200"]:
                held[:] = []
                return ["IEF"] if "IEF" in data.charts else []
        rows = []
        for sym in uni.members_on(d):
            q = data.quick(sym, d, 21 * o["months"], 21 * o["skip"])
            if q and (q["above200"] or not o["trend"]):
                rows.append((q["ret"], sym))
        rank = [sym for _, sym in sorted(rows, reverse=True)]
        keep = [t for t in held if t in rank[:o["n"] * o["buffer"]]]
        out = keep + [t for t in rank if t not in keep][:max(0, o["n"] - len(keep))]
        held[:] = out
        return out
    return run_targets(data, start, asof, cash, choose, o["every"])


DUAL_DEFAULT = {"k": 1, "months": 12, "safe": "IEF", "cash_like": "SHY",  # best 1 fund: won the walk-forward
                "pool": "all", "vol_target": None, "trend": False, "core": None, "core_weight": 0.5,
                "core_trend": False, "lookbacks": None, "skip": 0, "margin": 0.0, "every": 28,
                "tranches": 1, "start_ccy": "USD", "fx_fee": None}
DUAL_POOL = ("us_broad", "us_sector", "us_factor", "world", "commodities")
DUAL_POOLS = {"all": DUAL_POOL, "growth": ("us_broad", "us_sector", "us_factor")}


def run_dual(data, start, asof, cash, **opts):
    """Dual momentum on index funds: each month hold the k funds with the best 12-month return
    (relative momentum), but only those beating short bonds (SHY, absolute momentum); the
    rest goes to IEF. A fund counts only once it has traded long enough to have the history.

    Safety options: pool "growth" (US broad, sector and factor funds only); trend (a fund
    must also be above its 200-day average); vol_target (hold target/volatility of a fund,
    at most all of it, the rest in IEF: less in wild markets); core ("QQQ"): that fund takes
    core_weight of the money, dual momentum the rest, rebalanced together every month.

    tranches: split the money into n slices, each re-chosen every `every` days but on different
    weeks (a review every every/n days updates one slice), so one unlucky rebalance date cannot
    decide the result. start_ccy / fx_fee: the money starts in that currency and pays that
    conversion fee (%) when it buys US funds (1.5 at a bank rate, about 0.1 with Norbert's gambit)."""
    o = dict(DUAL_DEFAULT, **opts)
    n = max(1, int(o["tranches"]))
    held, parts, turn = [None] * n, [], [0]

    def choose(d):
        i = turn[0] % n
        turn[0] += 1
        w = dual_weights(data, d, prev=held[i], **opts)
        held[i] = next((f for f in w if f not in (o["core"], o["safe"])), None)
        if not parts:
            parts.extend([w] * n)  # at the start every slice holds today's choice
        parts[i] = w
        out = {}
        for p in parts:
            for f, x in p.items():
                out[f] = out.get(f, 0.0) + x / n
        return out
    return run_targets(data, start, asof, cash, choose, max(1, o["every"] // n), split={o["start_ccy"]: 1.0},
                       fx_fee=o["fx_fee"])


def dual_weights(data, d, prev=None, **opts):
    """What dual momentum (with its options) would hold after the close of `d`: {fund: weight}.
    skip: leave out the last months of the return (12-1). margin: keep `prev` (the fund held)
    unless the best beats it by this many points (fewer switches for small differences)."""
    o = dict(DUAL_DEFAULT, **opts)
    pool = sorted({x for g in DUAL_POOLS[o["pool"]] for x in univ.ETFS[g] if not x.endswith(".TO")})
    looks = o["lookbacks"] or [o["months"]]

    def mom(sym):
        """Average return over the lookbacks (months), with the stats of the longest one."""
        qs = [data.quick(sym, d, 21 * m, 21 * o["skip"] if m > o["skip"] else 0) for m in looks]
        if not all(qs):
            return None
        q = dict(qs[0])  # trend and volatility do not depend on the lookback
        q["ret"] = sum(x["ret"] for x in qs) / len(qs)
        return q
    hurdle = (mom(o["cash_like"]) or {}).get("ret", 0.0)
    rows = [(q["ret"], f, q) for f in pool for q in [mom(f)] if q]
    ranked = sorted(rows, key=lambda x: -x[0])
    if o["margin"] and prev and o["k"] == 1 and ranked:
        mine = next((x for x in ranked if x[1] == prev), None)
        if mine and ranked[0][0] - mine[0] < o["margin"]:
            ranked = [mine] + [x for x in ranked if x[1] != prev]
    top = [(f, q) for r, f, q in ranked[:o["k"]] if r > hurdle and (q["above200"] or not o["trend"])]
    sat = 1.0 - (o["core_weight"] if o["core"] else 0.0)
    w = {}
    for f, q in top:
        scale = min(1.0, o["vol_target"] / max(q["vol"], 1.0)) if o["vol_target"] else 1.0
        w[f] = w.get(f, 0.0) + sat / o["k"] * scale
    if o["core"] and o["core"] in data.charts:
        cq = data.quick(o["core"], d, 21)
        if not o["core_trend"] or (cq and cq["above200"]):  # core_trend: bonds while the core is under its 200-day
            w[o["core"]] = w.get(o["core"], 0.0) + o["core_weight"]
    rest = 1.0 - sum(w.values())
    if rest > 1e-6 and o["safe"] in data.charts:
        w[o["safe"]] = w.get(o["safe"], 0.0) + rest
    return w


SIGNAL_DEFAULT = {"source": "insiders", "n": 20, "days": 60, "min_count": 2, "officers": False,
                  "trend": False, "fill": "SPY", "every": 28}


def run_signals(data, uni, sig, start, asof, cash, **opts):
    """Follow the people who know: S&P 500 members (that day) that insiders (Form 4 open-market
    purchases) or members of Congress were buying, as known from filings up to that day.
    Ranked by how many different insiders / members bought, then by dollars. Equal weight,
    at most n names; empty slots sit in `fill` (SPY). Rebalanced every `every` days.
    source "both": a name needs either signal; trend: also above its 200-day average."""
    o = dict(SIGNAL_DEFAULT, **opts)

    def choose(d):
        members = uni.members_on(d)
        rows = []
        if o["source"] in ("insiders", "both"):
            for t, x in sig.insider_buys(d, o["days"]).items():
                if x["insiders"] >= o["min_count"] and (not o["officers"] or x["officers"] >= 1):
                    rows.append(((x["insiders"], x["value"]), t))
        if o["source"] == "congress" and o.get("weighted"):
            import math
            rec = member_records(data, sig, d)
            score = {}
            for filed, member, t, side, low, high, traded, owner in sig.congress_rows(d, max(o["days"], 90)):
                edge = max(-1.0, min(1.0, rec.get(member, 0.0) / 10.0))  # a member's past edge, +-10 pts caps it
                score[t] = score.get(t, 0.0) + math.log1p((low or 1000) / 1000.0) * (1.0 + edge)
            rows += [((sc,), t) for t, sc in score.items() if sc > 0]
        elif o["source"] in ("congress", "both"):
            for t, x in sig.congress_buys(d, max(o["days"], 90)).items():
                if x["members"] >= o["min_count"]:
                    rows.append(((x["members"], x["low"]), t))
        picks = []
        for _, t in sorted(rows, reverse=True):
            q = data.quick(t, d, 21) if t in members else None
            if q and (q["above200"] or not o["trend"]) and t not in picks:
                picks.append(t)
        picks = picks[:o["n"]]
        return picks + [o["fill"]] * (o["n"] - len(picks)) if o["fill"] in data.charts else picks
    return run_targets(data, start, asof, cash, choose, o["every"])


def member_records(data, sig, day, horizon=63, years=3, min_trades=3):
    """{member: average return beyond the S&P 500 over the `horizon` trading days after each of
    their disclosed buys}, counting only buys whose outcome was known by `day`. Cached by month."""
    key = (day[:7], horizon, years)
    cache = data.__dict__.setdefault("_records", {})
    if key in cache:
        return cache[key]
    month_start = data.trading_day_on_or_before(day[:7] + "-01") if day[8:] != "01" else day
    per = {}
    for filed, member, t, side, low, high, traded, owner in sig.congress_rows(month_start, 365 * years):
        r, end = _fwd(data, t, filed, horizon)
        s_, s_end = _fwd(data, "SPY", filed, horizon)
        if r is None or s_ is None or end > month_start:
            continue
        per.setdefault(member, []).append(100.0 * (r - s_))
    cache[key] = {m: sum(x) / len(x) for m, x in per.items() if len(x) >= min_trades}
    return cache[key]


def run_momentum_signals(data, uni, sig, start, asof, cash, n=20, days=180, **opts):
    """Momentum, but only among S&P 500 members that insiders or Congress bought in the last
    `days` (filing dates): price strength confirmed by people with an information edge."""
    o = dict(MOMENTUM_DEFAULT, n=n, **opts)
    held = []

    def choose(d):
        backed = set(sig.insider_buys(d, days)) | set(sig.congress_buys(d, days))
        rows = []
        for sym in uni.members_on(d):
            if sym not in backed:
                continue
            q = data.quick(sym, d, 21 * o["months"], 21 * o["skip"])
            if q and (q["above200"] or not o["trend"]):
                rows.append((q["ret"], sym))
        rank = [sym for _, sym in sorted(rows, reverse=True)]
        keep = [t for t in held if t in rank[:o["n"] * o["buffer"]]]
        out = keep + [t for t in rank if t not in keep][:max(0, o["n"] - len(keep))]
        held[:] = out
        return out + ["SPY"] * (o["n"] - len(out)) if "SPY" in data.charts else out
    return run_targets(data, start, asof, cash, choose, o["every"])


def blend(parts, cash):
    """Split the money equally between strategies at the start and let each run on its own
    (no rebalancing between them): the blend's value is the sum of the parts' values."""
    parts = [p for p in parts if p and p.get("curve")]
    if not parts:
        return None
    n = len(parts)
    days = [d for d, _ in parts[0]["curve"]]
    by = [dict(p["curve"]) for p in parts]
    curve, last = [], [p["curve"][0][1] for p in parts]
    for d in days:
        last = [b.get(d, last[i]) for i, b in enumerate(by)]
        curve.append([d, round(sum(last) / n, 2)])
    v = curve[-1][1]
    held = sorted({h for p in parts for h in p.get("holdings", [])})
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2), "curve": curve,
            "trades": sum(p.get("trades", 0) for p in parts), "fees": round(sum(p.get("fees") or 0 for p in parts) / n, 2),
            "holdings": held, "contrib": [], "fills": []}


# ---------------------------------------------------------------- a learned score

FEATURES = ["mom_12_1", "mom_6_1", "rev_1m", "low_vol", "above200", "insiders", "congress"]
MODEL_DEFAULT = {"n": 20, "every": 28, "horizon": 21, "ridge": 10.0, "features": FEATURES, "core": None,
                 "core_weight": 0.7}


def _zscore(rows):
    """Standardise each column across the stocks of one date, capped at +-3."""
    import statistics
    if len(rows) < 10:
        return None
    cols = list(zip(*rows))
    out = []
    for c in cols:
        m, sd = statistics.mean(c), statistics.pstdev(c) or 1.0
        out.append([max(-3.0, min(3.0, (x - m) / sd)) for x in c])
    return [list(r) for r in zip(*out)]


def model_features(data, uni, sig, d, names=FEATURES):
    """{ticker: [feature values]} for S&P 500 members on `d`, from data known by its close."""
    import math
    ins = sig.insider_buys(d, 90) if sig and sig.insiders else {}
    con = sig.congress_buys(d, 180) if sig and sig.congress else {}
    out = {}
    for sym in uni.members_on(d):
        q12, q6 = data.quick(sym, d, 252, 21), data.quick(sym, d, 126, 21)
        q1 = data.quick(sym, d, 21)
        if not (q12 and q6 and q1):
            continue
        f = {"mom_12_1": q12["ret"], "mom_6_1": q6["ret"], "rev_1m": -q1["ret"], "low_vol": -q12["vol"],
             "above200": 1.0 if q12["above200"] else 0.0,
             "insiders": math.log1p((ins.get(sym) or {}).get("insiders", 0)),
             "congress": math.log1p((con.get(sym) or {}).get("members", 0))}
        out[sym] = [f[k] for k in names]
    return out


def _fwd(data, sym, d, n):
    ds = data.dates.get(sym) or []
    i = bisect.bisect_right(ds, d) - 1
    if i < 0 or i + n >= len(ds):
        return None, None
    bars = data.charts[sym]["bars"]
    return (bars[i + n]["c"] / bars[i]["c"] - 1) if bars[i]["c"] else None, ds[i + n]


def _solve(a, b):
    """Gaussian elimination for a small dense system."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit_model(data, uni, sig, cutoff, opts=None, first="2016-01-01"):
    """Ridge regression of each stock's next-month return relative to the other members,
    on standardised features, using only months whose outcome was known by `cutoff`."""
    o = dict(MODEL_DEFAULT, **(opts or {}))
    k = len(o["features"])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    n = 0
    month = None
    for d in data.days:
        if d < first or d > cutoff:
            continue
        if d[:7] == month:
            continue
        month = d[:7]
        feats = model_features(data, uni, sig, d, o["features"])
        rows, ys = [], []
        for sym, f in feats.items():
            y, end = _fwd(data, sym, d, o["horizon"])
            if y is None or end > cutoff:
                continue
            rows.append(f)
            ys.append(y)
        z = _zscore(rows)
        if not z:
            continue
        mean = sum(ys) / len(ys)
        ys = [max(-0.5, min(0.5, y - mean)) for y in ys]
        for x, y in zip(z, ys):
            for i in range(k):
                xty[i] += x[i] * y
                for j in range(k):
                    xtx[i][j] += x[i] * x[j]
            n += 1
    if n < 100:
        return None
    for i in range(k):
        xtx[i][i] += o["ridge"]
    return {"coef": _solve(xtx, xty), "samples": n, "cutoff": cutoff, "features": o["features"]}


def run_model(data, uni, sig, start, asof, cash, **opts):
    """Hold the n S&P 500 members with the best learned score, refitting every January on
    everything known by then (expanding window, point in time). core: a fund takes
    core_weight of the money, the model the rest."""
    o = dict(MODEL_DEFAULT, **opts)
    models = {}

    def model_for(d):
        cutoff = data.trading_day_on_or_before(d[:4] + "-01-01") if d[5:] != "01-01" else d
        if cutoff not in models:
            key = (cutoff, tuple(o["features"]), o["horizon"], o["ridge"], id(uni), id(sig))
            cache = data.__dict__.setdefault("_fits", {})  # many runs refit the same January
            if key not in cache:
                cache[key] = fit_model(data, uni, sig, cutoff, o)
            models[cutoff] = cache[key]
        return models[cutoff]

    def choose(d):
        m = model_for(d)
        feats = model_features(data, uni, sig, d, o["features"])
        if not m or len(feats) < 10:
            return {"SPY": 1.0} if "SPY" in data.charts else {}
        syms = list(feats)
        z = _zscore([feats[t] for t in syms])
        score = sorted(((sum(c * x for c, x in zip(m["coef"], zr)), t) for t, zr in zip(syms, z)), reverse=True)
        top = [t for _, t in score[:o["n"]]]
        sat = 1.0 - (o["core_weight"] if o["core"] else 0.0)
        w = {t: sat / len(top) for t in top}
        if o["core"] and o["core"] in data.charts:
            w[o["core"]] = w.get(o["core"], 0.0) + o["core_weight"]
        return w
    out = run_targets(data, start, asof, cash, choose, o["every"])
    out["models"] = {c: {"coef": dict(zip(m["features"], [round(x, 5) for x in m["coef"]])), "samples": m["samples"]}
                     for c, m in models.items() if m}
    return out


PEAD_DEFAULT = {"n": 20, "days": 60, "min_move": 3.0, "every": 7, "eps": None}


def pead_pick(data, uni, sig, d, n=20, days=60, min_move=3.0, eps=None):
    """Earnings drift: S&P 500 members (that day) whose earnings 8-K in the last `days` was met by
    a jump of at least `min_move` points beyond the S&P 500 on the first day the market could
    react. Strongest reactions first. Known by the close of `d`.

    eps "up": only if the quarter's diluted EPS (from the 10-Q or 10-K, once FILED, usually a few
    weeks after the 8-K) beat the same quarter a year earlier. eps "sue": the same, ranked by the
    size of that beat against the company's usual swings instead of by the price jump."""
    out = []
    for t, effs in sig.news(d, days, item="2.02").items():
        if t not in uni.members_on(d) or t not in data.charts:
            continue
        eff = max(effs)
        ds = data.dates[t]
        i = bisect.bisect_left(ds, eff)  # the first trading day on or after the filing took effect
        if i <= 0 or i >= len(ds) or ds[i] > d:
            continue
        before, react = ds[i - 1], ds[i]
        r = data.close(t, react) / data.close(t, before) - 1 if data.close(t, before) else None
        sp0, sp1 = data.close("SPY", before), data.close("SPY", react)
        if r is None or not sp0:
            continue
        x = 100.0 * (r - (sp1 / sp0 - 1))
        if x < min_move:
            continue
        if eps:
            e = sig.eps_surprise(t, d)
            if not e or e["change"] <= 0 or _gap(e["end"], eff) > 100:  # not this 8-K's quarter (yet)
                continue
            if eps == "sue":
                if e["sue"] is None:
                    continue
                x = e["sue"]
        out.append((x, t))
    return [t for _, t in sorted(out, reverse=True)[:n]]


def run_events(data, uni, sig, start, asof, cash, **opts):
    """Hold the earnings-drift picks equal weight, the rest in SPY; reviewed every `every` days."""
    o = dict(PEAD_DEFAULT, **opts)

    def choose(d):
        picks = pead_pick(data, uni, sig, d, o["n"], o["days"], o["min_move"], o["eps"])
        return picks + ["SPY"] * (o["n"] - len(picks)) if "SPY" in data.charts else picks
    return run_targets(data, start, asof, cash, choose, o["every"])


PLAN_DEFAULT = {"core": "QQQ", "core_weight": 0.7, "sleeves": {"dual": 1.0}, "every": 28, "n": 20}


def run_plan(data, uni, sig, start, asof, cash, **opts):
    """The core plus a satellite split between sleeves: 'dual' (dual momentum fund), 'momentum'
    (top n S&P 500 members by 12-1 momentum above their 200-day) and 'drift' (earnings drift)."""
    o = dict(PLAN_DEFAULT, **opts)
    sat = 1.0 - o["core_weight"]

    def choose(d):
        w = {}
        if o["core"] in data.charts:
            w[o["core"]] = o["core_weight"]
        for sleeve, share in o["sleeves"].items():
            part = sat * share
            if sleeve in ("dual", "copycat", "screen", "pelosi"):
                got = (dual_weights(data, d) if sleeve == "dual" else
                       copycat_weights(data, sig, d, **COPY_DEFAULT) if sleeve == "copycat" else
                       screen_weights(data, uni, sig, d, **SCREEN_DEFAULT) if sleeve == "screen" else
                       pelosi_weights(data, sig, d, **PELOSI_DEFAULT))
                for f, x in got.items():
                    w[f] = w.get(f, 0.0) + part * x
                continue
            if sleeve == "momentum":
                rows = [(q["ret"], t) for t in uni.members_on(d) for q in [data.quick(t, d, 252, 21)]
                        if q and q["above200"]]
                picks = [t for _, t in sorted(rows, reverse=True)[:o["n"]]]
            else:
                picks = pead_pick(data, uni, sig, d, o["n"], eps=o.get("eps")) if sig else []
            if not picks:
                w["SPY"] = w.get("SPY", 0.0) + part
            for t in picks:
                w[t] = w.get(t, 0.0) + part / len(picks)
        return w
    return run_targets(data, start, asof, cash, choose, o["every"])


# ---------------------------------------------------------------- the upstream agents, point in time

def _equal(picks):
    picks = list(dict.fromkeys(picks))
    return {t: 1.0 / len(picks) for t in picks} if picks else {"SPY": 1.0}


COPY_DEFAULT = {"mode": "top", "n": 3, "who": None, "min_count": 3, "trend": False}
COPY_VERSIONS = [
    ("C1", "Copycat: Berkshire's whole portfolio (what the upstream skill does)", {"mode": "book", "who": ["0001067983"]}),
    ("C2", "Copycat: all 23 investors' portfolios, an equal share each", {"mode": "book"}),
    ("C3", "Copycat: each investor's top 3 ideas (default)", {}),
    ("C4", "Copycat: consensus, in the top 10 of 3+ investors", {"mode": "consensus", "n": 10}),
    ("C5", "Copycat: new buys and big adds, top 3 per investor", {"mode": "new"}),
    ("C6", "Copycat: top 3 ideas, only while above the 200-day", {"trend": True}),
]


def copycat_weights(data, sig, d, mode="top", n=3, who=None, min_count=3, trend=False):
    """What the upstream copycat would hold after the close of `d`, from 13Fs the market could act
    on by then. book: each investor's reported portfolio (top 50 stocks) at its weights, an equal
    share per investor. top: each investor's n biggest positions. consensus: stocks in the top n
    of at least min_count investors. new: per investor, the n biggest positions that are new or at
    least 1.5x the shares of the report before. Stocks we have no prices for are skipped."""
    if not sig or not sig.f13:
        return {"SPY": 1.0}
    books = {}
    for cik in (who or sorted(sig.f13)):
        h = sig.holdings_13f(cik, d)
        if not h:
            continue
        ok = {t: v for t, v in h.items() if t in data.charts and data.close(t, d)
              and (not trend or (data.quick(t, d, 21) or {}).get("above200"))}
        if mode == "new":
            before = sig.holdings_13f(cik, d, back=1) or {}
            ok = {t: v for t, v in ok.items() if t not in before or v[1] >= 1.5 * max(before[t][1], 1)}
        if ok:
            books[cik] = sorted(ok.items(), key=lambda kv: -kv[1][0])
    w = {}
    if mode == "consensus":
        count = {}
        for rows in books.values():
            for t, _ in rows[:n]:
                count[t] = count.get(t, 0) + 1
        return _equal(sorted(t for t, c in count.items() if c >= min_count))
    for rows in books.values():
        rows = rows if mode == "book" else rows[:n]
        tot = sum(v[0] for _, v in rows) if mode == "book" else len(rows)
        for t, v in rows:
            share = (v[0] if mode == "book" else 1.0) / tot / len(books)
            w[t] = w.get(t, 0.0) + share
    return w or {"SPY": 1.0}


def run_copycat(data, sig, start, asof, cash, **opts):
    """The copycat's picks, checked weekly so a new 13F is acted on within days of being filed."""
    o = dict(COPY_DEFAULT, **opts)
    return run_targets(data, start, asof, cash, lambda d: copycat_weights(data, sig, d, **o), 7)


SCREEN_DEFAULT = {"top": 10, "growth": 10.0, "margin": 25.0, "pe": 35.0, "rank": "upstream"}
SCREEN_VERSIONS = [
    ("S1", "Screener: its own example rules, top 10 (default)", {}),
    ("S2", "Screener: the example rules, top 20", {"top": 20}),
    ("S3", "Screener: the example rules, then the 20 with the best 12-1 momentum", {"top": 20, "rank": "momentum"}),
    ("S4", "Screener: looser rules (growth 5%+, margin 15%+, P/E up to 50), top 20", {"top": 20, "growth": 5.0,
                                                                                       "margin": 15.0, "pe": 50.0}),
]


def screen_weights(data, uni, sig, d, top=10, growth=10.0, margin=25.0, pe=35.0, rank="upstream"):
    """The upstream screener's example ('Growing, profitable, not priced for perfection': revenue
    growth >= 10% a year, operating margin >= 25%, EPS > 0, P/E <= 35) run on what each S&P 500
    member that day had filed by then, with that day's price. rank "upstream": its own ranking
    (revenue growth twice, then low P/E and high margin); "momentum": best 12-1 month return."""
    if not sig or not sig.fund or uni is None:
        return {"SPY": 1.0}
    rows = []
    for t in uni.members_on(d):
        f = sig.fundamentals(t, d)
        px = data.close(t, d)
        if not f or not px or f["eps_ttm"] is None or f["eps_ttm"] <= 0 or f["rev_growth"] is None \
                or f["op_margin"] is None:
            continue
        p_e = px / f["eps_ttm"]
        if f["rev_growth"] >= growth and f["op_margin"] >= margin and p_e <= pe:
            mom = (data.quick(t, d, 252, 21) or {}).get("ret")
            rows.append({"t": t, "g": f["rev_growth"], "m": f["op_margin"], "pe": p_e, "mom": mom})
    if rank == "momentum":
        rows = sorted([r for r in rows if r["mom"] is not None], key=lambda r: -r["mom"])
    else:
        pos = {}
        for key, sign, weight in (("g", -1, 2), ("pe", 1, 1), ("m", -1, 1)):
            for i, r in enumerate(sorted(rows, key=lambda r: sign * r[key])):
                pos[r["t"]] = pos.get(r["t"], 0) + weight * i
        rows = sorted(rows, key=lambda r: (pos[r["t"]], r["t"]))
    return _equal([r["t"] for r in rows[:top]])


def run_screen(data, uni, sig, start, asof, cash, **opts):
    """The screener's picks, equal weight, re-screened monthly."""
    o = dict(SCREEN_DEFAULT, **opts)
    return run_targets(data, start, asof, cash, lambda d: screen_weights(data, uni, sig, d, **o), 28)


PELOSI_DEFAULT = {"mode": "mirror", "days": 365, "min_low": 0}
PELOSI_VERSIONS = [
    ("P1", "Pelosi: what she bought in the last year, sold when she sells (default)", {}),
    ("P2", "Pelosi: every buy kept a year, her sales ignored", {"mode": "hold"}),
    ("P3", "Pelosi: only trades of $1M or more, mirrored", {"min_low": 1000001}),
]


def pelosi_weights(data, sig, d, mode="mirror", days=365, min_low=0):
    """Nancy Pelosi's disclosed trades since 2015 (House PTRs, from the day each was filed): equal
    weight in what she bought in the last `days`. mirror: a later sale drops it."""
    if not sig or not sig.congress:
        return {"SPY": 1.0}
    rows = sorted(r for r in sig.congress_rows(d, days, "buy") + sig.congress_rows(d, days, "sell")
                  if "pelosi" in (r[1] or "").lower() and (r[4] or 0) >= min_low)
    held = []
    for filed, member, t, side, low, high, traded, owner in rows:
        if side == "buy" and t not in held:
            held.append(t)
        elif side == "sell" and mode == "mirror" and t in held:
            held.remove(t)
    return _equal([t for t in held if t in data.charts and data.close(t, d)])


def run_pelosi_signals(data, sig, start, asof, cash, **opts):
    o = dict(PELOSI_DEFAULT, **opts)
    return run_targets(data, start, asof, cash, lambda d: pelosi_weights(data, sig, d, **o), 7)


def upstream_version(code):
    """('copycat' | 'screener' | 'pelosi', name, options) for a version code like C3, S1 or P2."""
    for fam, rows in (("copycat", COPY_VERSIONS), ("screener", SCREEN_VERSIONS), ("pelosi", PELOSI_VERSIONS)):
        for c, name, over in rows:
            if c == code.upper():
                return fam, name, over
    raise ReplayError("no version %s (copycat C1-C6, screener S1-S4, Pelosi P1-P3)" % code)


def upstream_picks(code, data, uni, sig, day):
    """Today's weights for one version, as the upstream budget skill reads them (trader/targets.json)."""
    fam, name, over = upstream_version(code)
    w = (copycat_weights(data, sig, day, **dict(COPY_DEFAULT, **over)) if fam == "copycat" else
         screen_weights(data, uni, sig, day, **dict(SCREEN_DEFAULT, **over)) if fam == "screener" else
         pelosi_weights(data, sig, day, **dict(PELOSI_DEFAULT, **over)))
    return {"source": "%s %s, from filings public by %s (trader-replay --picks)" % (code.upper(), name, day),
            "as_of": day, "weights": [{"ticker": t, "weight": round(100.0 * x, 2)}
                                      for t, x in sorted(w.items(), key=lambda kv: -kv[1])]}


def upstream_rows(data, uni, sig, start, asof, cash):
    """The upstream agents' default versions, where their data was loaded."""
    out = {}
    if sig and sig.f13:
        out["copycat"] = run_copycat(data, sig, start, asof, cash)
    if sig and sig.fund:
        out["screener"] = run_screen(data, uni, sig, start, asof, cash)
    if sig and any("pelosi" in (r[1] or "").lower() for r in sig.congress):
        out["pelosi (since 2015)"] = run_pelosi_signals(data, sig, start, asof, cash)
    return out


UPSTREAM_PLANS = [
    ("K1", "70% Nasdaq 100 + 30% copycat top-3 ideas", {"sleeves": {"copycat": 1.0}}),
    ("K2", "70% Nasdaq 100 + 30% screener picks", {"sleeves": {"screen": 1.0}}),
    ("K3", "70% Nasdaq 100 + 30% Pelosi's buys", {"sleeves": {"pelosi": 1.0}}),
]


def run_hold(data, weights, start, asof, cash):
    pf = Portfolio(data, cash, split=currency_split(data, weights, start), start=start)
    orders = [{"side": "buy", "ticker": s, "cad": cash * w * 0.999, "decided": start} for s, w in weights.items()
              if s in data.charts]
    for d in [d for d in data.days if start <= d <= asof]:
        pf.pay_dividends(d)
        orders = pf.fill(orders, d)
        pf.mark(d)
    return pf.result(asof, cash)


VIX_SYM, VIX3M_SYM = "^VIX", "^VIX3M"
VIX_RULES = [
    ("VIX agent: Nasdaq 100 unless VIX > 30 (default)", {"mode": "level", "threshold": 30, "asset": "QQQ"}),
    ("VIX agent: S&P 500 unless VIX > 25", {"mode": "level", "threshold": 25}),
    ("VIX agent: S&P 500 unless VIX > 20", {"mode": "level", "threshold": 20}),
    ("VIX agent: S&P 500 unless VIX > 30", {"mode": "level", "threshold": 30}),
    ("VIX agent: S&P 500 while VIX is under its 50-day average", {"mode": "trend", "days": 50}),
    ("VIX agent: S&P 500 unless VIX > 3-month VIX (stress)", {"mode": "term"}),
    ("VIX agent: Nasdaq 100 unless VIX > 3-month VIX", {"mode": "term", "asset": "QQQ"}),
]


def run_vix_agent(data, start, asof, cash, rule=None):
    """Hold the S&P 500 while the VIX agent says risk-on, cash while it says risk-off.
    Decided at each close from VIX closes up to that day; acted on at the next open.
    The money stays in US dollars: out of the fund means US-dollar cash, no conversion.
    rule["asset"] picks the fund (SPY by default, QQQ for the Nasdaq 100)."""
    fund = (rule or {}).get("asset") or "SPY"
    if fund not in data.charts:
        fund = "SPY"
    rule = {k: v for k, v in (rule or {}).items() if k != "asset"}
    pf, pending, invested = Portfolio(data, cash, split={"USD": 1.0}, start=start), [], None
    days = [d for d in data.days if start <= d <= asof]
    on_days = switches = 0
    vix_dates = data.dates[VIX_SYM]
    v3_dates = data.dates.get(VIX3M_SYM) or []
    for d in days:
        pf.pay_dividends(d)
        pending = pf.fill(pending, d)
        pf.mark(d)
        if d == asof:
            break
        closes = [b["c"] for b in data.charts[VIX_SYM]["bars"][:bisect.bisect_right(vix_dates, d)]]
        c3 = [b["c"] for b in data.charts[VIX3M_SYM]["bars"][:bisect.bisect_right(v3_dates, d)]] if v3_dates else None
        on, _ = vix.decide(closes, rule, c3)
        on_days += 1 if on else 0
        if on and invested is not True:
            pending = [{"side": "buy", "ticker": fund, "cad": pf.value(d) * 0.995, "decided": d}]
        elif not on and invested is not False:  # risk-off also cancels a buy still waiting for the open
            pending = [{"side": "sell", "ticker": fund, "shares": pf.pos[fund]["shares"], "decided": d}] \
                if pf.pos.get(fund) else []
        if invested is not None and on != invested:
            switches += 1
        invested = on
    out = pf.result(asof, cash)
    out["switches"] = switches
    out["fund"] = fund
    out["risk_on_days_pct"] = round(100.0 * on_days / max(1, len(days) - 1), 1)
    return out


def vix_regimes(curve, data):
    """Average daily return by the VIX regime known at the PREVIOUS close, and the
    correlation of daily returns with daily VIX changes (descriptive only)."""
    import statistics
    buckets, pairs = {}, []
    for (d0, v0), (d1, v1) in zip(curve, curve[1:]):
        if not v0:
            continue
        r = v1 / v0 - 1
        x0, x1 = data.close(VIX_SYM, d0), data.close(VIX_SYM, d1)
        reg = vix.regime(x0)
        if reg:
            buckets.setdefault(reg, []).append(r)
        if x0 and x1:
            pairs.append((r, x1 / x0 - 1))
    out = {name: {"days": len(buckets.get(name, [])),
                  "avg_daily_pct": round(100 * statistics.mean(buckets[name]), 3) if buckets.get(name) else None}
           for _, name in vix.REGIMES}
    corr = None
    if len(pairs) > 10:
        a, b = [p[0] for p in pairs], [p[1] for p in pairs]
        sa, sb = statistics.pstdev(a), statistics.pstdev(b)
        if sa and sb:
            ma, mb = statistics.mean(a), statistics.mean(b)
            corr = round(sum((x - ma) * (y - mb) for x, y in pairs) / len(pairs) / (sa * sb), 2)
    out["corr_with_vix"] = corr
    return out


def run_stockbot(data, universe, start, asof, cash, overrides=None, uni=None, news=None):
    """The ATR bot with US-dollar cash: $cash CAD worth of USD at the start, valued in CAD.
    overrides: paper.PARAMS changes, e.g. {"idle": None} for the bot without its index sleeve.
    uni: trade any S&P 500 member, but only on days it was a member (instead of `universe`)."""
    fx0 = data.fx(start)
    usd0 = cash / fx0
    p = dict(paper.PARAMS, fractional=True, min_order=1)
    p.update(overrides or {})
    idle_bars = {b["d"]: b for b in data.charts[p["idle"]]["bars"]} if p.get("idle") in data.charts else None
    eligible = None
    if uni is not None:
        universe = [s for s in uni.ever(start, asof) if s in data.charts]
        eligible = uni.members_on
        if news is not None:  # news shock: only a breakout that came with company news (an 8-K) that week
            eligible = lambda day: uni.members_on(day) & set(news.news(day, 5))  # noqa: E731
    first = (_date(start) - datetime.timedelta(days=150)).isoformat()  # enough for the ATR and the regime
    charts = {}
    for s in universe:
        if s in data.charts:
            ds = data.dates[s]
            bars = data.charts[s]["bars"][bisect.bisect_left(ds, first):bisect.bisect_right(ds, asof)]
            if bars:
                charts[s] = {"bars": bars}
    days, bars_by, regime = paper.prepare(charts, p)
    led, idle = paper.new_ledger(usd0, p), []
    for d in days:
        if start <= d <= asof:
            paper.step(led, d, bars_by, regime, p, idle_bars, eligible)
            e = led["equity"][-1][1]
            idle.append(led["cash"] / e if e else 1.0)
    eq = led["equity"][-1][1] if led["equity"] else usd0
    v = eq * data.fx(asof)
    by = {}
    for t in led["trades"]:
        by[t["ticker"]] = by.get(t["ticker"], 0.0) + t["pnl"] * data.fx(t["exit_day"])
    for t, pos in led["positions"].items():
        by[t] = by.get(t, 0.0) + ((data.close(t, asof) or pos["entry"]) - pos["entry"]) * pos["shares"] * data.fx(asof)
    fees_usd = sum(abs(t["shares"]) * (t["entry"] + t["exit"]) * paper.PARAMS["cost_bps"] / 1e4 for t in led["trades"])
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2),
            "trades": len(led["trades"]) + len(led["positions"]),
            "fees": round(fees_usd * data.fx(asof), 2), "fx_fees": 0.0, "dividends": 0.0,
            "holdings": sorted(led["positions"]) + ([p["idle"]] if led.get("idle_shares") else []),
            "cash_left": None, "idle": p.get("idle"),
            "cash_drag_pct": round(100.0 * sum(idle) / len(idle), 1) if idle else None,
            "contrib": sorted(({"ticker": k, "pnl": round(x, 2), "held": k in led["positions"]} for k, x in by.items()),
                              key=lambda c: -c["pnl"]),
            "curve": [[d, round(e * data.fx(d), 2)] for d, e in led["equity"]],
            "fills": [{"day": t["exit_day"], "side": "round trip", "ticker": t["ticker"], "shares": t["shares"],
                       "price": t["exit"], "currency": "USD", "cad": round(t["pnl"] * data.fx(t["exit_day"]), 2)}
                      for t in led["trades"][-40:]],
            "win_rate_pct": paper.stats(led["equity"], led["trades"]).get("win_rate_pct") if led["trades"] else None}


def market_close_utc(day):
    """4 p.m. New York on `day`, as epoch seconds."""
    try:
        from zoneinfo import ZoneInfo
        t = datetime.datetime.combine(_date(day), datetime.time(16, 0), ZoneInfo("America/New_York"))
        return int(t.timestamp())
    except Exception:
        return int(datetime.datetime.combine(_date(day), datetime.time(20, 0), datetime.timezone.utc).timestamp())


def run_crypto(candles, data, start, asof, cash, workdir, overrides=None):
    cfg = dict(team.DEFAULTS)
    cfg.update(overrides or {})
    usd0 = cash / data.fx(start)  # US-dollar cash: crypto trades in USD, nothing is converted
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
    prices = {}
    for c, bs in candles.items():
        i = bisect.bisect_right(keys[c], t1 - iv)
        if i:
            prices[c] = bs[i - 1]["c"]
    eq = broker.account(prices)["equity"]
    v = eq * data.fx(asof)
    btc_hold = _btc_hold(candles, keys, t0, t1, iv, usd0, data, asof, cash)
    rate = data.fx(asof)
    daily = {}
    for row in team.trade_log.read(paths.equity):
        daily[row["time"][:10]] = float(row["equity"]) * rate
    if killed:  # the kill switch sold everything: US-dollar cash, flat, to the as-of close
        for d in data.days:
            if start <= d <= asof and d not in daily and (not daily or d > max(daily)):
                daily[d] = eq * data.fx(d)
    by = {}
    for t in team.trade_log.read(paths.trades):
        c = t["asset"].split("/")[0]
        by[c] = by.get(c, 0.0) + float(t["pnl"]) * rate
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2), "trades": s["trades"],
            "fees": round(s["fees_slippage"] * rate, 2), "fx_fees": 0.0, "dividends": 0.0,
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
    v = usd0 * candles["BTC"][b - 1]["c"] / candles["BTC"][a - 1]["c"] * data.fx(asof)
    return {"value": round(v, 2), "return_pct": round(100.0 * (v / cash - 1), 2),
            "curve": [], "trades": 1}


def load_candles(cfg, first, asof, offline=None):
    """({coin: bars}, errors) at cfg["interval_min"], from `first` minus the lookback to the as-of close.
    Offline: candles-<COIN>.json (15-minute) or candles-<COIN>-<minutes>.json."""
    iv = cfg["interval_min"]
    t0 = market_close_utc(first) - (cfg["lookback_bars"] + 4) * iv * 60
    if offline:
        out = {}
        for c in cfg["coins"]:
            p = os.path.join(offline, "candles-%s.json" % c if iv == 15 else "candles-%s-%d.json" % (c, iv))
            if os.path.exists(p):
                with open(p) as fh:
                    out[c] = json.load(fh)
        return out, []
    return team.candles.fetch(cfg["coins"], cfg["data"], t0, market_close_utc(asof) + iv * 60, iv)


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


def run_pelosi(data, filings, start, asof, cash, mode="mirror"):
    """Equal weight in what she disclosed buying; act only after each filing was posted.
    mode "mirror" also sells what she disclosed selling; "hold" keeps every buy (her sales
    are often old winners trimmed for taxes, and the copy learns of them weeks late)."""
    basket, pf, pending = [], Portfolio(data, cash, split={"USD": 1.0}, start=start), []
    lookback = (_date(start) - datetime.timedelta(days=PELOSI_LOOKBACK_DAYS)).isoformat()
    used = []

    def apply(rows):
        b, s = pelosi_signals(rows)
        for t in b:
            if t not in basket and t in data.charts:
                basket.append(t)
        for t in s:
            if t in basket and mode == "mirror":
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

BENCH = ("S&P 500 (SPY)", "Nasdaq 100 (QQQ)", "S&P 500 equal weight (RSP)", "TSX 60 (XIU.TO)", "Bitcoin (hold)", "cash")


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
    if VIX_SYM in data.charts:
        v0, v1 = data.close(VIX_SYM, start), data.close(VIX_SYM, asof)
        inside = [b["c"] for b in data.charts[VIX_SYM]["bars"] if start <= b["d"] <= asof]
        out.update(vix_start=v0, vix_end=v1, vix_max=round(max(inside), 2) if inside else None,
                   vix_regime=vix.regime(v1))
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
        qqq = (row.get("Nasdaq 100 (QQQ)") or {}).get("return_pct")
        refs = [(ref, ref_name)] + ([(qqq, "the Nasdaq 100")] if k == "growth" and qqq is not None else [])
        for ref, ref_name in refs:
            if ref is None:
                continue
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
        if k == "VIX agent" and r.get("switches") is not None:
            note = "in the market %.0f%% of days, switched %d times" % (r["risk_on_days_pct"], r["switches"])
            (good if r["switches"] <= 4 else bad).append(note + ("" if r["switches"] <= 4 else ": whipsaw costs"))
        reg = r.get("vix_regimes") or {}
        fear = [reg[n]["avg_daily_pct"] for n in ("nervous", "fear") if reg.get(n, {}).get("avg_daily_pct") is not None]
        if fear and min(fear) < -0.3:
            bad.append("lost %.2f%% a day on average when the VIX was 20+" % -min(fear))
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


# ---------------------------------------------------------------- scenarios: same strategy, different settings

SCENARIOS = [
    ("growth", "Default: aggressive (3-month momentum, 30% cap, no cash)", {}),
    ("growth", "Previous default (12-month momentum, 20% cap, 3% cash)", {"momentum_months": 12, "max_position_pct": 20,
                                                                         "min_positions": 6, "cash_target_pct": 3}),
    ("growth", "12-month momentum", {"momentum_months": 12}),
    ("growth", "6-month momentum", {"momentum_months": 6}),
    ("growth", "Concentrated: 40% cap, 3+ names", {"max_position_pct": 40, "min_positions": 3}),
    ("growth", "Diversified: 10% cap, 10+ names", {"max_position_pct": 10, "min_positions": 10}),
    ("growth", "Tight stop: 15%", {"stop_loss_pct": 15}),
    ("growth", "Rebalance monthly", {"review_every_days": 28}),
    ("growth", "Monthly, 10% cap, 10+ names", {"review_every_days": 28, "max_position_pct": 10, "min_positions": 10}),
    ("growth", "6-month momentum, monthly", {"momentum_months": 6, "review_every_days": 28}),
    ("growth", "Rebalance quarterly", {"review_every_days": 91}),
    ("medium", "Default (6-month trend, 15% cap)", {}),
    ("medium", "Long trend: 12 months", {"momentum_months": 12}),
    ("medium", "Rebalance monthly", {"review_every_days": 28}),
    ("medium", "Rebalance quarterly", {"review_every_days": 91}),
    ("medium", "Monthly, 10% cap, 10+ names", {"review_every_days": 28, "max_position_pct": 10, "min_positions": 10}),
    ("dividend", "Default (2% yield floor, 12% cap)", {}),
    ("dividend", "Higher yield floor: 3.5%", {"min_yield_pct": 3.5}),
    ("dividend", "Rebalance monthly", {"review_every_days": 28}),
    ("dividend", "Rebalance quarterly", {"review_every_days": 91}),
]


def scenario_list(base):
    """Built-in scenarios + 'Your settings' (rules saved in accounts.json) + trader/replay/scenarios.json."""
    out = list(SCENARIOS)
    cfg = acc.read_json(os.path.join(base, "accounts.json"), {}) or {}
    for a in cfg.get("accounts", []):
        mine = {k: v for k, v in (a.get("rules") or {}).items() if k in acc.TUNABLE}
        if mine and a.get("strategy") in acc.RULES:
            out.append((a["strategy"], "Your settings (%s)" % a.get("name", a["id"]), mine))
    for x in acc.read_json(os.path.join(base, "replay", "scenarios.json"), []) or []:
        try:
            out.append((x["strategy"], x["name"], acc.check_rules(x["strategy"], x.get("rules"))))
        except (KeyError, acc.AccountsError):
            continue
    return out


def run_scenarios(data, watch, starts, asof, cash, account_type, scenarios, uni=None):
    rows = []
    if uni is not None:  # the old way, for comparison: today's hand-picked watchlists, replayed into the past
        scenarios = list(scenarios) + [(st, "Today's hand-picked watchlist (hindsight)", {"_fixed": True})
                                       for st in ("growth", "medium", "dividend")]
    for strategy, name, over in scenarios:
        fixed = over.get("_fixed")
        over = {k: v for k, v in over.items() if k != "_fixed"}
        row = {"strategy": strategy, "name": name, "inputs": dict(over) if not fixed else {"watchlist": "today's picks"},
               "settings": {k: dict(acc.RULES[strategy], **over).get(k) for k in acc.TUNABLE
                            if strategy in acc.TUNABLE[k][3]}, "results": {}}
        for label, start in starts:
            r = run_account(data, strategy, watch[strategy] if (fixed or uni is None) else [], start, asof, cash,
                            account_type, over, uni=None if fixed else uni)
            row["results"][label] = {"value": r["value"], "return_pct": r["return_pct"], "trades": r["trades"],
                                     "fees": r["fees"], "holdings": r["holdings"]}
            if label == starts[0][0]:
                row["risk"] = risk_stats(r["curve"]) if len(r["curve"]) > 20 else None
        rows.append(row)
    return rows


STOCKBOT_VARIANTS = [
    ("Stock bot: trades + idle cash in QQQ (default)", {}),
    ("Stock bot: trades only, idle cash stays cash", {"idle": None}),
    ("Stock bot: trades + idle cash in SPY", {"idle": "SPY"}),
    ("Stock bot: idle in QQQ, hold 5 days", {"hold_days": 5}),
]
MOMENTUM_VARIANTS = [
    ("Momentum: top 20, 12-1 months, above trend (default)", {}),
    ("Momentum: top 10", {"n": 10}),
    ("Momentum: top 40", {"n": 40}),
    ("Momentum: 6-1 months", {"months": 6}),
    ("Momentum: bonds while the S&P 500 is under its 200-day", {"market": True}),
    ("Momentum: no trend filter", {"trend": False}),
]
SIGNAL_VARIANTS = [
    ("insider buys", "Insiders: 2+ buying in 60 days (default)", {}),
    ("insider buys", "Insiders: 3+ buying in 60 days", {"min_count": 3}),
    ("insider buys", "Insiders: 1+ officer buying, 90 days", {"min_count": 1, "officers": True, "days": 90}),
    ("insider buys", "Insiders: 2+, above the 200-day average", {"trend": True}),
    ("insider buys", "Insiders: 2+, top 10", {"n": 10}),
    ("congress buys", "Congress: 2+ members buying in 90 days (default)", {"source": "congress", "days": 90}),
    ("congress buys", "Congress: any member buying in 90 days", {"source": "congress", "days": 90, "min_count": 1}),
    ("congress buys", "Congress: 2+ members, 180 days", {"source": "congress", "days": 180}),
    ("congress buys", "Insiders or Congress, 2+ buyers", {"source": "both", "days": 90}),
    ("congress buys", "Congress: weighted by size and each member's past record", {"source": "congress", "days": 90,
                                                                                  "weighted": True}),
]
DUAL_VARIANTS = [
    ("Dual momentum: best 1 fund (default)", {}),
    ("Dual momentum: best 2 funds", {"k": 2}),
    ("Dual momentum: growth funds only", {"pool": "growth"}),
    ("Dual momentum: volatility target 15%", {"vol_target": 15}),
    ("Dual momentum: volatility target 20%", {"vol_target": 20}),
    ("Dual momentum: fund above its 200-day only", {"trend": True}),
    ("Dual momentum: best 2, growth funds, volatility target 20%", {"k": 2, "pool": "growth", "vol_target": 20}),
    ("Dual momentum: best 3 funds", {"k": 3}),
    ("Dual momentum: best 5 funds", {"k": 5}),
    ("Dual momentum: 6-month lookback", {"months": 6}),
]
CORE_DEFAULT = {"core": "QQQ", "core_weight": 0.7, "every": 14}  # chosen in the walk-forward (pit-v11-news, rule v4)
CORE_VARIANTS = [
    ("Core: 70% Nasdaq 100, 30% dual momentum, monthly (previous plan)", {"core": "QQQ", "core_weight": 0.7}),
    ("Core: half Nasdaq 100, half dual momentum, rebalanced monthly", {"core": "QQQ", "core_weight": 0.5}),
    ("Core: half Nasdaq 100, half dual momentum (volatility target 15%)", {"core": "QQQ", "core_weight": 0.5,
                                                                         "vol_target": 15}),
    ("Core: half Nasdaq 100, half dual momentum (best 2, growth funds)", {"core": "QQQ", "core_weight": 0.5, "k": 2,
                                                                        "pool": "growth"}),
    ("Core: 70/30, Nasdaq 100 only above its 200-day (else bonds)", {"core": "QQQ", "core_weight": 0.7,
                                                                       "core_trend": True}),
    ("Core: 70/30, dual momentum on 1/3/6/12-month average", {"core": "QQQ", "core_weight": 0.7,
                                                                "lookbacks": [1, 3, 6, 12]}),
    ("Core: 70/30, both (trend switch + blended lookbacks)", {"core": "QQQ", "core_weight": 0.7, "core_trend": True,
                                                                "lookbacks": [1, 3, 6, 12]}),
    ("Core: 50/50, both (trend switch + blended lookbacks)", {"core": "QQQ", "core_weight": 0.5, "core_trend": True,
                                                                "lookbacks": [1, 3, 6, 12]}),
    ("Core: Nasdaq 100 only above its 200-day, else bonds", {"core": "QQQ", "core_weight": 1.0, "core_trend": True}),
]
PEAD_VARIANTS = [
    ("Earnings drift: top 20 jumps of 3+ pts, held about 60 days (default)", {}),
    ("Earnings drift: jumps of 5+ pts", {"min_move": 5.0}),
    ("Earnings drift: held about 30 days", {"days": 30}),
    ("Earnings drift: only if EPS beat the same quarter a year ago", {"eps": "up"}),
    ("Earnings drift: ranked by earnings surprise (EPS vs a year ago)", {"eps": "sue"}),
]
PLAN_VARIANTS = [  # adjustments to 70% Nasdaq 100 + 30% dual momentum
    ("Plan A: dual momentum on 12-1 months", {"core": "QQQ", "core_weight": 0.7, "skip": 1}),
    ("Plan B: rebalanced every 2 weeks (default)", {"core": "QQQ", "core_weight": 0.7, "every": 14}),
    ("Plan C: satellite half dual momentum, half earnings drift", {"plan": True, "sleeves": {"dual": 0.5, "drift": 0.5}}),
    ("Plan D: satellite = top 20 momentum stocks", {"plan": True, "sleeves": {"momentum": 1.0}}),
    ("Plan E: switch funds only for a 5-point lead", {"core": "QQQ", "core_weight": 0.7, "margin": 5.0}),
    ("Plan F: 4 slices, one re-chosen each week (each monthly)", {"core": "QQQ", "core_weight": 0.7, "tranches": 4}),
    ("Plan G: 2 slices, one re-chosen every 2 weeks (each monthly)", {"core": "QQQ", "core_weight": 0.7, "tranches": 2}),
    ("Plan H: satellite half dual momentum, half earnings drift with EPS up",
     {"plan": True, "sleeves": {"dual": 0.5, "drift": 0.5}, "eps": "up"}),
    ("Plan, money starts in CAD: bank conversion 1.5%", {"core": "QQQ", "core_weight": 0.7, "every": 14,
                                                          "start_ccy": "CAD", "fx_fee": 1.5}),
    ("Plan, money starts in CAD: Norbert's gambit about 0.1%", {"core": "QQQ", "core_weight": 0.7, "every": 14,
                                                                 "start_ccy": "CAD", "fx_fee": 0.1}),
]
MODEL_VARIANTS = [
    ("Learned score: top 20 (default)", {}),
    ("Learned score: top 40", {"n": 40}),
    ("Learned score: price features only", {"features": ["mom_12_1", "mom_6_1", "rev_1m", "low_vol", "above200"]}),
    ("Learned score: 70% Nasdaq 100 + 30% top 20", {"core": "QQQ"}),
]
PELOSI_VARIANTS = [("Pelosi: mirror buys and sells", "mirror"), ("Pelosi: keep every buy", "hold")]
CRYPTO_VARIANTS = [
    ("Crypto team: 1-day bars (default)", {"interval_min": 1440}),
    ("Crypto team: 15-minute bars (the guide)", {"interval_min": 15}),
    ("Crypto team: 6-hour bars", {"interval_min": 360}),
    ("Crypto team: 1-day bars, Bitcoin and Ether only", {"interval_min": 1440, "coins": ["BTC", "ETH"]}),
]


def agent_scenarios(data, ctx, starts, asof, cash, longest):
    """The bots under different settings: stock bot, VIX agent, Pelosi copycat, crypto team."""
    rows = []

    def add(strategy, name, inputs, run, max_days=None):
        row = {"strategy": strategy, "name": name, "inputs": dict(inputs), "settings": dict(inputs), "results": {}}
        for label, start in starts:
            if max_days and (_date(asof) - _date(start)).days > max_days + 4:
                row["results"][label] = None
                continue
            r = run(start)
            row["results"][label] = {"value": r["value"], "return_pct": r["return_pct"], "trades": r["trades"],
                                     "fees": r["fees"], "holdings": r["holdings"]}
            if label == longest:
                row["risk"] = risk_stats(r["curve"]) if len(r.get("curve") or []) > 20 else None
        rows.append(row)
    for name, over in STOCKBOT_VARIANTS:
        add("stock bot", name, over, lambda st, o=over: run_stockbot(data, ctx["universe"], st, asof, cash, o,
                                                                     uni=ctx.get("uni")))
    if ctx.get("uni") is not None:
        add("stock bot", "Stock bot: today's 30 hand-picked large caps (hindsight)", {"universe": "today's picks"},
            lambda st: run_stockbot(data, ctx["universe"], st, asof, cash))
        for name, over in MOMENTUM_VARIANTS:
            add("momentum", name, over, lambda st, o=over: run_momentum(data, ctx["uni"], st, asof, cash, **o))
        for name, over in DUAL_VARIANTS:
            add("dual momentum", name, over, lambda st, o=over: run_dual(data, st, asof, cash, **o))
        if "QQQ" in data.charts:
            for name, over in CORE_VARIANTS:
                add("core + dual", name, over, lambda st, o=over: run_dual(data, st, asof, cash, **o))
        sig = ctx.get("signals")
        if sig and sig.events:
            for name, over in PEAD_VARIANTS:
                if over.get("eps") and not sig.eps:
                    continue
                add("news", name, over, lambda st, o=over: run_events(data, ctx["uni"], sig, st, asof, cash, **o))
            add("news", "News shock: stock bot trades only breakouts with an 8-K that week", {"news": "8-K"},
                lambda st: run_stockbot(data, ctx["universe"], st, asof, cash, uni=ctx["uni"], news=sig))
        if "QQQ" in data.charts:
            for name, over in PLAN_VARIANTS:
                if "drift" in over.get("sleeves", {}) and not (sig and sig.events and (sig.eps or not over.get("eps"))):
                    continue
                if "plan" in over:
                    add("core + dual", name, over, lambda st, o=over: run_plan(
                        data, ctx["uni"], sig, st, asof, cash, **{k: v for k, v in o.items() if k != "plan"}))
                else:
                    add("core + dual", name, over, lambda st, o=over: run_dual(data, st, asof, cash, **o))
        for name, over in MODEL_VARIANTS:
            add("model", name, over, lambda st, o=over: run_model(data, ctx["uni"], ctx.get("signals"), st, asof, cash, **o))
        sig = ctx.get("signals")
        if sig and sig.f13:  # the upstream agents, every version (C: copycat, S: screener, P: Pelosi, K: plans)
            for code, name, over in COPY_VERSIONS:
                add("copycat", "%s. %s" % (code, name), over,
                    lambda st, o=over: run_copycat(data, sig, st, asof, cash, **o))
        if sig and sig.fund:
            for code, name, over in SCREEN_VERSIONS:
                add("screener", "%s. %s" % (code, name), over,
                    lambda st, o=over: run_screen(data, ctx["uni"], sig, st, asof, cash, **o))
        if sig and sig.congress:
            for code, name, over in PELOSI_VERSIONS:
                add("pelosi", "%s. %s" % (code, name), over,
                    lambda st, o=over: run_pelosi_signals(data, sig, st, asof, cash, **o))
        if sig and "QQQ" in data.charts:
            for code, name, over in UPSTREAM_PLANS:
                need = {"copycat": sig.f13, "screen": sig.fund, "pelosi": sig.congress}[next(iter(over["sleeves"]))]
                if need:
                    add("core + upstream", "%s. %s" % (code, name), over,
                        lambda st, o=over: run_plan(data, ctx["uni"], sig, st, asof, cash, **o))
    sig = ctx.get("signals")
    if ctx.get("uni") is not None and sig:
        for fam, name, over in SIGNAL_VARIANTS:
            if over.get("source", "insiders") in ("insiders", "both") and not sig.insiders:
                continue
            if over.get("source") in ("congress", "both") and not sig.congress:
                continue
            add(fam, name, over, lambda st, o=over: run_signals(data, ctx["uni"], sig, st, asof, cash, **o))
        add("momentum", "Momentum: only names insiders or Congress bought (180 days)", {"backed": "180 days"},
            lambda st: run_momentum_signals(data, ctx["uni"], sig, st, asof, cash))
    if VIX_SYM in data.charts:
        for name, rule in VIX_RULES:
            add("vix", name, rule, lambda st, r=rule: run_vix_agent(data, st, asof, cash, r))
    if "pelosi" not in ctx["skip"]:
        for name, mode in PELOSI_VARIANTS:
            add("pelosi", name, {"mode": mode}, lambda st, m=mode: run_pelosi(data, ctx["filings"], st, asof, cash, m))
    if "crypto" not in ctx["skip"]:
        for name, over in CRYPTO_VARIANTS:
            cfg = dict(team.DEFAULTS, **over)
            limit = CRYPTO_MAX_DAYS if cfg["interval_min"] < 60 else CRYPTO_LONG_DAYS
            first = min(st for _, st in starts if (_date(asof) - _date(st)).days <= limit + 4)
            if cfg["interval_min"] == team.DEFAULTS["interval_min"] and ctx.get("candles"):
                candles, errs = ctx["candles"], []  # already loaded for the main table
            else:
                candles, errs = load_candles(cfg, first, asof, ctx["offline"])
            ctx["errors"].extend(errs)
            if not candles:
                continue
            work = os.path.join(ctx["base"], "replay", "crypto-scenario")
            add("crypto", name, over, lambda st, c=candles, o=over: run_crypto(c, data, st, asof, cash, work, o), limit)
    return rows


# ---------------------------------------------------------------- risk stats and Monte Carlo

def daily_returns(curve):
    vals = [v for _, v in curve]
    return [b / a - 1 for a, b in zip(vals, vals[1:]) if a]


def risk_stats(curve):
    """Annualised volatility, Sharpe (risk-free 0), max drawdown, share of up days."""
    import math
    import statistics
    r = daily_returns(curve)
    if len(r) < 10:
        return None
    vals = [v for _, v in curve]
    peak, dd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    sd = statistics.pstdev(r)
    return {"vol_pct": round(100 * sd * math.sqrt(252), 2),
            "sharpe": round(statistics.mean(r) / sd * math.sqrt(252), 2) if sd else None,
            "max_dd_pct": round(100 * dd, 2), "up_days_pct": round(100.0 * sum(1 for x in r if x > 0) / len(r), 1),
            "days": len(r)}


def _pct(sorted_vals, q):
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def mc_curves(row):
    """Daily curves long enough to simulate. One short curve (e.g. crypto with little history)
    would shrink everyone's sample, because all strategies share the same days, so it sits out."""
    curves = {k: r["curve"] for k, r in row.items()
              if isinstance(r, dict) and r.get("curve") and len(r["curve"]) > 20}
    full = max((len(c) for c in curves.values()), default=0)
    short = sorted(k for k, c in curves.items() if len(c) < 0.8 * full)
    for k in short:
        del curves[k]
    return curves, short


def monte_carlo(curves, bench="S&P 500 (SPY)", runs=5000, horizon=126, block=5, seed=7, cash=100.0):
    """Block bootstrap of the strategies' own daily returns, the same days for every strategy
    (so their link to the market is kept). Returns outcome percentiles and success rates."""
    import random
    rets = {k: daily_returns(c) for k, c in curves.items()}
    n = min((len(r) for r in rets.values()), default=0)
    if n < 2 * block or bench not in rets:
        return None
    rets = {k: r[-n:] for k, r in rets.items()}  # align on the same last n days
    rng = random.Random(seed)
    ends = {k: [] for k in rets}
    dds = {k: [] for k in rets}
    beat = {k: 0 for k in rets}
    fan_days = list(range(0, horizon + 1, max(1, horizon // 25)))
    fan = {k: {d: [] for d in fan_days} for k in rets}
    for _ in range(runs):
        idx = []
        while len(idx) < horizon:
            s0 = rng.randrange(0, n - block + 1)
            idx.extend(range(s0, s0 + block))
        idx = idx[:horizon]
        final = {}
        for k, r in rets.items():
            v, peak, dd = cash, cash, 0.0
            fk = fan[k]
            if 0 in fk:
                fk[0].append(v)
            for step, i in enumerate(idx, 1):
                v *= 1 + r[i]
                peak = max(peak, v)
                dd = min(dd, v / peak - 1)
                if step in fk:
                    fk[step].append(v)
            final[k] = v
            ends[k].append(v)
            dds[k].append(dd)
        for k in rets:
            if final[k] > final[bench]:
                beat[k] += 1
    out = {"runs": runs, "horizon_days": horizon, "block_days": block, "sample_days": n, "strategies": {}}
    for k in rets:
        e, d = sorted(ends[k]), sorted(dds[k])
        out["strategies"][k] = {
            "p5": round(_pct(e, 0.05), 2), "p25": round(_pct(e, 0.25), 2), "median": round(_pct(e, 0.5), 2),
            "p75": round(_pct(e, 0.75), 2), "p95": round(_pct(e, 0.95), 2),
            "prob_profit_pct": round(100.0 * sum(1 for x in e if x > cash) / runs, 1),
            "prob_loss_10_pct": round(100.0 * sum(1 for x in e if x < cash * 0.9) / runs, 1),
            "prob_beat_bench_pct": None if k == bench else round(100.0 * beat[k] / runs, 1),
            "median_max_dd_pct": round(100 * _pct(d, 0.5), 2), "bad_max_dd_pct": round(100 * _pct(d, 0.05), 2),
            "fan": [[day, round(_pct(sorted(v), 0.05), 2), round(_pct(sorted(v), 0.5), 2), round(_pct(sorted(v), 0.95), 2)]
                    for day, v in sorted(fan[k].items()) if v]}
    return out


# ---------------------------------------------------------------- your holdings

def my_holdings(base, extra=None):
    """{account id: {name, strategy, type, shares}} from trader/accounts/<id>.json, plus any
    --holdings ID=FILE CSVs. These stay on your computer: the replay writes them only to trader/."""
    cfg = acc.read_json(os.path.join(base, "accounts.json"), {}) or {}
    out = {}
    for a in cfg.get("accounts", []):
        h = acc.read_json(os.path.join(base, "accounts", "%s.json" % a.get("id")), {}) or {}
        shares = {}
        for p in h.get("positions", []):
            shares[mk.yahoo_symbol(p["ticker"])] = shares.get(mk.yahoo_symbol(p["ticker"]), 0) + float(p["shares"])
        if shares and h.get("source") != "demo":
            out[a["id"]] = {"name": a.get("name", a["id"]), "strategy": a.get("strategy", "growth"),
                            "type": a.get("type", "TFSA"), "shares": shares, "rules": a.get("rules") or {}}
    for spec in extra or []:
        aid, _, path = spec.partition("=")
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            doc = acc.parse_holdings_csv(fh.read(), aid)
        a = [x for x in cfg.get("accounts", []) if x.get("id") == aid]
        shares = {p["ticker"]: float(p["shares"]) for p in doc["positions"]}
        out[aid] = {"name": a[0].get("name", aid) if a else aid, "strategy": a[0].get("strategy", "growth") if a else "growth",
                    "type": a[0].get("type", "TFSA") if a else "TFSA", "shares": shares,
                    "rules": (a[0].get("rules") or {}) if a else {}}
    return out


def mine_rows(data, mine, watch, start, end, cash, uni=None):
    rows, labels = {}, {}
    for aid, m in mine.items():
        held = {t: q for t, q in m["shares"].items() if t in data.charts}
        if not held:
            continue
        k1, k2 = "mine:%s:held" % aid, "mine:%s:rules" % aid
        rows[k1] = run_mix(data, held, start, end, cash, m["type"])
        over = {k: v for k, v in m["rules"].items() if k in acc.TUNABLE}
        rows[k2] = run_account(data, m["strategy"], sorted(set(held) if uni else set(watch[m["strategy"]]) | set(held)),
                               start, end, cash, m["type"], over, seed=held, uni=uni)
        labels[k1] = "Your %s, held as is" % m["name"]
        labels[k2] = "Your %s, run by its %s rules" % (m["name"], m["strategy"])
    return rows, labels


# ---------------------------------------------------------------- rolling windows: does it KEEP working?

def rolling(data, watch, universe, filings, mine, asof, cash, account_type, spec=ROLLING, include_pelosi=True, uni=None,
            sig=None):
    """Many equal-length windows (default 3 months, a new one each month for a year). The
    question is not 'did it win once' but 'how often did it beat the S&P 500'."""
    starts = []
    for i in range(spec["count"]):
        end_target = _date(asof) - datetime.timedelta(days=i * spec["step_days"])
        end = data.trading_day_on_or_before(end_target.isoformat())
        start = data.trading_day_on_or_before((end_target - datetime.timedelta(days=spec["horizon_days"])).isoformat())
        if start < end:
            starts.append((start, end))
    runs = {}
    for start, end in reversed(starts):
        row = {s: run_account(data, s, [] if uni else watch[s], start, end, cash, account_type, uni=uni)
               for s in ("growth", "medium", "dividend")}
        row["stock bot"] = run_stockbot(data, universe, start, end, cash, uni=uni)
        if uni is not None:
            row["momentum"] = run_momentum(data, uni, start, end, cash)
            row["dual momentum"] = run_dual(data, start, end, cash)
            if sig and sig.insiders:
                row["insider buys"] = run_signals(data, uni, sig, start, end, cash)
            if sig and sig.congress:
                row["congress buys"] = run_signals(data, uni, sig, start, end, cash, source="congress", days=90)
            row["blend"] = blend([row["dual momentum"], row["momentum"], row.get("congress buys")], cash)
            if "QQQ" in data.charts:
                row["core + dual"] = run_dual(data, start, end, cash, **CORE_DEFAULT)
            row["model"] = run_model(data, uni, sig, start, end, cash)
            if sig and sig.events:
                row["earnings drift"] = run_events(data, uni, sig, start, end, cash)
            row.update(upstream_rows(data, uni, sig, start, end, cash))
        if VIX_SYM in data.charts:
            row["VIX agent"] = run_vix_agent(data, start, end, cash, VIX_RULES[0][1])
        if include_pelosi:
            row["Pelosi copycat"] = run_pelosi(data, filings, start, end, cash)
        row["S&P 500 (SPY)"] = run_hold(data, {"SPY": 1.0}, start, end, cash)
        if "QQQ" in data.charts:
            row["Nasdaq 100 (QQQ)"] = run_hold(data, {"QQQ": 1.0}, start, end, cash)
        row["TSX 60 (XIU.TO)"] = run_hold(data, {"XIU.TO": 1.0}, start, end, cash)
        row.update(mine_rows(data, mine, watch, start, end, cash, uni)[0])
        for k, r in row.items():
            runs.setdefault(k, []).append((start, end, r["return_pct"], row["S&P 500 (SPY)"]["return_pct"]))
    import statistics
    table = {}
    for k, xs in runs.items():
        rets = [x[2] for x in xs]
        table[k] = {"windows": len(xs), "avg_pct": round(statistics.mean(rets), 2),
                    "median_pct": round(statistics.median(rets), 2), "best_pct": max(rets), "worst_pct": min(rets),
                    "positive": sum(1 for r in rets if r > 0),
                    "beat_spy": None if k == "S&P 500 (SPY)" else sum(1 for x in xs if x[2] > x[3]),
                    "runs": [{"start": a, "end": b, "return_pct": r} for a, b, r, _ in xs]}
    return {"horizon_days": spec["horizon_days"], "step_days": spec["step_days"], "table": table}


# ---------------------------------------------------------------- self-checks

CORE = ("growth", "medium", "dividend", "stock bot", "S&P 500 (SPY)", "TSX 60 (XIU.TO)")


def checks(out, data, rolling_spec):
    """Sanity checks on the finished replay. Each is {name, ok, detail}; any failure means
    the numbers should not be trusted (--strict exits non-zero)."""
    import math
    res, asof = [], out["asof"]

    def add(name, ok, detail):
        res.append({"name": name, "ok": bool(ok), "detail": detail})
    last = data.days[-1] if data.days else None
    add("prices reach the as-of date", last is not None and last >= asof, "last SPY bar %s, as of %s" % (last, asof))
    missing = ["%s: %s" % (w, k) for w, row in out["results"].items() for k in CORE if k not in row]
    add("every window has every core strategy", not missing, ", ".join(missing[:6]) or "all present")
    bad = ["%s: %s" % (w, k) for w, row in out["results"].items() for k, r in row.items()
           if isinstance(r, dict) and "value" in r and not (isinstance(r["value"], (int, float))
                                                            and math.isfinite(r["value"]) and r["value"] > 0)]
    add("values are positive and finite", not bad, ", ".join(bad[:6]) or "all good")
    off = []
    for w, row in out["results"].items():
        for k, r in row.items():
            c = isinstance(r, dict) and r.get("curve")
            if c and (c[0][0] != row["start"] or c[-1][0] != asof):
                off.append("%s: %s" % (w, k))
    add("daily curves run from each start to the as-of close", not off, ", ".join(off[:6]) or "all aligned")
    worst = 0.0
    for w, row in out["results"].items():
        spy = row.get("S&P 500 (SPY)")
        p0, p1 = data.close("SPY", row["start"]), data.close("SPY", asof)
        f0, f1 = data.fx(row["start"]), data.fx(asof)
        if spy and p0 and p1:  # US-dollar cash, no conversion fee; dividends net of 15% withholding
            divs = sum(a for d, a in data.charts["SPY"]["dividends"] if row["start"] < d <= asof)
            expect = 100 * (((p1 + divs * (1 - COSTS["us_withholding_pct"] / 100)) / p0) * (f1 / f0) - 1)
            worst = max(worst, abs(spy["return_pct"] - expect))
    add("S&P 500 row matches the raw price change in CAD (dividends counted; overnight gap and slippage allowed)",
        worst <= 2.5, "largest gap %.2f points" % worst)
    cov = [(w, row["coverage"]) for w, row in out["results"].items() if row.get("coverage")]
    if cov:
        low = [(w, c) for w, c in cov if (c["pct"] or 0) < 80]
        add("point-in-time universe has prices for most index members (80%+)", not low,
            ", ".join("%s: %d of %d (%.0f%%)" % (w, c["priced"], c["members"], c["pct"] or 0) for w, c in (low or cov)[:6]))
    if rolling_spec and out.get("rolling"):
        n = max((x["windows"] for x in out["rolling"]["table"].values()), default=0)
        add("rolling windows all ran", n == rolling_spec["count"], "%d of %d" % (n, rolling_spec["count"]))
    return res


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


HISTORY_YEARS = {"2y": 2, "5y": 5, "10y": 10}


def paid_data_key(base="trader"):
    """EODHD_API_KEY from the environment or the git-ignored .env (never printed, never saved)."""
    if os.environ.get("EODHD_API_KEY"):
        return os.environ["EODHD_API_KEY"].strip()
    env, _ = team.candles.load_env(os.path.join(os.path.dirname(os.path.abspath(base)), ".env"), ".env")
    return (env.get("EODHD_API_KEY") or "").strip() or None


def replay(base="trader", asof=None, cash=100.0, skip=(), offline=None, account_type="TFSA", log=print, mc_runs=5000,
           windows=None, holdings=None, rolling_spec=ROLLING, uni=None, history="5y", save_dir=None, signals=None):
    """uni: "auto" (the point-in-time S&P 500 + index funds + the Canadian list), a Universe, or
    None (today's hand-picked watchlists). history: how much price data to load ("5y", "10y").
    save_dir: also write every chart there, for later runs with offline=save_dir."""
    windows = windows or WINDOWS
    if uni == "auto":
        uni = univ.load()
    sig = sigs.Signals.load(signals) if isinstance(signals, str) else signals
    sig = sig if sig else None
    watch = watchlists(base)
    mine = my_holdings(base, holdings)
    labels = {}
    universe = [mk.yahoo_symbol(s) for s in paper.universe(os.path.join(base, "paper", "config.json"))]
    errors = []
    filings = []
    if "pelosi" not in skip:
        this_year = datetime.date.today().year if not asof else _date(asof).year
        filings, errs = pelosi_filings([this_year - 1, this_year], offline=offline,
                                       pdf_dir=os.path.join(base, "state", "ptr-pdfs"))
        errors += errs
    pelosi_syms = sorted({t for _, rows in filings for t in pelosi_signals(rows)[0]})
    syms = set(["SPY", "QQQ", "RSP", "XIU.TO", "USDCAD=X", VIX_SYM, VIX3M_SYM]) | {s for v in watch.values() for s in v} \
        | set(universe) | set(pelosi_syms) | {t for m in mine.values() for t in m["shares"]}
    if uni is not None:
        end = asof or datetime.date.today().isoformat()
        since = (_date(end) - datetime.timedelta(days=365 * HISTORY_YEARS.get(history, 5))).isoformat()
        syms |= set(uni.ever(since, end)) | set(univ.CANADA) | {x for v in univ.ETFS.values() for x in v}
    if sig:  # what the copycat's investors and Nancy Pelosi held, so the upstream agents can be replayed
        syms |= {t for rows in sig.f13.values() for _, _, h in rows for t in h}
        syms |= {r[2] for r in sig.congress if "pelosi" in (r[1] or "").lower() and r[2]}
    syms = sorted(syms)
    charts = {}
    if not offline and len(syms) > 100:
        log("loading %d price histories (%s)..." % (len(syms), history))
    eod_key = paid_data_key(base)
    filled = []
    for i, s in enumerate(syms):
        try:
            charts[s] = mk.get_chart(s, offline=offline, range_=history, save=save_dir)
        except mk.MarketError as e:
            eod_file = os.path.join(offline or save_dir or "", "eod-%s.json" % s.upper())
            if offline and os.path.exists(eod_file):
                with open(eod_file, encoding="utf-8") as fh:
                    charts[s] = json.load(fh)
                filled.append(s)
                continue
            if eod_key and not offline and "." not in s and not s.startswith("^") and "=" not in s:
                try:  # a company Yahoo no longer lists: paid data still has it
                    charts[s] = mk.get_chart_eodhd(s, eod_key)
                    filled.append(s)
                    if save_dir:
                        with open(eod_file, "w", encoding="utf-8") as fh:
                            json.dump(charts[s], fh)
                    continue
                except mk.MarketError as e2:
                    errors.append(str(e2))
            errors.append(str(e))
        if not offline and len(syms) > 100 and i % 100 == 99:
            log("  %d of %d" % (i + 1, len(syms)))
    if "SPY" not in charts:
        raise ReplayError("no SPY prices, so no trading calendar. Data problems: %s"
                          % "; ".join(errors[:3] or ["none reported"]))
    data = Data(charts, {})
    if filled:
        log("paid data filled %d companies Yahoo no longer lists" % len(filled))
    asof = data.trading_day_on_or_before(asof) if asof else latest_friday(data.days)
    candles = {}
    crypto_max = CRYPTO_MAX_DAYS if team.DEFAULTS["interval_min"] < 60 else CRYPTO_LONG_DAYS
    if "crypto" not in skip:
        first = (_date(asof) - datetime.timedelta(days=min(crypto_max, max(n for _, n in windows)) + 4)).isoformat()
        candles, errs = load_candles(dict(team.DEFAULTS), first, asof, offline)
        errors += errs
    results = {}
    for label, n in windows:
        start = data.trading_day_on_or_before((_date(asof) - datetime.timedelta(days=n)).isoformat())
        log("replaying %s (from the close of %s)..." % (label, start))
        row = {"start": start}
        for strat in ("growth", "medium", "dividend"):
            row[strat] = run_account(data, strat, [] if uni else watch[strat], start, asof, cash, account_type, uni=uni)
        row["stock bot"] = run_stockbot(data, universe, start, asof, cash, uni=uni)
        if uni is not None:
            row["coverage"] = coverage(data, uni, start)
            row["momentum"] = run_momentum(data, uni, start, asof, cash)
            row["dual momentum"] = run_dual(data, start, asof, cash)
            if sig and sig.insiders:
                row["insider buys"] = run_signals(data, uni, sig, start, asof, cash)
            if sig and sig.congress:
                row["congress buys"] = run_signals(data, uni, sig, start, asof, cash, source="congress", days=90)
            row["blend"] = blend([row["dual momentum"], row["momentum"], row.get("congress buys")], cash)
            if "QQQ" in data.charts:
                row["core + dual"] = run_dual(data, start, asof, cash, **CORE_DEFAULT)
            row["model"] = run_model(data, uni, sig, start, asof, cash)
            if sig and sig.events:
                row["earnings drift"] = run_events(data, uni, sig, start, asof, cash)
            row.update(upstream_rows(data, uni, sig, start, asof, cash))
        if candles and n <= crypto_max:
            c = run_crypto(candles, data, start, asof, cash, os.path.join(base, "replay", "crypto-" + label.replace(" ", "")))
            row["crypto team"] = c
            if c.get("btc_hold"):
                row["Bitcoin (hold)"] = c["btc_hold"]
        if "pelosi" not in skip:
            row["Pelosi copycat"] = run_pelosi(data, filings, start, asof, cash)
        if VIX_SYM in data.charts:
            row["VIX agent"] = run_vix_agent(data, start, asof, cash, VIX_RULES[0][1])
        row["S&P 500 (SPY)"] = run_hold(data, {"SPY": 1.0}, start, asof, cash)
        if "QQQ" in data.charts:
            row["Nasdaq 100 (QQQ)"] = run_hold(data, {"QQQ": 1.0}, start, asof, cash)
        if uni is not None and "RSP" in data.charts:
            row["S&P 500 equal weight (RSP)"] = run_hold(data, {"RSP": 1.0}, start, asof, cash)
        row["TSX 60 (XIU.TO)"] = run_hold(data, {"XIU.TO": 1.0}, start, asof, cash)
        rows, lab = mine_rows(data, mine, watch, start, asof, cash, uni)
        row.update(rows)
        labels.update(lab)
        row["cash"] = {"value": round(cash, 2), "return_pct": 0.0}
        row["factors"] = factors(data, start, asof, filings)
        if VIX_SYM in data.charts:
            for k, r in row.items():
                if isinstance(r, dict) and len(r.get("curve") or []) > 5:
                    r["vix_regimes"] = vix_regimes(r["curve"], data)
        row["insights"] = insights(row, row["factors"], cash)
        results[label] = row
    longest = results[windows[0][0]]
    curves, short = mc_curves(longest)
    for k, c in curves.items():
        longest[k]["risk"] = risk_stats(c)
    mc = monte_carlo(curves, cash=cash, runs=mc_runs)
    if mc:
        mc["left_out"] = short
    starts = [(label, results[label]["start"]) for label, _ in windows]
    scen = run_scenarios(data, watch, starts, asof, cash, account_type, scenario_list(base), uni)
    ctx = {"universe": universe, "filings": filings, "skip": skip, "offline": offline, "base": base, "uni": uni,
           "signals": sig,
           "errors": errors, "candles": candles}
    scen += agent_scenarios(data, ctx, starts, asof, cash, windows[0][0])
    roll = None
    if rolling_spec:
        log("rolling %d-day windows..." % rolling_spec["horizon_days"])
        roll = rolling(data, watch, universe, filings, mine, asof, cash, account_type, rolling_spec,
                       include_pelosi="pelosi" not in skip, uni=uni, sig=sig)
    out = {"asof": asof, "cash": cash, "account_type": account_type, "costs": COSTS, "results": results,
           "monte_carlo": mc, "scenarios": scen, "rolling": roll, "labels": labels,
           "windows": [w for w, _ in windows], "has_holdings": bool(mine),
           "overall": overall(results), "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "errors": errors, "pelosi_filings": [f for f, _ in filings], "watchlists": watch,
           "universe": None if uni is None else {
               "kind": "point-in-time S&P 500 members + %d index funds + %d Canadian companies" % (
                   sum(len(v) for v in univ.ETFS.values()), len(univ.CANADA)),
               "source": uni.doc.get("licence"), "last_snapshot": uni.doc.get("last_snapshot"),
               "shortlist": SHORTLIST, "history": history},
           "note": "Point-in-time replay: decisions use data up to each day's close, fills at the next open. "
                   + ("Stocks are chosen only from what was in the S&P 500 that day (plus index funds and a "
                      "Canadian list made today); companies Yahoo has no prices for (mostly delisted) cannot be "
                      "chosen, a survivorship bias that remains. " if uni is not None else
                      "Watchlists are today's, which is a hindsight bias. ") + "Not financial advice."}
    out["checks"] = checks(out, data, rolling_spec)
    folder = os.path.join(base, "replay")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    text = render(out)
    with open(os.path.join(folder, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return out, text


ORDER = ["growth", "medium", "dividend", "stock bot", "momentum", "dual momentum", "insider buys", "congress buys",
         "blend", "core + dual", "model", "earnings drift", "copycat", "screener", "pelosi (since 2015)",
         "crypto team", "VIX agent",
         "Pelosi copycat",
         "S&P 500 (SPY)", "Nasdaq 100 (QQQ)", "S&P 500 equal weight (RSP)", "TSX 60 (XIU.TO)", "Bitcoin (hold)", "cash"]
LABELS = {"growth": "Growth reviewer (Questrade)", "medium": "Medium-term reviewer",
          "dividend": "Dividend reviewer (Wealthsimple)", "stock bot": "Stock bot (ATR, paper)",
          "crypto team": "Crypto bot team (paper)", "VIX agent": "VIX agent (Nasdaq 100 or cash)",
          "momentum": "Momentum agent (top 20 of the S&P 500)", "dual momentum": "Dual momentum (index funds)",
          "insider buys": "Insider buying (2+ insiders, S&P 500)", "congress buys": "Congress buying (2+ members, S&P 500)",
          "blend": "Blend: dual momentum + momentum + Congress (thirds)",
          "core + dual": "Core + satellite: 70% Nasdaq 100, 30% dual momentum, rebalanced every 2 weeks",
          "model": "Learned score (top 20, refit every January)",
          "earnings drift": "Earnings drift (8-K news: jumps on earnings, held ~60 days)",
          "copycat": "Copycat (upstream): each famous investor's top 3 from their 13Fs",
          "screener": "Screener (upstream): its example rules on filed results, top 10",
          "pelosi (since 2015)": "Pelosi (upstream): her buys of the last year, mirrored, since 2015"}
STRATS = [k for k in ORDER if k not in BENCH]


def _p(x):
    return "n/a" if x is None else "%+.1f%%" % x


def render(out):
    wins = out.get("windows") or list(out["results"])
    labels = out.get("labels") or {}

    def lab(k):
        return labels.get(k) or LABELS.get(k, k)
    mine = sorted(k for w in wins for k in out["results"][w] if k.startswith("mine:"))
    mine = list(dict.fromkeys(mine))
    keys = STRATS + mine + [k for k in ORDER if k in BENCH]
    L = ["# $%g replay, as of the close on %s" % (out["cash"], out["asof"]), "",
         "Each cell: value at the close on %s (return). Starts: %s." % (
             out["asof"], ", ".join("%s = %s" % (w, out["results"][w]["start"]) for w in wins)), "",
         "| strategy | " + " | ".join(wins) + " |", "| --- |" + " ---: |" * len(wins)]
    if out.get("universe"):
        u = out["universe"]
        cov = ["%s: %d of %d priced" % (w, out["results"][w]["coverage"]["priced"], out["results"][w]["coverage"]["members"])
               for w in wins if out["results"][w].get("coverage")]
        L[2:2] = ["**Universe:** %s (%s history). Each review the scanner ranks them all and the reviewer scores the "
                  "best %s. Index members at each start: %s." % (
                      u["kind"], u["history"], "/".join(str(v) for v in u["shortlist"].values()), "; ".join(cov)), ""]
    for k in keys:
        cells = []
        for w in wins:
            r = out["results"][w].get(k)
            cells.append("$%.2f (%+.1f%%)" % (r["value"], r["return_pct"]) if r else "n/a")
        if any(c != "n/a" for c in cells):
            if k == "Pelosi copycat":
                L.append("| **%s** | " % "Pelosi copycat (separate)" + " | ".join(cells) + " |")
            else:
                L.append("| %s | " % (("**%s**" % lab(k)) if k.startswith("mine:") else lab(k)) + " | ".join(cells) + " |")
    L += ["", "## Details", ""]
    for w in wins:
        r = out["results"][w]
        L.append("**%s** (from %s)" % (w, r["start"]))
        for k in STRATS + mine:
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
            if x.get("switches") is not None:
                bits.append("trades %s; in the market %s%% of days, %d switches"
                            % (x.get("fund", "SPY"), x["risk_on_days_pct"], x["switches"]))
            L.append("- %s: %s" % (lab(k), "; ".join(bits)))
        L.append("")
    L += ["## What is going well, what is not", ""]
    for k, t in sorted(out.get("overall", {}).items(), key=lambda kv: -kv[1]["beat_spy"]):
        L.append("- **%s** beat the S&P 500 in %d of %d windows" % (lab(k), t["beat_spy"], t["windows"]))
    L.append("")
    for w in wins:
        r = out["results"][w]
        f = r.get("factors") or {}
        L.append("### %s: the backdrop" % w)
        L.append("S&P 500 %s, TSX 60 %s, USD/CAD %s, S&P 500 %s its 200-day average, Pelosi filings posted: %d%s" % (
            _p(f.get("spy_pct")), _p(f.get("tsx_pct")), _p(f.get("usdcad_pct")),
            "above" if f.get("spy_above_200d") else "below", len(f.get("pelosi_filings") or []),
            (", VIX %.1f -> %.1f (high %.1f, now %s)" % (f["vix_start"], f["vix_end"], f["vix_max"], f["vix_regime"]))
            if f.get("vix_end") else ""))
        for k, n in (r.get("insights") or {}).items():
            L.append("- **%s**: + %s / - %s" % (lab(k), "; ".join(n["going_well"]) or "nothing stood out",
                                                 "; ".join(n["not_going_well"]) or "nothing stood out"))
        L.append("")
    if out.get("scenarios"):
        L += ["## Scenarios: same strategy, different settings", "",
              "| strategy | scenario | changed inputs | " + " | ".join(wins) + " | Sharpe (%s) | worst drop |" % wins[0],
              "| --- | --- | --- |" + " ---: |" * (len(wins) + 2)]
        for sc in out["scenarios"]:
            rk = sc.get("risk") or {}
            L.append("| %s | %s | %s | %s | %s | %s |" % (
                sc["strategy"], sc["name"], ", ".join("%s=%s" % kv for kv in sc["inputs"].items()) or "defaults",
                " | ".join("%+.1f%%" % sc["results"][w]["return_pct"] if sc["results"].get(w) else "n/a" for w in wins),
                rk.get("sharpe", "–"), _p(rk.get("max_dd_pct"))))
        L.append("")
    roll = out.get("rolling")
    if roll and roll.get("table"):
        t = roll["table"]
        L += ["## Rolling %d-day windows: does it keep working?" % roll["horizon_days"], "",
              "%d windows of %d days, a new one every %d days. Beating the S&P 500 in most of them is "
              "evidence; one good window is luck." % (max(x["windows"] for x in t.values()), roll["horizon_days"],
                                                       roll["step_days"]), "",
              "| strategy | beat S&P 500 | made money | average | median | best | worst |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for k in sorted(t, key=lambda k: (-(t[k]["beat_spy"] or 0), -t[k]["avg_pct"])):
            x = t[k]
            L.append("| %s | %s | %d of %d | %s | %s | %s | %s |" % (
                lab(k), "–" if x["beat_spy"] is None else "%d of %d" % (x["beat_spy"], x["windows"]),
                x["positive"], x["windows"], _p(x["avg_pct"]), _p(x["median_pct"]), _p(x["best_pct"]),
                _p(x["worst_pct"])))
        L.append("")
    six = out["results"][wins[0]]
    if any(isinstance(r, dict) and r.get("vix_regimes") for r in six.values()):
        names = [n for _, n in vix.REGIMES]
        L += ["## By VIX regime (%s)" % wins[0], "",
              "Average daily return on days after the VIX closed calm (<15), normal (15-20), nervous (20-30) "
              "or in fear (30+), and how each strategy moved with the VIX (-1 = falls when fear rises).", "",
              "| strategy | " + " | ".join(names) + " | corr. with VIX |", "| --- |" + " ---: |" * (len(names) + 1)]
        for k in keys:
            vr = (six.get(k) or {}).get("vix_regimes")
            if vr:
                L.append("| %s | %s | %s |" % (lab(k), " | ".join(
                    ("%+.2f%% (%dd)" % (vr[n]["avg_daily_pct"], vr[n]["days"])) if vr[n]["avg_daily_pct"] is not None
                    else "–" for n in names), vr.get("corr_with_vix", "–")))
        L.append("")
    mc = out.get("monte_carlo")
    if mc:
        L += ["## Monte Carlo: the next %d trading days" % mc["horizon_days"], "",
              "%d runs, resampling %d-day blocks of each strategy's own daily returns from the last %d days "
              "(the same days for every strategy). $%g today becomes:" % (
                  mc["runs"], mc["block_days"], mc["sample_days"], out["cash"]), "",
              "| strategy | bad case (5%) | median | good case (95%) | P(profit) | P(beat S&P 500) | typical max drop | Sharpe (past) |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for k in keys:
            m = mc["strategies"].get(k)
            if not m:
                continue
            rk = (six.get(k) or {}).get("risk") or {}
            L.append("| %s | $%.2f | $%.2f | $%.2f | %.0f%% | %s | %.1f%% | %s |" % (
                lab(k), m["p5"], m["median"], m["p95"], m["prob_profit_pct"],
                "–" if m["prob_beat_bench_pct"] is None else "%.0f%%" % m["prob_beat_bench_pct"],
                m["median_max_dd_pct"], rk.get("sharpe", "–")))
        L += ["", "A bootstrap of one past period: it shows the spread that period implies, not a forecast.%s" % (
            (" Left out (too little history): " + ", ".join(mc["left_out"])) if mc.get("left_out") else ""), ""]
    if out.get("checks"):
        L += ["## Self-checks", ""]
        L += ["- %s %s: %s" % ("PASS" if c["ok"] else "FAIL", c["name"], c["detail"]) for c in out["checks"]]
        L.append("")
    if out["errors"]:
        L.append("## Data problems")
        L += ["- " + e for e in out["errors"][:15]]
        L.append("")
    L.append("_%s_" % out["note"])
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- forward paper record

# ---------------------------------------------------------------- long history (2000-2017)

LONG_PROXIES = {"IEF": "VFITX", "SHY": "VFISX"}  # Vanguard Treasury funds (1991) before the ETFs (2002)
FRED_USDCAD = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXCAUS"  # US dollar in CAD, daily since 1971
LONG_STRATS = [
    ("70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen)", {"core": "QQQ", "core_weight": 0.7, "every": 14}),
    ("70/30, rebalanced monthly (previous plan)", {"core": "QQQ", "core_weight": 0.7}),
    ("70/30, 4 slices re-chosen on different weeks", {"core": "QQQ", "core_weight": 0.7, "tranches": 4}),
    ("Dual momentum alone (single strongest fund)", {}),
]
LONG_BENCH = [("Nasdaq 100 (QQQ)", "QQQ"), ("S&P 500 (SPY)", "SPY")]


def splice(chart, proxy, name=None):
    """`chart` extended back in time with `proxy`'s moves before its first day: prices and
    dividends scaled so the two meet on that day (total return carries over)."""
    if not chart or not proxy or not chart["bars"]:
        return chart
    first = chart["bars"][0]["d"]
    meet = [b for b in proxy["bars"] if b["d"] <= first]
    if not meet or not meet[-1]["c"]:
        return chart
    k = chart["bars"][0]["c"] / meet[-1]["c"]
    old = [dict(b, o=b["o"] * k, h=b["h"] * k, l=b["l"] * k, c=b["c"] * k) for b in proxy["bars"] if b["d"] < first]
    divs = [(d, a * k) for d, a in proxy["dividends"] if d < first]
    return dict(chart, bars=old + chart["bars"], dividends=divs + list(chart["dividends"]),
                spliced={"proxy": name or proxy.get("symbol"), "until": first})


def daily(chart):
    """True when the bars are daily (the typical gap is under 5 days), not weekly or monthly."""
    ds = [_date(b["d"]) for b in chart["bars"]]
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    return bool(gaps) and gaps[len(gaps) // 2] < 5


def fred_chart(text, symbol="USDCAD=X"):
    """FRED's CSV (DATE,VALUE, '.' for holidays) as a chart of daily bars."""
    bars = []
    for line in text.splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            x = float(v)
        except ValueError:
            continue
        bars.append({"d": d.strip(), "o": x, "h": x, "l": x, "c": x, "v": 0})
    return {"symbol": symbol, "name": "FRED DEXCAUS", "currency": "CAD", "price": bars[-1]["c"] if bars else None,
            "time": bars[-1]["d"] if bars else None, "bars": bars, "dividends": []}


def long_charts(offline=None, save=None, log=print):
    """Every fund the long run needs, as far back as Yahoo goes, with proxies spliced in."""
    syms = {"SPY", "QQQ", "IEF", "SHY", "USDCAD=X"} | set(LONG_PROXIES.values()) \
        | {x for g in DUAL_POOL for x in univ.ETFS[g] if not x.endswith(".TO")}
    charts, notes = {}, {}
    for sym in sorted(syms):
        try:
            charts[sym] = mk.get_chart(sym, offline=offline, range_="max", save=save)
        except mk.MarketError as e:
            log("long: %s" % e)
    for etf, fund in LONG_PROXIES.items():
        if etf in charts and fund in charts:
            charts[etf] = splice(charts[etf], charts.pop(fund), fund)
            notes[etf] = "%s before %s" % (fund, charts[etf]["spliced"]["until"])
    path = os.path.join(offline or "", "fred-DEXCAUS.csv")
    try:
        if offline:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = mk.fetch(FRED_USDCAD)
            if save:
                with open(os.path.join(save, "fred-DEXCAUS.csv"), "w", encoding="utf-8") as fh:
                    fh.write(text)
        fred = fred_chart(text)
        charts["USDCAD=X"] = splice(charts.get("USDCAD=X"), fred, "FRED DEXCAUS") if "USDCAD=X" in charts else fred
        notes["USDCAD=X"] = "FRED daily rate before %s" % ((charts["USDCAD=X"].get("spliced") or {}).get("until") or "-")
    except (OSError, mk.MarketError) as e:
        notes["USDCAD=X"] = "no rate before Yahoo's (%s): a flat 1.35 is used, which hits every strategy alike" % e
    return charts, notes


def long_run(data, first="2000-01-03", until="2017-10-18", horizon=365, step=91, cash=100.0,
             period_ends=("2002-10-18", "2004-10-15", "2006-10-20", "2008-10-17", "2010-10-15", "2012-10-19",
                          "2014-10-17", "2016-10-14"), notes=None):
    """The chosen plan and its rivals before anything was chosen: rolling `horizon`-day windows
    from `first`, every `step` days, ending by `until` (where the training periods begin), and
    24-month periods ending each `period_ends`. Point in time like every replay."""
    def runs(start, end):
        out = {}
        for name, opts in LONG_STRATS:
            out[name] = run_dual(data, start, end, cash, **opts)
        for name, sym in LONG_BENCH:
            if sym in data.charts:
                out[name] = run_hold(data, {sym: 1.0}, start, end, cash)
        return out
    table, d0 = {}, _date(first)
    while (d0 + datetime.timedelta(days=horizon)).isoformat() <= until:
        start = data.trading_day_on_or_before(d0.isoformat())
        end = data.trading_day_on_or_before((d0 + datetime.timedelta(days=horizon)).isoformat())
        for name, r in runs(start, end).items():
            table.setdefault(name, {"runs": []})["runs"].append(
                {"start": start, "end": end, "return_pct": r["return_pct"], "trades": r["trades"],
                 "max_dd_pct": (risk_stats(r["curve"]) or {}).get("max_dd_pct")})
        d0 += datetime.timedelta(days=step)
    periods = []
    for e in period_ends:
        end = data.trading_day_on_or_before(e)
        start = data.trading_day_on_or_before((_date(end) - datetime.timedelta(days=730)).isoformat())
        periods.append({"start": start, "end": end, "results": {
            name: {"return_pct": r["return_pct"], "max_dd_pct": (risk_stats(r["curve"]) or {}).get("max_dd_pct"),
                   "trades": r["trades"], "fees": r["fees"],
                   "switches": [p for i, p in enumerate(r.get("picks") or []) if not i or p[1] != r["picks"][i - 1][1]]}
            for name, r in runs(start, end).items()}})
    count = len(next(iter(table.values()))["runs"]) if table else 0
    return {"asof": until, "first": first, "rolling": {"table": table, "horizon_days": horizon, "step_days": step,
                                                       "count": count},
            "periods": periods, "names": [n for n, _ in LONG_STRATS] + [n for n, _ in LONG_BENCH], "notes": notes or {}}


def render_long(out):
    spy = "S&P 500 (SPY)"
    L = ["# Long history: %s to %s, before anything was chosen" % (out["first"], out["asof"]), "",
         "Every setting here was chosen on 2017-2026 data, so these years are a fresh test. The 2000-2002 "
         "dot-com crash and the 2008 crisis are included. Fund strategies only (the S&P 500 stock lists and "
         "company filings do not go back this far). Point in time: decisions at each close, fills at the next "
         "open. The dual momentum list is today's funds (each counts once it has a year of history), a mild "
         "hindsight.", ""]
    if out.get("notes"):
        L += ["Data stitched in: " + "; ".join("%s: %s" % kv for kv in sorted(out["notes"].items())) + ".", ""]
    L += ["## 24-month periods (gap to the S&P 500 in brackets, worst drop after the slash)", "",
          "| strategy | " + " | ".join(p["end"] for p in out["periods"]) + " | beat S&P 500 | average gap |",
          "| --- |" + " ---: |" * (len(out["periods"]) + 2)]
    for name in out["names"]:
        cells, gaps = [], []
        for p in out["periods"]:
            r, b = p["results"].get(name), p["results"].get(spy)
            if not r:
                cells.append("n/a")
                continue
            gap = None if name == spy or not b else r["return_pct"] - b["return_pct"]
            if gap is not None:
                gaps.append(gap)
            cells.append("%+.0f%%%s / %s" % (r["return_pct"], "" if gap is None else " (%+.0f)" % gap,
                                             "n/a" if r["max_dd_pct"] is None else "%.0f%%" % r["max_dd_pct"]))
        L.append("| %s | %s | %s | %s |" % (name, " | ".join(cells), "-" if name == spy else "%d of %d" % (
            sum(g > 0 for g in gaps), len(gaps)), "-" if not gaps else "%+.1f pts" % (sum(gaps) / len(gaps))))
    t = out["rolling"]["table"]
    L += ["", "## %d rolling %d-day windows, a new one every %d days" % (
        out["rolling"]["count"], out["rolling"]["horizon_days"], out["rolling"]["step_days"]), "",
          "| strategy | average return | average gap to the S&P 500 | beat it | average worst drop | worst window |",
          "| --- | ---: | ---: | ---: | ---: | ---: |"]
    base = [x["return_pct"] for x in t.get(spy, {}).get("runs", [])]
    for name in out["names"]:
        rs = t.get(name, {}).get("runs", [])
        if not rs:
            continue
        ret = [x["return_pct"] for x in rs]
        gaps = [a - b for a, b in zip(ret, base)] if len(base) == len(ret) and name != spy else []
        dds = [x["max_dd_pct"] for x in rs if x["max_dd_pct"] is not None]
        L.append("| %s | %+.1f%% | %s | %s | %s | %+.1f%% |" % (
            name, sum(ret) / len(ret), "%+.1f pts" % (sum(gaps) / len(gaps)) if gaps else "-",
            "%d of %d" % (sum(g > 0 for g in gaps), len(gaps)) if gaps else "-",
            "%.1f%%" % (sum(dds) / len(dds)) if dds else "n/a", min(ret)))
    L += ["", "_Simulated; past results do not promise future ones. Not financial advice._"]
    return "\n".join(L) + "\n"


FORWARD_PLAN = os.path.join(HERE, "forward_plan.json")


def forward(plan, record=None, offline=None, today=None, log=print, signals=None):
    """The live paper record: every strategy in the frozen plan, run from the plan's start date
    to the latest close with only what was known each day. Values for days already in `record`
    are kept as they were (append-only): only new days are added. Kind "pelosi" needs
    `signals` (a Signals with the Congress filings)."""
    start = plan["start"]
    syms = {"SPY", "QQQ", "IEF", "SHY", "USDCAD=X"}
    for st in plan["strategies"].values():
        if st["kind"] == "hold":
            syms |= set(st["weights"])
        elif st["kind"] == "pelosi":
            syms |= {r[2] for r in (signals.congress if signals else []) if "pelosi" in (r[1] or "").lower() and r[2]}
        elif st["kind"] == "dual":
            pool = DUAL_POOLS[dict(DUAL_DEFAULT, **st.get("opts", {}))["pool"]]
            syms |= {x for g in pool for x in univ.ETFS[g] if not x.endswith(".TO")}
    charts = {}
    for s in sorted(syms):
        try:
            charts[s] = mk.get_chart(s, offline=offline, range_="2y")
        except mk.MarketError as e:
            log("forward: %s" % e)
    data = Data(charts, {})
    last = data.trading_day_on_or_before(today or data.days[-1])
    first = data.trading_day_on_or_before(start)
    rec = record or {"start": start, "plan": plan, "days": {}}
    if rec.get("start") != start:  # a new plan starts a new record; the old one is kept exactly as it was
        old = dict(rec)
        rec = {"start": start, "plan": plan, "days": {}, "earlier": old.pop("earlier", []) + [old]}
    out = {}
    for name, st in plan["strategies"].items():
        if st["kind"] == "hold":
            r = run_hold(data, st["weights"], first, last, plan.get("cash", 100.0))
        elif st["kind"] == "pelosi":
            r = run_pelosi_signals(data, signals, first, last, plan.get("cash", 100.0), **st.get("opts", {}))
        else:
            r = run_dual(data, first, last, plan.get("cash", 100.0), **st.get("opts", {}))
        out[name] = {d: v for d, v in r["curve"]}
        out[name]["_holdings"] = r.get("holdings", [])
    days = sorted({d for v in out.values() for d in v if not d.startswith("_")})
    for d in days:
        if d in rec["days"]:
            continue  # never rewrite a day that is already on the record
        rec["days"][d] = {name: v.get(d) for name, v in out.items()}
    rec["holdings"] = {name: v["_holdings"] for name, v in out.items()}

    def today_weights(st):
        if st["kind"] == "dual":
            return dual_weights(data, last, **st.get("opts", {}))
        if st["kind"] == "pelosi":
            return pelosi_weights(data, signals, last, **dict(PELOSI_DEFAULT, **st.get("opts", {})))
        return st["weights"]
    rec["targets"] = {name: {k: round(x, 4) for k, x in today_weights(st).items()}
                      for name, st in plan["strategies"].items()}
    rec["updated"] = last
    return rec


def render_forward(rec):
    days = sorted(rec["days"])
    if not days:
        return "No forward days yet."
    first, last = rec["days"][days[0]], rec["days"][days[-1]]
    L = ["Live paper record since %s (%d trading days), $%g each:" % (rec["start"], len(days), rec["plan"].get("cash", 100))]
    for name in rec["plan"]["strategies"]:
        v = last.get(name)
        if v is not None:
            L.append("  %-40s $%.2f (%+.1f%%)  holds %s" % (name, v, v - rec["plan"].get("cash", 100),
                                                            ", ".join(rec.get("holdings", {}).get(name, [])[:5])))
    return "\n".join(L)


def parse_rolling(text):
    """'365,91,28' -> {"horizon_days": 365, "step_days": 91, "count": 28} (None -> the default)."""
    if not text:
        return ROLLING
    h, st, n = [int(x) for x in text.split(",")]
    return {"horizon_days": h, "step_days": st, "count": n}


def parse_windows(text):
    """'12m,6m,1w' -> [('12 months', 365), ('6 months', 182), ('1 week', 7)]."""
    if not text:
        return None
    out = []
    for part in text.split(","):
        part = part.strip().lower()
        n, unit = int(part[:-1]), part[-1]
        days = {"d": 1, "w": 7, "m": 30.4, "y": 365}[unit] * n
        name = {"d": "day", "w": "week", "m": "month", "y": "year"}[unit]
        out.append(("%d %s%s" % (n, name, "" if n == 1 else "s"), int(round(min(days, 365 * n if unit == "y" else days)))))
    return sorted(out, key=lambda w: -w[1])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Point-in-time replay of every strategy with $100.")
    ap.add_argument("--dir", default="trader")
    ap.add_argument("--asof", help="YYYY-MM-DD (default: the latest Friday close)")
    ap.add_argument("--cash", type=float, default=100.0)
    ap.add_argument("--account-type", default="TFSA")
    ap.add_argument("--skip", nargs="*", default=[], choices=["crypto", "pelosi"])
    ap.add_argument("--holdings", action="append", metavar="ACCOUNT=FILE",
                    help="replay your own holdings from a broker CSV (also read from trader/accounts/*.json)")
    ap.add_argument("--windows", help="e.g. 12m,6m,3m,1m,2w,1w (default)")
    ap.add_argument("--no-rolling", action="store_true", help="skip the rolling-window test")
    ap.add_argument("--rolling-spec", metavar="DAYS,STEP,COUNT",
                    help="rolling windows: length in days, days between starts, how many (default 91,30,12)")
    ap.add_argument("--universe", choices=["auto", "watchlists"], default="auto",
                    help="auto: choose from the S&P 500 as it was each day + index funds (default); "
                         "watchlists: today's hand-picked lists (hindsight)")
    ap.add_argument("--history", choices=sorted(HISTORY_YEARS), default="5y", help="price history to load")
    ap.add_argument("--save-data", metavar="DIR", help="also save every chart to DIR (reuse with --offline DIR)")
    ap.add_argument("--signals", metavar="DIR", help="congress.json.gz / insiders.json.gz from signals.py")
    ap.add_argument("--forward", metavar="RECORD", help="update the live paper record in RECORD (JSON) from "
                    "forward_plan.json, then stop")
    ap.add_argument("--long", metavar="OUTDIR", help="the fund strategies from 2000 to 2017 (before anything "
                    "was chosen), with older funds stitched in; writes OUTDIR/long.json and long.md, then stop")
    ap.add_argument("--picks", metavar="CODE", help="write today's picks of one upstream version (C1-C6 copycat, "
                    "S1-S4 screener, P1-P3 Pelosi; needs --signals) to DIR/targets.json for trader-budget, then stop")
    ap.add_argument("--strict", action="store_true", help="exit 3 if any self-check fails")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.picks:
        try:
            fam = upstream_version(a.picks)[0]
            sig = sigs.Signals.load(a.signals or "signals")
            uni = univ.load()
            today = a.asof or datetime.date.today().isoformat()
            syms = {"SPY"} | (set(uni.members_on(today)) if fam == "screener" else
                              {t for rows in sig.f13.values() for _, _, h in rows[-2:] for t in h} if fam == "copycat"
                              else {r[2] for r in sig.congress if "pelosi" in (r[1] or "").lower() and r[2]})
            charts = {}
            for s in sorted(syms):
                try:
                    charts[s] = mk.get_chart(s, offline=a.offline, range_="2y")
                except mk.MarketError:
                    continue
            data = Data(charts, {})
            doc = upstream_picks(a.picks, data, uni, sig, data.trading_day_on_or_before(today))
        except (ReplayError, mk.MarketError) as e:
            print("replay: %s" % e, file=sys.stderr)
            return 2
        acc.write_json(os.path.join(a.dir, "targets.json"), doc)
        print("%s -> %s" % (doc["source"], os.path.join(a.dir, "targets.json")))
        for row in doc["weights"]:
            print("  %-8s %6.2f%%" % (row["ticker"], row["weight"]))
        print("Next: /trader-budget sizes it, /trader-risk checks it, /trader-broker asks you per order. "
              "Not financial advice.")
        return 0
    if a.long:
        charts, notes = long_charts(a.offline, a.save_data, log=lambda m: print(m, file=sys.stderr))
        if "SPY" not in charts:
            print("replay: no SPY prices", file=sys.stderr)
            return 2
        if not daily(charts["SPY"]):
            print("replay: SPY prices are not daily bars, so the run would be wrong", file=sys.stderr)
            return 2
        out = long_run(Data(charts, {}), notes=notes)
        os.makedirs(a.long, exist_ok=True)
        with open(os.path.join(a.long, "long.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        text = render_long(out)
        with open(os.path.join(a.long, "long.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        print(text)
        return 0
    if a.forward:
        with open(FORWARD_PLAN, encoding="utf-8") as fh:
            plan = json.load(fh)
        rec = None
        if os.path.exists(a.forward):
            with open(a.forward, encoding="utf-8") as fh:
                rec = json.load(fh)
        sig = sigs.Signals.load(a.signals) if a.signals else None
        if any(st["kind"] == "pelosi" for st in plan["strategies"].values()) and not (sig and sig.congress):
            print("replay: the plan copies Pelosi's filings: pass --signals DIR with congress.json.gz", file=sys.stderr)
            return 2
        rec = forward(plan, rec, offline=a.offline, today=a.asof, log=lambda m: print(m, file=sys.stderr),
                      signals=sig)
        os.makedirs(os.path.dirname(os.path.abspath(a.forward)), exist_ok=True)
        with open(a.forward, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
        print(render_forward(rec))
        return 0
    try:
        out, text = replay(a.dir, a.asof, a.cash, a.skip, a.offline, a.account_type,
                           log=lambda m: print(m, file=sys.stderr), windows=parse_windows(a.windows),
                           holdings=a.holdings, rolling_spec=None if a.no_rolling else parse_rolling(a.rolling_spec),
                           uni="auto" if a.universe == "auto" else None, history=a.history, save_dir=a.save_data,
                           signals=a.signals)
    except (ReplayError, mk.MarketError) as e:
        print("replay: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1) if a.json else text)
    if a.strict and not all(c["ok"] for c in out.get("checks", [])):
        print("replay: a self-check failed (see Self-checks)", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
