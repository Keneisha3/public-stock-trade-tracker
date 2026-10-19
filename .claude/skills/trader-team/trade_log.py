"""The trade log: every trade, error and equity reading goes to a CSV you can open in Excel.

  trades.csv   one row per closed trade (the fields the review prompt needs)
  events.csv   errors, downtime, missed cycles, kill switch, refusals
  equity.csv   account value and buy-and-hold value after every cycle

summary() reads them back and works out the numbers for the daily report:
total trades, win rate, average win and loss, P&L, max drawdown, and the bot
against simply holding the same coins.
"""

import csv
import datetime
import os

TRADE_FIELDS = ["opened_at", "closed_at", "mode", "asset", "side", "entry", "exit", "qty", "position_usd",
                "stop_loss", "take_profit", "fees_slippage_est", "pnl", "pnl_pct", "exit_reason",
                "approved_by", "scanner_note", "analyst_note", "risk_note"]
EVENT_FIELDS = ["time", "kind", "detail"]
EQUITY_FIELDS = ["time", "equity", "buy_and_hold", "open_positions"]


def iso(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _append(path, fields, row):
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def trade(path, row):
    _append(path, TRADE_FIELDS, row)


def event(path, ts, kind, detail):
    _append(path, EVENT_FIELDS, {"time": iso(ts), "kind": kind, "detail": detail})


def equity(path, ts, eq, hold, n_open):
    _append(path, EQUITY_FIELDS, {"time": iso(ts), "equity": round(eq, 2),
                                  "buy_and_hold": round(hold, 2) if hold is not None else "",
                                  "open_positions": n_open})


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def summary(folder, day=None):
    """Numbers for the report. day='YYYY-MM-DD' limits it to that UTC day."""
    trades = read(os.path.join(folder, "trades.csv"))
    curve = read(os.path.join(folder, "equity.csv"))
    events = read(os.path.join(folder, "events.csv"))
    if day:
        trades = [t for t in trades if t["closed_at"].startswith(day)]
        curve = [c for c in curve if c["time"].startswith(day)]
        events = [e for e in events if e["time"].startswith(day)]
    pnls = [_f(t["pnl"]) or 0.0 for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    eqs = [_f(c["equity"]) for c in curve if _f(c["equity"]) is not None]
    peak, dd = None, 0.0
    for v in eqs:
        peak = v if peak is None else max(peak, v)
        dd = min(dd, v / peak - 1) if peak else dd
    holds = [_f(c["buy_and_hold"]) for c in curve if _f(c["buy_and_hold"])]
    first_eq = eqs[0] if eqs else None
    out = {
        "period": day or "since start", "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "pnl": round(sum(pnls), 2),
        "fees_slippage": round(sum(_f(t["fees_slippage_est"]) or 0 for t in trades), 2),
        "max_drawdown_pct": round(100 * dd, 2),
        "equity_start": first_eq, "equity_end": eqs[-1] if eqs else None,
        "bot_return_pct": round(100 * (eqs[-1] / first_eq - 1), 2) if first_eq else None,
        "hold_return_pct": round(100 * (holds[-1] / holds[0] - 1), 2) if len(holds) >= 1 and holds[0] else None,
        "errors": sum(1 for e in events if e["kind"] in ("error", "api_error")),
        "downtime": sum(1 for e in events if e["kind"] == "downtime"),
        "exit_reasons": {},
    }
    for t in trades:
        out["exit_reasons"][t["exit_reason"]] = out["exit_reasons"].get(t["exit_reason"], 0) + 1
    return out


def render(s, mode="PAPER"):
    def p(x):
        return "n/a" if x is None else "%+.2f%%" % x

    lines = ["[%s] Summary (%s)" % (mode, s["period"]),
             "  trades %d  (wins %d, losses %d)  win rate %s" % (
                 s["trades"], s["wins"], s["losses"], "n/a" if s["win_rate_pct"] is None else "%.1f%%" % s["win_rate_pct"]),
             "  average win %s  average loss %s  fees+slippage %s" % (
                 "n/a" if s["avg_win"] is None else "$%.2f" % s["avg_win"],
                 "n/a" if s["avg_loss"] is None else "$%.2f" % s["avg_loss"], "$%.2f" % s["fees_slippage"]),
             "  P&L $%.2f   max drawdown %.2f%%" % (s["pnl"], s["max_drawdown_pct"]),
             "  bot %s   vs holding the same coins %s" % (p(s["bot_return_pct"]), p(s["hold_return_pct"])),
             "  errors %d, downtime gaps %d" % (s["errors"], s["downtime"])]
    if s["exit_reasons"]:
        lines.append("  exits: " + ", ".join("%s %d" % kv for kv in sorted(s["exit_reasons"].items())))
    return "\n".join(lines)
