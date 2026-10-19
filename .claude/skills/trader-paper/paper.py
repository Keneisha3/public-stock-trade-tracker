#!/usr/bin/env python3
"""Paper-trading bot for trader-paper. Standard library only. Paper money only.

The strategy is the one Keneisha's ATR-Based-News-Triggered-Stock-System
validated (2021-2026, 56 US large caps): a close-to-close move of at least
1.5 ATR is a "breach"; in a bull regime (an equal-weight index of the
universe above its 50-day average) up-breaches tend to continue for a few
days, in a bear regime they fade. So:

  entry   an up-breach in a bull regime -> buy at the NEXT day's open
  size    risk 1% of equity between entry and the stop, at most 15% of equity
          per name, at most 8 names at once
  stop    entry - 2 ATR (a gap below the stop fills at the open)
  exit    after 3 trading days at the close, or at the stop
  costs   5 bps a side (commission + slippage), charged on every fill
  idle    cash no trade is using sits in QQQ (the Nasdaq 100; bought and sold
          at the open as trades need it), so the bot is the index plus its
          trades instead of mostly cash. "idle": null turns it off

    python3 paper.py backtest                   # the rule over the last 5 years vs buy-and-hold
    python3 paper.py run                        # live paper: catch up to the latest close, trade, save
    python3 paper.py status                     # equity, open positions, trades, readiness check
    python3 paper.py reset --cash 10000

`run` is meant to run once a day after the close (the daily briefing and the
dashboard call it). It never touches a broker. The ledger lives in
trader/paper/ledger.json. Results are simulated: real fills, taxes and your
own discipline will differ.
"""

import argparse
import datetime
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
import market as mk  # noqa: E402

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "CRM", "ORCL", "ADBE",
            "AVGO", "QCOM", "MU", "JPM", "BAC", "GS", "V", "MA", "AXP", "COST", "WMT", "HD", "LLY", "UNH",
            "XOM", "CAT", "GE", "UBER"]
PARAMS = {"atr_period": 14, "breach_atr": 1.5, "regime_ma": 50, "hold_days": 3, "stop_atr": 2.0,
          "risk_pct": 1.0, "max_position_pct": 15.0, "max_positions": 8, "cost_bps": 5.0,
          "start_cash": 10000.0, "idle": "QQQ"}
WARMUP = 60


class PaperError(Exception):
    pass


# ---------------------------------------------------------------- signal

def wilder_atr(bars, period=14):
    """ATR per bar (None until there is enough history). Wilder's smoothing."""
    out, atr, trs = [], None, []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(None)
            continue
        pc = bars[i - 1]["c"]
        tr = max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc))
        if atr is None:
            trs.append(tr)
            if len(trs) == period:
                atr = sum(trs) / period
        else:
            atr = (atr * (period - 1) + tr) / period
        out.append(atr)
    return out


def regime_series(bars_by, days, ma=50):
    """{day: 'bull'|'bear'|'unknown'} from an equal-weight index of the universe."""
    first = {}
    level = []
    for d in days:
        vals = []
        for s, idx in bars_by.items():
            b = idx.get(d)
            if b:
                first.setdefault(s, b["c"])
                vals.append(b["c"] / first[s])
        level.append(sum(vals) / len(vals) if vals else None)
    out = {}
    for i, d in enumerate(days):
        win = [x for x in level[max(0, i - ma + 1):i + 1] if x is not None]
        if len(win) < ma or level[i] is None:
            out[d] = "unknown"
        else:
            out[d] = "bull" if level[i] >= sum(win) / len(win) else "bear"
    return out


def prepare(charts, p=PARAMS):
    """charts {SYM: chart} -> (days, {SYM: {day: bar+atr+move}}, regime)."""
    bars_by, days = {}, set()
    for s, ch in charts.items():
        bars = ch["bars"]
        atr = wilder_atr(bars, p["atr_period"])
        idx = {}
        for i, b in enumerate(bars):
            prev_atr = atr[i - 1] if i else None
            move = (b["c"] - bars[i - 1]["c"]) / prev_atr if i and prev_atr else None
            idx[b["d"]] = dict(b, atr=atr[i], move_atr=move)
            days.add(b["d"])
        bars_by[s] = idx
    days = sorted(days)
    return days, bars_by, regime_series(bars_by, days, p["regime_ma"])


