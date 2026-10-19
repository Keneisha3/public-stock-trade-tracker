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

    def __init__(self, data, cash=100.0, account_type="TFSA", split=None, start=None):
        self.data, self.pos = data, {}
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
            fee, rate = COSTS["fx_fee_pct"] / 100.0, self.data.fx(day)
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


def run_targets(data, start, asof, cash, choose, every=28, split=None):
    """Equal weight in whatever choose(day) returns (a name listed twice gets two shares),
    rebalanced every `every` days. choose sees only data up to that day's close; trades
    fill at the next open."""
    pf, pending = Portfolio(data, cash, split=split or {"USD": 1.0}, start=start), []
    days = [d for d in data.days if start <= d <= asof]
    reviews = _review_days(days, start, asof, every)
    picks_log = []
    for d in days:
        pf.pay_dividends(d)
        pending = pf.fill(pending, d)
        pf.mark(d)
        if d not in reviews:
            continue
        picked = [t for t in choose(d) if data.close(t, d)]
        picks_log.append([d, list(picked)])
        total = pf.value(d) * 0.995
        share = {t: total * picked.count(t) / len(picked) for t in dict.fromkeys(picked)} if picked else {}
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
    out["picks"] = picks_log[-6:]
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


DUAL_DEFAULT = {"k": 3, "months": 12, "safe": "IEF", "cash_like": "SHY"}
DUAL_POOL = ("us_broad", "us_sector", "us_factor", "world", "commodities")


def run_dual(data, start, asof, cash, **opts):
    """Dual momentum on index funds: each month hold the k funds with the best 12-month return
    (relative momentum), but only those beating short bonds (SHY, absolute momentum); the
    rest goes to IEF. A fund counts only once it has traded long enough to have the history."""
    o = dict(DUAL_DEFAULT, **opts)
    pool = sorted({x for g in DUAL_POOL for x in univ.ETFS[g] if not x.endswith(".TO")})

    def choose(d):
        hurdle = (data.quick(o["cash_like"], d, 21 * o["months"]) or {}).get("ret", 0.0)
        rows = [(q["ret"], f) for f in pool for q in [data.quick(f, d, 21 * o["months"])] if q]
        top = [f for r, f in sorted(rows, reverse=True)[:o["k"]] if r > hurdle]
        return top + [o["safe"]] * (o["k"] - len(top)) if o["safe"] in data.charts else top
    return run_targets(data, start, asof, cash, choose, 28)


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


def run_stockbot(data, universe, start, asof, cash, overrides=None, uni=None):
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
DUAL_VARIANTS = [
    ("Dual momentum: best 3 funds (default)", {}),
    ("Dual momentum: best 1 fund", {"k": 1}),
    ("Dual momentum: best 5 funds", {"k": 5}),
    ("Dual momentum: 6-month lookback", {"months": 6}),
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

def rolling(data, watch, universe, filings, mine, asof, cash, account_type, spec=ROLLING, include_pelosi=True, uni=None):
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
        if spy and p0 and p1:
            expect = 100 * ((p1 / p0) * (f1 / f0) - 1)  # US-dollar cash: no conversion fee
            worst = max(worst, abs(spy["return_pct"] - expect))
    years = max(1.0, max((_gap(row["start"], asof) for row in out["results"].values()), default=365) / 365.0)
    allow = 1.0 + 1.5 * years  # dividends (about 1.3% a year) and the overnight gap at the first fill
    add("S&P 500 row matches the raw price change in CAD (overnight gap, slippage and dividends allowed)",
        worst <= allow, "largest gap %.2f points (allowed %.1f)" % (worst, allow))
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


def replay(base="trader", asof=None, cash=100.0, skip=(), offline=None, account_type="TFSA", log=print, mc_runs=5000,
           windows=None, holdings=None, rolling_spec=ROLLING, uni=None, history="5y", save_dir=None):
    """uni: "auto" (the point-in-time S&P 500 + index funds + the Canadian list), a Universe, or
    None (today's hand-picked watchlists). history: how much price data to load ("5y", "10y").
    save_dir: also write every chart there, for later runs with offline=save_dir."""
    windows = windows or WINDOWS
    if uni == "auto":
        uni = univ.load()
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
    syms = sorted(syms)
    charts = {}
    if not offline and len(syms) > 100:
        log("loading %d price histories (%s)..." % (len(syms), history))
    for i, s in enumerate(syms):
        try:
            charts[s] = mk.get_chart(s, offline=offline, range_=history, save=save_dir)
        except mk.MarketError as e:
            errors.append(str(e))
        if not offline and len(syms) > 100 and i % 100 == 99:
            log("  %d of %d" % (i + 1, len(syms)))
    if "SPY" not in charts:
        raise ReplayError("no SPY prices, so no trading calendar. Data problems: %s"
                          % "; ".join(errors[:3] or ["none reported"]))
    data = Data(charts, {})
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
           "errors": errors, "candles": candles}
    scen += agent_scenarios(data, ctx, starts, asof, cash, windows[0][0])
    roll = None
    if rolling_spec:
        log("rolling %d-day windows..." % rolling_spec["horizon_days"])
        roll = rolling(data, watch, universe, filings, mine, asof, cash, account_type, rolling_spec,
                       include_pelosi="pelosi" not in skip, uni=uni)
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


ORDER = ["growth", "medium", "dividend", "stock bot", "momentum", "dual momentum", "crypto team", "VIX agent",
         "Pelosi copycat",
         "S&P 500 (SPY)", "Nasdaq 100 (QQQ)", "S&P 500 equal weight (RSP)", "TSX 60 (XIU.TO)", "Bitcoin (hold)", "cash"]
LABELS = {"growth": "Growth reviewer (Questrade)", "medium": "Medium-term reviewer",
          "dividend": "Dividend reviewer (Wealthsimple)", "stock bot": "Stock bot (ATR, paper)",
          "crypto team": "Crypto bot team (paper)", "VIX agent": "VIX agent (Nasdaq 100 or cash)",
          "momentum": "Momentum agent (top 20 of the S&P 500)", "dual momentum": "Dual momentum (index funds)"}
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
    ap.add_argument("--universe", choices=["auto", "watchlists"], default="auto",
                    help="auto: choose from the S&P 500 as it was each day + index funds (default); "
                         "watchlists: today's hand-picked lists (hindsight)")
    ap.add_argument("--history", choices=sorted(HISTORY_YEARS), default="5y", help="price history to load")
    ap.add_argument("--save-data", metavar="DIR", help="also save every chart to DIR (reuse with --offline DIR)")
    ap.add_argument("--strict", action="store_true", help="exit 3 if any self-check fails")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        out, text = replay(a.dir, a.asof, a.cash, a.skip, a.offline, a.account_type,
                           log=lambda m: print(m, file=sys.stderr), windows=parse_windows(a.windows),
                           holdings=a.holdings, rolling_spec=None if a.no_rolling else ROLLING,
                           uni="auto" if a.universe == "auto" else None, history=a.history, save_dir=a.save_data)
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
