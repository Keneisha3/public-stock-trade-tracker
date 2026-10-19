#!/usr/bin/env python3
"""The crypto bot team, PAPER MONEY ONLY. Standard library only.

Every 15 minutes the team works through one cycle:

  1. exits      open positions are checked against their stop-loss and
                take-profit, then the Analyst can call an exit
  2. Scanner    checks the data for 10 coins and picks possible setups
  3. Analyst    EMA crossover + RSI: is the setup a BUY?
  4. Risk Mgr   sizes it (max 2% of the account at risk), sets stop and target,
                or says no
  5. Executor   places the PAPER / SIMULATED trade and logs it to the CSV

    python3 team.py check                  # is everything set up? (never trades)
    python3 team.py run                    # every 15 minutes until Ctrl+C or the kill switch
    python3 team.py run --once             # one cycle (for cron or a scheduled task)
    python3 team.py status                 # positions, equity, kill switch
    python3 team.py summary [--day YYYY-MM-DD]
    python3 team.py kill                   # KILL SWITCH: sell all paper positions and stop
    python3 team.py kill --keep-positions  # stop, leave positions (their stops are no longer watched)
    python3 team.py resume                 # clear the kill switch
    python3 team.py backtest --days 30     # the same rules on the last 30 days, simulated

Files (git-ignored) in trader/team/: config.json, state.json, trades.csv,
events.csv, equity.csv, KILL. Keys live in .env, never in code or chat.

NOT FINANCIAL ADVICE. Paper results look better than real trading: real
fills have slippage, fees, latency and liquidity limits.
"""

import argparse
import bisect
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
import analyst  # noqa: E402
import candles  # noqa: E402
import executor  # noqa: E402
import risk_manager  # noqa: E402
import scanner  # noqa: E402
import trade_log  # noqa: E402

DEFAULTS = {
    "coins": ["BTC", "ETH", "SOL", "XRP", "DOGE", "LTC", "BCH", "LINK", "AVAX", "DOT"],
    "interval_min": 1440, "lookback_bars": 200,  # daily bars: the only timeframe that made money in both test periods
    "ema_fast": 9, "ema_slow": 21, "ema_trend": 50, "rsi_period": 14, "rsi_min": 50, "rsi_max": 70,
    "atr_period": 14, "stop_atr": 1.5, "tp_atr": 3.0,
    "risk_pct": 2.0, "max_position_pct": 25, "max_open": 3, "max_total_risk_pct": 6,
    "daily_loss_kill_pct": 5, "min_notional": 10, "fee_pct": 0.25, "slippage_pct": 0.05,
    "cooldown_bars": 4, "max_consecutive_errors": 5,
    "broker": "sim", "data": "coinbase", "start_cash": 10000,
}


class TeamError(Exception):
    pass


class Paths:
    def __init__(self, base):
        self.dir = base
        self.config = os.path.join(base, "config.json")
        self.state = os.path.join(base, "state.json")
        self.trades = os.path.join(base, "trades.csv")
        self.events = os.path.join(base, "events.csv")
        self.equity = os.path.join(base, "equity.csv")
        self.kill = os.path.join(base, "KILL")
        self.summary = os.path.join(base, "last_summary.txt")


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(path + ".tmp", path)


def load_cfg(paths):
    cfg = dict(DEFAULTS)
    user = _read(paths.config, {})
    cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    cfg["coins"] = [str(c).upper().replace("-USD", "").replace("/USD", "") for c in cfg["coins"]]
    if cfg["broker"] not in ("sim", "alpaca-paper"):
        raise TeamError("config broker must be \"sim\" or \"alpaca-paper\"")
    if cfg["risk_pct"] > 2:
        raise TeamError("risk_pct is %s: the team never risks more than 2%% of the account on one trade"
                        % cfg["risk_pct"])
    return cfg


def env_for(base):
    env, _ = candles.load_env(os.path.join(os.getcwd(), ".env"), os.path.join(REPO, ".env"),
                              os.path.join(base, ".env"))
    return env