def signals_on(day, bars_by, regime, p=PARAMS, eligible=None):
    """eligible(day) -> set of tickers allowed that day (point-in-time index members), or None."""
    if regime.get(day) != "bull":
        return []
    out = []
    allowed = eligible(day) if eligible else None
    for s, idx in bars_by.items():
        if allowed is not None and s not in allowed:
            continue
        b = idx.get(day)
        if b and b["move_atr"] is not None and b["move_atr"] >= p["breach_atr"] and b["atr"]:
            out.append({"ticker": s, "move_atr": round(b["move_atr"], 2), "atr": b["atr"], "close": b["c"]})
    return sorted(out, key=lambda x: -x["move_atr"])


# ---------------------------------------------------------------- engine

def new_ledger(cash=None, p=PARAMS):
    cash = float(cash if cash is not None else p["start_cash"])
    return {"start_cash": cash, "cash": cash, "positions": {}, "pending": [], "trades": [], "equity": [],
            "last_day": None, "params": dict(p), "created": None}


def _cost(value, p):
    return abs(value) * p["cost_bps"] / 10000.0


def _idle_sell(led, value, ib, p):
    """Sell SPY (or whatever `idle` is) worth `value` at the open to fund a trade."""
    q = min(led.get("idle_shares", 0.0), value / (ib["o"] * (1 - p["cost_bps"] / 10000.0)))
    if q > 0:
        led["idle_shares"] -= q
        led["cash"] += q * ib["o"] - _cost(q * ib["o"], p)


def step(led, day, bars_by, regime, p=PARAMS, idle_bars=None, eligible=None):
    """One trading day: fill yesterday's signals at the open, run stops and
    exits, mark to market at the close, then queue today's signals.
    idle_bars ({day: bar} of p["idle"]): park unused cash there at the open."""
    ib = (idle_bars or {}).get(day) if p.get("idle") else None
    led.setdefault("idle_shares", 0.0)
    # 1. entries at the open
    still = []
    for o in led["pending"]:
        b = bars_by.get(o["ticker"], {}).get(day)
        if not b:  # no bar for it today: keep it one more day, then drop it
            o["tries"] = o.get("tries", 0) + 1
            if o["tries"] < 2:
                still.append(o)
            continue
        if o["ticker"] in led["positions"] or len(led["positions"]) >= p["max_positions"]:
            continue
        price = b["o"]
        equity = _equity(led, bars_by, day, at_open=True, idle_bar=ib)
        stop = price - p["stop_atr"] * o["atr"]
        risk_per_share = price - stop
        if risk_per_share <= 0:
            continue
        shares = (equity * p["risk_pct"] / 100.0) / risk_per_share
        shares = min(shares, equity * p["max_position_pct"] / 100.0 / price)
        shares = round(shares, 6) if p.get("fractional") else math.floor(shares)
        cost = shares * price
        if ib and cost + _cost(cost, p) > led["cash"]:
            _idle_sell(led, cost + _cost(cost, p) - led["cash"] + 0.01, ib, p)
        if shares <= 0 or cost < p.get("min_order", 1) or cost + _cost(cost, p) > led["cash"]:
            continue
        led["cash"] -= cost + _cost(cost, p)
        led["positions"][o["ticker"]] = {"shares": shares, "entry": round(price, 4), "entry_day": day,
                                         "stop": round(stop, 4), "days": 0, "signal_atr": o["move_atr"]}
    led["pending"] = still
    if ib and led["cash"] > 1.0:  # whatever no trade needs goes into the index at the open
        q = (led["cash"] - 0.5) / (ib["o"] * (1 + p["cost_bps"] / 10000.0))
        led["cash"] -= q * ib["o"] + _cost(q * ib["o"], p)
        led["idle_shares"] += q
    # 2. stops and time exits
    for s in list(led["positions"]):
        pos = led["positions"][s]
        b = bars_by.get(s, {}).get(day)
        if not b:
            continue
        pos["days"] += 1
        exit_px, why = None, None
        if b["l"] <= pos["stop"]:
            exit_px, why = min(b["o"], pos["stop"]), "stop"
        elif pos["days"] >= p["hold_days"]:
            exit_px, why = b["c"], "time"
        if exit_px is not None:
            value = pos["shares"] * exit_px
            led["cash"] += value - _cost(value, p)
            pnl = value - pos["shares"] * pos["entry"] - _cost(value, p) - _cost(pos["shares"] * pos["entry"], p)
            led["trades"].append({"ticker": s, "entry_day": pos["entry_day"], "exit_day": day,
                                  "entry": pos["entry"], "exit": round(exit_px, 4), "shares": pos["shares"],
                                  "pnl": round(pnl, 2),
                                  "ret_pct": round(100.0 * pnl / (pos["shares"] * pos["entry"]), 2),
                                  "why": why})
            del led["positions"][s]
    # 3. mark to market
    if ib:
        led["idle_last"] = ib["c"]
    eq = _equity(led, bars_by, day, idle_bar=ib)
    led["equity"].append([day, round(eq, 2)])
    # 4. today's signals -> tomorrow's open
    held = set(led["positions"])
    room = p["max_positions"] - len(held)
    for sig in signals_on(day, bars_by, regime, p, eligible):
        if room <= 0:
            break
        if sig["ticker"] in held:
            continue
        led["pending"].append({"ticker": sig["ticker"], "atr": sig["atr"], "move_atr": sig["move_atr"],
                               "signal_day": day})
        room -= 1
    led["last_day"] = day
    return led


def _equity(led, bars_by, day, at_open=False, idle_bar=None):
    eq = led["cash"]
    if led.get("idle_shares"):
        eq += led["idle_shares"] * ((idle_bar["o"] if at_open else idle_bar["c"]) if idle_bar
                                    else led.get("idle_last", 0.0))
    for s, pos in led["positions"].items():
        b = bars_by.get(s, {}).get(day)
        px = (b["o"] if at_open else b["c"]) if b else pos.get("last", pos["entry"])
        if b:
            pos["last"] = b["c"]
        eq += pos["shares"] * px
    return eq


# ---------------------------------------------------------------- stats

def stats(curve, trades=None):
    vals = [v for _, v in curve]
    if len(vals) < 2:
        return {}
    rets = [b / a - 1 for a, b in zip(vals, vals[1:]) if a]
    years = len(vals) / 252.0
    total = vals[-1] / vals[0] - 1
    peak, dd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0
    out = {"total_pct": round(100 * total, 2),
           "cagr_pct": round(100 * ((1 + total) ** (1 / years) - 1), 2) if years > 0 and total > -1 else None,
           "sharpe": round(statistics.mean(rets) / sd * math.sqrt(252), 2) if sd else None,
           "max_dd_pct": round(100 * dd, 2), "days": len(vals)}
    if trades is not None:
        wins = [t for t in trades if t["pnl"] > 0]
        out.update({"trades": len(trades), "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
                    "avg_trade_pct": round(statistics.mean(t["ret_pct"] for t in trades), 3) if trades else None})
    return out


def benchmark(days, bars_by, start_cash):
    """Equal-weight buy-and-hold of the same universe over the same days."""
    first = {}
    curve = []
    for d in days:
        vals = []
        for s, idx in bars_by.items():
            b = idx.get(d)
            if b:
                first.setdefault(s, b["c"])
                vals.append(b["c"] / first[s])
        if vals:
            curve.append([d, round(start_cash * sum(vals) / len(vals), 2)])
    return curve


def _idle_bars(p, offline=None, range_="5y", charts=None):
    """{day: bar} for the index idle cash sits in, or None."""
    sym = p.get("idle")
    if not sym:
        return None
    ch = (charts or {}).get(sym) or mk.get_chart(sym, offline=offline, range_=range_)
    return {b["d"]: b for b in ch["bars"]}