# ---------------------------------------------------------------- kill switch

def read_kill(paths):
    return _read(paths.kill, None) if os.path.exists(paths.kill) else None


def set_kill(paths, reason, flatten=True, now=None):
    _write(paths.kill, {"reason": reason, "flatten": flatten, "set_at": trade_log.iso(now or time.time())})
    trade_log.event(paths.events, now or time.time(), "kill_switch", reason)


# ---------------------------------------------------------------- one cycle

def _day(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")


def hold_value(state, prices):
    hs = state.get("hold_start") or {}
    ratios = [prices[c] / hs[c] for c in hs if c in prices and hs[c]]
    if not ratios or not state.get("start_equity"):
        return None
    return state["start_equity"] * sum(ratios) / len(ratios)


def _close(state, coin, price, reason, broker, cfg, paths, now, log):
    p = state["positions"][coin]
    fill = broker.sell(coin, p["qty"], price)
    fees = p.get("fee_in", 0) + fill["fee"]
    slip = (p["qty"] * p["entry"] + fill["qty"] * fill["price"]) * cfg["slippage_pct"] / 100.0
    pnl = (fill["price"] - p["entry"]) * fill["qty"] - fees
    trade_log.trade(paths.trades, {
        "opened_at": trade_log.iso(p["opened_t"]), "closed_at": trade_log.iso(now), "mode": broker.label,
        "asset": coin + "/USD", "side": "long", "entry": round(p["entry"], 8), "exit": round(fill["price"], 8),
        "qty": p["qty"], "position_usd": round(p["qty"] * p["entry"], 2), "stop_loss": round(p["stop"], 8),
        "take_profit": round(p["tp"], 8), "fees_slippage_est": round(fees + slip, 2), "pnl": round(pnl, 2),
        "pnl_pct": round(100.0 * pnl / (p["qty"] * p["entry"]), 2), "exit_reason": reason,
        "approved_by": p["approved_by"], "scanner_note": p["scanner_note"], "analyst_note": p["analyst_note"],
        "risk_note": p["risk_note"]})
    del state["positions"][coin]
    if reason == "stop-loss":
        state.setdefault("cooldown", {})[coin] = now + cfg["cooldown_bars"] * cfg["interval_min"] * 60
    log("[%s] SELL %s %s @ %.6g  %s  P&L $%.2f" % (broker.label, p["qty"], coin, fill["price"], reason, pnl))
    return {"coin": coin, "reason": reason, "pnl": round(pnl, 2)}


def cycle(state, bars_all, now, broker, cfg, paths, log=print):
    """One pass of the team over closed bars. Pure apart from the broker and the log files."""
    iv = cfg["interval_min"]
    bars_by = {c: candles.closed_only(b, now, iv) for c, b in bars_all.items()}
    prices = {c: b[-1]["c"] for c, b in bars_by.items() if b}
    pos = state.setdefault("positions", {})
    rep = {"time": now, "mode": broker.label, "entries": [], "exits": [], "skipped": [], "refused": []}
    for c, px in prices.items():
        state.setdefault("hold_start", {}).setdefault(c, px)
    if "start_equity" not in state:
        state["start_equity"] = broker.account(prices)["equity"]

    kill = read_kill(paths)
    if kill:
        if kill.get("flatten"):
            for c in list(pos):
                if c in prices:
                    rep["exits"].append(_close(state, c, prices[c], "kill switch", broker, cfg, paths, now, log))
        rep["killed"] = kill["reason"]
        _finish(state, broker, prices, paths, now, rep)
        return rep

    # 1. exits: stop-loss / take-profit on every bar since the last check
    for c in list(pos):
        p, hit = pos[c], None
        for b in [b for b in bars_by.get(c, []) if b["t"] > p["checked_t"]]:
            p["checked_t"] = b["t"]
            if b["l"] <= p["stop"]:  # if one bar hits both, assume the stop came first
                hit = ("stop-loss", min(b["o"], p["stop"]))
                break
            if b["h"] >= p["tp"]:
                hit = ("take-profit", max(b["o"], p["tp"]))
                break
        if hit:
            rep["exits"].append(_close(state, c, hit[1], hit[0], broker, cfg, paths, now, log))

    # daily loss limit -> kill switch, flatten
    acct = broker.account(prices)
    day = _day(now)
    starts = state.setdefault("day_start_equity", {})
    starts.setdefault(day, acct["equity"])
    for d in sorted(starts)[:-7]:
        del starts[d]
    if risk_manager.daily_loss_hit(starts[day], acct["equity"], cfg):
        set_kill(paths, "daily loss limit: equity %.2f is %.1f%% under today's start %.2f" % (
            acct["equity"], 100 * (1 - acct["equity"] / starts[day]), starts[day]), True, now)
        for c in list(pos):
            if c in prices:
                rep["exits"].append(_close(state, c, prices[c], "kill switch", broker, cfg, paths, now, log))
        rep["killed"] = "daily loss limit"
        _finish(state, broker, prices, paths, now, rep)
        return rep

    # 2-5. Scanner -> Analyst -> Risk Manager -> Executor
    setups, skipped = scanner.scan(bars_by, cfg, now, held=set(pos))
    rep["skipped"] = skipped
    for s in setups:
        c = s["coin"]
        sig = analyst.analyze(c, bars_by[c], cfg)
        if c in pos:
            if sig["action"] == "EXIT":
                rep["exits"].append(_close(state, c, prices[c], "signal: EMA cross down", broker, cfg, paths, now, log))
            continue
        if sig["action"] != "BUY":
            rep["refused"].append({"coin": c, "by": "Analyst", "why": "; ".join(sig["reasons"])})
            continue
        if state.get("entered_bar", {}).get(c) == bars_by[c][-1]["t"]:  # one entry per signal bar
            rep["refused"].append({"coin": c, "by": "Analyst", "why": "already traded this bar's signal"})
            continue
        acct = broker.account(prices)
        acct.update(positions=pos, cooldown=state.get("cooldown", {}))
        plan = risk_manager.plan_entry(sig, acct, cfg, now)
        if not plan["approved"]:
            rep["refused"].append({"coin": c, "by": "Risk Manager", "why": "; ".join(plan["reasons"])})
            continue
        try:
            fill = broker.buy(c, plan["qty"], sig["price"])
        except (executor.PaperGuardError, candles.DataError) as e:
            rep["refused"].append({"coin": c, "by": "Executor", "why": str(e)})
            trade_log.event(paths.events, now, "error", "Executor refused %s: %s" % (c, e))
            continue
        shift = fill["price"] - sig["price"]  # keep the stop and target the same distance from the real fill
        pos[c] = {"qty": fill["qty"], "entry": fill["price"], "stop": plan["stop"] + shift, "tp": plan["tp"] + shift,
                  "opened_t": now, "checked_t": bars_by[c][-1]["t"], "fee_in": fill["fee"],
                  "risk_usd": plan["risk_usd"], "approved_by": "Scanner > Analyst > Risk Manager > Executor (%s)"
                  % broker.label, "scanner_note": s["why"], "analyst_note": "; ".join(sig["reasons"]),
                  "risk_note": "; ".join(plan["reasons"])}
        state.setdefault("entered_bar", {})[c] = bars_by[c][-1]["t"]
        rep["entries"].append({"coin": c, "qty": fill["qty"], "price": fill["price"]})
        log("[%s] BUY %s %s @ %.6g  stop %.6g  target %.6g  risking $%.2f" % (
            broker.label, fill["qty"], c, fill["price"], pos[c]["stop"], pos[c]["tp"], plan["risk_usd"]))
    _finish(state, broker, prices, paths, now, rep)
    return rep


def _finish(state, broker, prices, paths, now, rep):
    acct = broker.account(prices)
    hold = hold_value(state, prices)
    trade_log.equity(paths.equity, now, acct["equity"], hold, len(state.get("positions", {})))
    rep["equity"], rep["buy_and_hold"] = round(acct["equity"], 2), (round(hold, 2) if hold else None)
    state["last_cycle"] = now


# ---------------------------------------------------------------- live

def fetch_bars(cfg, env, now, http=candles.http_json, offline=None):
    coins = cfg["coins"]
    if offline:
        out, errors = {}, []
        for c in coins:
            path = os.path.join(offline, "candles-%s.json" % c)
            if os.path.exists(path):
                out[c] = _read(path, [])
            else:
                errors.append("no offline candles for %s" % c)
        return out, errors
    start = now - (cfg["lookback_bars"] + 2) * cfg["interval_min"] * 60
    return candles.fetch(coins, cfg["data"], start, now, cfg["interval_min"], http=http, keys=env)


def run_once(base, now=None, http=candles.http_json, offline=None, log=print, sleep=time.sleep):
    paths = Paths(base)
    cfg = load_cfg(paths)
    now = int(now or time.time())
    state = _read(paths.state, {"started": now, "mode": cfg["broker"]})
    if state.get("mode") and state["mode"] != cfg["broker"]:
        raise TeamError("state.json was made with broker %r but config says %r: run `team.py reset` first"
                        % (state["mode"], cfg["broker"]))
    iv = cfg["interval_min"] * 60
    if state.get("last_cycle") and now - state["last_cycle"] > 2 * iv + 60:
        missed = int((now - state["last_cycle"]) // iv) - 1
        trade_log.event(paths.events, now, "downtime", "about %d cycle(s) missed since %s" % (
            missed, trade_log.iso(state["last_cycle"])))
    env = env_for(base)
    try:
        broker = executor.make_broker(cfg, state, env, http=http, sleep=sleep)
        bars, errors = fetch_bars(cfg, env, now, http=http, offline=offline)
        for e in errors:
            trade_log.event(paths.events, now, "api_error", e)
        if not bars:
            raise TeamError("no price data this cycle (%s)" % "; ".join(errors[:2]))
        prev_day = _day(state["last_cycle"]) if state.get("last_cycle") else None
        rep = cycle(state, bars, now, broker, cfg, paths, log=log)
        state["consecutive_errors"] = 0
        _write(paths.state, state)
        if prev_day and prev_day != _day(now):
            text = trade_log.render(trade_log.summary(paths.dir, prev_day), broker.label) + "\n" + \
                trade_log.render(trade_log.summary(paths.dir), broker.label)
            with open(paths.summary, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            log(text)
        return rep
    except (TeamError, executor.PaperGuardError, candles.DataError) as e:
        state["consecutive_errors"] = state.get("consecutive_errors", 0) + 1
        trade_log.event(paths.events, now, "error", str(e))
        if state["consecutive_errors"] >= cfg["max_consecutive_errors"] and not read_kill(paths):
            set_kill(paths, "%d cycles in a row failed; last: %s" % (state["consecutive_errors"], e), True, now)
        _write(paths.state, state)
        raise


def run_loop(base, log=print):
    cfg = load_cfg(Paths(base))
    iv = cfg["interval_min"] * 60
    log("Paper bot team running every %d minutes. Ctrl+C to stop; `team.py kill` sells everything and stops."
        % cfg["interval_min"])
    while True:
        try:
            rep = run_once(base, log=log)
            log("[%s] %s  equity $%.2f  buy-and-hold %s  open %d  new %d  closed %d" % (
                rep["mode"], trade_log.iso(rep["time"]), rep["equity"],
                "$%.2f" % rep["buy_and_hold"] if rep["buy_and_hold"] else "n/a",
                len(_read(Paths(base).state, {}).get("positions", {})), len(rep["entries"]), len(rep["exits"])))
            if rep.get("killed"):
                log("KILL SWITCH: %s. Stopped. `team.py resume` to start again." % rep["killed"])
                return 1
        except (TeamError, executor.PaperGuardError, candles.DataError) as e:
            log("cycle failed: %s (logged; will retry next cycle)" % e)
            if read_kill(Paths(base)):
                log("KILL SWITCH set after repeated errors. Stopped.")
                return 1
        step = min(iv, 900)  # check stops every 15 minutes even on daily bars
        wait = step - (time.time() % step) + 20  # 20 s after a 15-minute mark
        time.sleep(wait)


# ---------------------------------------------------------------- backtest

def backtest(base, days=30, http=candles.http_json, offline=None, log=print):
    cfg = load_cfg(Paths(base))
    cfg = dict(cfg, broker="sim")
    out = os.path.join(base, "backtest")
    paths = Paths(out)
    for f in (paths.state, paths.trades, paths.events, paths.equity, paths.kill):
        if os.path.exists(f):
            os.remove(f)
    iv = cfg["interval_min"] * 60
    end = int(time.time()) // iv * iv
    start = end - days * 86400 - (cfg["lookback_bars"] + 2) * iv
    if offline:
        bars, errors = fetch_bars(cfg, {}, end, offline=offline)
    else:
        bars, errors = candles.fetch(cfg["coins"], cfg["data"], start, end, cfg["interval_min"], http=http)
    if not bars:
        raise TeamError("no history for the backtest (%s)" % "; ".join(errors[:2]))
    times = sorted({b["t"] for bs in bars.values() for b in bs})
    keys = {c: [b["t"] for b in bs] for c, bs in bars.items()}
    state, broker = {"mode": "sim"}, None
    broker = executor.SimBroker(state, cfg)
    quiet = lambda *a: None  # noqa: E731
    for t in times[cfg["lookback_bars"]:]:
        now = t + iv
        window = {}
        for c, bs in bars.items():
            i = bisect.bisect_right(keys[c], t)
            window[c] = bs[max(0, i - cfg["lookback_bars"]):i]
        rep = cycle(state, window, now, broker, cfg, paths, log=quiet)
        if rep.get("killed"):
            break
    s = trade_log.summary(out)
    s["from"], s["to"] = trade_log.iso(times[cfg["lookback_bars"]]), trade_log.iso(times[-1])
    s["errors_fetching"] = errors
    _write(os.path.join(out, "result.json"), s)
    log("Backtest %s to %s, %d coins (SIMULATED)" % (s["from"], s["to"], len(bars)))
    log(trade_log.render(s, "SIMULATED"))
    if read_kill(paths):
        log("The daily-loss kill switch fired during the test: %s" % read_kill(paths)["reason"])
    log("Past results do not predict future ones, and a backtest is easier than live trading.")
    return s


# ---------------------------------------------------------------- CLI

def cmd_check(base):
    paths = Paths(base)
    cfg = load_cfg(paths)
    env = env_for(base)
    print("config: broker=%s data=%s coins=%s" % (cfg["broker"], cfg["data"], ",".join(cfg["coins"])))
    print("rules: risk %g%%/trade, stop %g ATR, target %g ATR, max %d open, kill at -%g%%/day" % (
        cfg["risk_pct"], cfg["stop_atr"], cfg["tp_atr"], cfg["max_open"], cfg["daily_loss_kill_pct"]))
    if cfg["broker"] == "sim":
        print("OK: SIMULATED mode, fake money in trader/team/state.json, no account or keys needed.")
        return 0
    print("key: %s  secret: %s  TRADING_MODE=%s" % (candles.mask(env.get("PAPER_API_KEY")),
                                                  candles.mask(env.get("PAPER_API_SECRET")),
                                                  env.get("TRADING_MODE", "(not set)")))
    acct = executor.AlpacaPaperBroker(env, cfg).verify()
    print("OK: Alpaca PAPER account confirmed (%s), equity $%s. No trade was placed." % (
        candles.mask(acct.get("account_number")), acct.get("equity")))
    return 0


def cmd_status(base):
    paths = Paths(base)
    state = _read(paths.state, {})
    kill = read_kill(paths)
    print("mode: %s  started: %s  last cycle: %s" % (
        state.get("mode", "not started"), trade_log.iso(state["started"]) if state.get("started") else "-",
        trade_log.iso(state["last_cycle"]) if state.get("last_cycle") else "-"))
    print("kill switch: %s" % (("ON: " + kill["reason"]) if kill else "off"))
    for c, p in (state.get("positions") or {}).items():
        print("  %-5s %s @ %.6g  stop %.6g  target %.6g  since %s" % (
            c, p["qty"], p["entry"], p["stop"], p["tp"], trade_log.iso(p["opened_t"])))
    print(trade_log.render(trade_log.summary(paths.dir), "SIMULATED" if state.get("mode") == "sim" else "PAPER"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Crypto bot team, paper money only.")
    ap.add_argument("--dir", default=os.path.join("trader", "team"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--once", action="store_true")
    p.add_argument("--offline", metavar="DIR", help="read DIR/candles-<COIN>.json instead of the network")
    p.add_argument("--now", type=int, help="epoch seconds, for tests")
    sub.add_parser("check")
    sub.add_parser("status")
    p = sub.add_parser("summary")
    p.add_argument("--day")
    p = sub.add_parser("kill")
    p.add_argument("--keep-positions", action="store_true")
    p.add_argument("--reason", default="kill switch pressed by you")
    sub.add_parser("resume")
    p = sub.add_parser("reset", help="SIMULATED mode only: start over with fresh fake money")
    p = sub.add_parser("backtest")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--offline", metavar="DIR")
    a = ap.parse_args(argv)
    paths = Paths(a.dir)
    try:
        if a.cmd == "check":
            return cmd_check(a.dir)
        if a.cmd == "status":
            return cmd_status(a.dir)
        if a.cmd == "summary":
            mode = _read(paths.state, {}).get("mode")
            print(trade_log.render(trade_log.summary(a.dir, a.day), "SIMULATED" if mode == "sim" else "PAPER"))
            return 0
        if a.cmd == "kill":
            set_kill(paths, a.reason, flatten=not a.keep_positions)
            print("KILL SWITCH ON. %s" % ("Paper positions are sold on the next cycle (or now, with `team.py run "
                                          "--once`), then the bot stops." if not a.keep_positions else
                                          "Positions are kept but nobody watches their stops now."))
            return 0
        if a.cmd == "resume":
            if os.path.exists(paths.kill):
                os.remove(paths.kill)
                trade_log.event(paths.events, time.time(), "resume", "kill switch cleared")
            print("kill switch off")
            return 0
        if a.cmd == "reset":
            if load_cfg(paths)["broker"] != "sim":
                raise TeamError("reset is for SIMULATED mode; reset an Alpaca paper account on Alpaca's site")
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for f in (paths.state, paths.trades, paths.events, paths.equity):
                if os.path.exists(f):
                    os.replace(f, f + "." + stamp + ".old")
            print("fresh start with $%s of fake money (old files kept as *.old)" % load_cfg(paths)["start_cash"])
            return 0
        if a.cmd == "backtest":
            backtest(a.dir, a.days, offline=a.offline)
            return 0
        if a.once or a.offline:
            rep = run_once(a.dir, now=a.now, offline=a.offline)
            print("[%s] equity $%.2f  buy-and-hold %s  entries %d  exits %d%s" % (
                rep["mode"], rep["equity"], "$%.2f" % rep["buy_and_hold"] if rep["buy_and_hold"] else "n/a",
                len(rep["entries"]), len(rep["exits"]), ("  KILLED: " + rep["killed"]) if rep.get("killed") else ""))
            return 0
        return run_loop(a.dir)
    except KeyboardInterrupt:
        print("\nstopped by you (positions and logs are saved)")
        return 0
    except (TeamError, executor.PaperGuardError, candles.DataError) as e:
        print("team: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