def backtest(charts, p=PARAMS, cash=None, idle_bars=None):
    days, bars_by, regime = prepare(charts, p)
    if len(days) <= WARMUP + 20:
        raise PaperError("not enough history: %d days" % len(days))
    led = new_ledger(cash, p)
    for d in days[WARMUP:]:
        step(led, d, bars_by, regime, p, idle_bars)
    bench = benchmark(days[WARMUP:], bars_by, led["start_cash"])
    years = {}
    for d, v in led["equity"]:
        years.setdefault(d[:4], [v, v])[1] = v
    byear = {}
    for d, v in bench:
        byear.setdefault(d[:4], [v, v])[1] = v
    per_year = [{"year": y, "bot_pct": round(100 * (e / s - 1), 2),
                 "buy_hold_pct": round(100 * (byear[y][1] / byear[y][0] - 1), 2) if y in byear else None}
                for y, (s, e) in sorted(years.items())]
    return {"from": days[WARMUP], "to": days[-1], "universe": sorted(bars_by), "params": p,
            "bot": stats(led["equity"], led["trades"]), "buy_hold": stats(bench), "per_year": per_year,
            "equity": led["equity"][::5], "benchmark": bench[::5], "recent_trades": led["trades"][-15:]}


def readiness(led, bench_stats=None):
    """Plain checks before anyone should even think about real money."""
    st = stats(led["equity"], led["trades"])
    checks = [
        ("60+ trading days of paper results", st.get("days", 0) >= 60),
        ("30+ closed trades", st.get("trades", 0) >= 30),
        ("made money after costs", (st.get("total_pct") or 0) > 0),
        ("beat buy-and-hold of the same stocks", bench_stats is not None and
         (st.get("total_pct") or -1e9) > (bench_stats.get("total_pct") or 1e9)),
        ("worst drawdown smaller than 15%", st.get("max_dd_pct", -100) > -15),
    ]
    return [{"check": c, "ok": bool(ok)} for c, ok in checks]


# ---------------------------------------------------------------- CLI

def load_charts(symbols, offline=None, range_="5y"):
    charts, errors = {}, []
    for s in symbols:
        try:
            charts[s] = mk.get_chart(s, offline=offline, range_=range_)
        except mk.MarketError as e:
            errors.append(str(e))
    if not charts:
        raise PaperError("no price data (%s)" % "; ".join(errors[:3]))
    return charts, errors


def read(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(path + ".tmp", path)


def universe(cfg_path):
    cfg = read(cfg_path, {}) or {}
    u = cfg.get("universe") or UNIVERSE
    return [mk.yahoo_symbol(s) for s in u]


def run_live(ledger_path, symbols, offline=None, today=None):
    """Catch the paper ledger up to the latest close. Returns (ledger, notes)."""
    led = read(ledger_path) or new_ledger()
    p = dict(PARAMS)
    p.update(led.get("params") or {})
    charts, errors = load_charts(symbols, offline=offline, range_="1y")
    days, bars_by, regime = prepare(charts, p)
    try:
        idle = _idle_bars(p, offline, "1y")
    except mk.MarketError as e:
        idle = None
        errors.append("idle cash stays cash today: %s" % e)
    if today:
        days = [d for d in days if d <= today]
    if not led.get("created"):
        led["created"] = days[-1]
        led["last_day"] = days[-2] if len(days) > 1 else None  # start trading from the latest close
    todo = [d for i, d in enumerate(days) if i >= WARMUP and (led["last_day"] is None or d > led["last_day"])]
    for d in todo:
        step(led, d, bars_by, regime, p, idle)
    led["regime"] = regime.get(days[-1], "unknown")
    led["today_signals"] = signals_on(days[-1], bars_by, regime, p)
    led["benchmark"] = benchmark([d for d in days if d >= led["created"]], bars_by, led["start_cash"])
    write(ledger_path, led)
    return led, errors


def summary(led):
    st = stats(led["equity"], led["trades"])
    bst = stats(led.get("benchmark") or [])
    return {"cash": round(led["cash"], 2), "equity": led["equity"][-1][1] if led["equity"] else led["cash"],
            "start_cash": led["start_cash"], "since": led.get("created"), "last_day": led.get("last_day"),
            "regime": led.get("regime"), "positions": led["positions"], "pending": led["pending"],
            "today_signals": led.get("today_signals", []), "stats": st, "buy_hold": bst,
            "recent_trades": led["trades"][-10:][::-1], "equity_curve": led["equity"],
            "benchmark_curve": led.get("benchmark", []), "readiness": readiness(led, bst),
            "note": "Paper money. Simulated fills at the open and close with 5 bps costs. Not financial advice."}


def _fmt(st):
    if not st:
        return "n/a"
    return "total %+.1f%%  CAGR %s  Sharpe %s  max DD %.1f%%" % (
        st["total_pct"], ("%+.1f%%" % st["cagr_pct"]) if st.get("cagr_pct") is not None else "n/a",
        st.get("sharpe"), st["max_dd_pct"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="ATR breach paper-trading bot (paper money only).")
    ap.add_argument("--dir", default="trader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "run", "status"):
        p = sub.add_parser(name)
        p.add_argument("--offline", metavar="DIR")
        p.add_argument("--json", action="store_true")
        p.add_argument("--symbols", nargs="*")
        if name == "run":
            p.add_argument("--today")
    p = sub.add_parser("reset")
    p.add_argument("--cash", type=float, default=PARAMS["start_cash"])
    a = ap.parse_args(argv)
    ledger_path = os.path.join(a.dir, "paper", "ledger.json")
    try:
        syms = [mk.yahoo_symbol(s) for s in (getattr(a, "symbols", None) or universe(os.path.join(a.dir, "paper", "config.json")))]
        if a.cmd == "reset":
            write(ledger_path, new_ledger(a.cash))
            print("paper ledger reset with %s" % a.cash)
            return 0
        if a.cmd == "backtest":
            charts, errors = load_charts(syms, offline=a.offline)
            res = backtest(charts, idle_bars=_idle_bars(PARAMS, a.offline))
            res["errors"] = errors
            write(os.path.join(a.dir, "paper", "backtest.json"), res)
            if a.json:
                print(json.dumps(res, indent=1))
            else:
                print("ATR breach bot, %s to %s, %d stocks" % (res["from"], res["to"], len(res["universe"])))
                print("  bot      %s  trades %s  win %s%%  avg %s%%" % (
                    _fmt(res["bot"]), res["bot"].get("trades"), res["bot"].get("win_rate_pct"),
                    res["bot"].get("avg_trade_pct")))
                print("  buy&hold %s" % _fmt(res["buy_hold"]))
                for y in res["per_year"]:
                    print("  %s  bot %+.1f%%  buy&hold %+.1f%%" % (y["year"], y["bot_pct"], y["buy_hold_pct"] or 0))
                print("Simulated on past data. Past results do not predict future ones.")
            return 0
        if a.cmd == "run":
            led, errors = run_live(ledger_path, syms, offline=a.offline, today=a.today)
        else:
            led = read(ledger_path)
            if not led:
                raise PaperError("no paper ledger yet: run `paper.py run` first")
        s = summary(led)
        if a.json:
            print(json.dumps(s, indent=1))
        else:
            print("Paper bot  equity %.2f (started %.2f on %s)  regime %s" % (
                s["equity"], s["start_cash"], s["since"], s["regime"]))
            print("  bot      " + _fmt(s["stats"]))
            print("  buy&hold " + _fmt(s["buy_hold"]))
            for t, pos in s["positions"].items():
                print("  holding %-6s %s @ %.2f stop %.2f (day %d)" % (t, pos["shares"], pos["entry"], pos["stop"], pos["days"]))
            for o in s["pending"]:
                print("  buys at next open: %s (%.1f ATR up-move)" % (o["ticker"], o["move_atr"]))
            for t in s["recent_trades"][:5]:
                print("  closed %-6s %+.2f%% (%s) %s" % (t["ticker"], t["ret_pct"], t["why"], t["exit_day"]))
            print("  readiness: " + ", ".join(("ok " if c["ok"] else "not yet ") + c["check"] for c in s["readiness"]))
            print(s["note"])
        return 0
    except (PaperError, mk.MarketError) as e:
        print("paper: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
