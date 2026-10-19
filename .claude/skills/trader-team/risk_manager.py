"""The Risk Manager: says yes or no to every trade, and decides its size.

Rules (all in config.json):
  - at most 2% of the PAPER account can be lost on one trade if the stop is hit
    (fees and slippage included in that loss)
  - every trade gets a stop-loss (entry - 1.5 ATR) and a take-profit
    (entry + 3 ATR), so a win is twice the size of a loss
  - no more than 25% of the account in one coin, 3 open trades, 6% total at risk
  - no second position in a coin already held, and a cool-off after a stop
  - a 5% loss in one day trips the kill switch
"""


def plan_entry(sig, account, cfg, now):
    """sig: the Analyst's BUY. account: {equity, cash, positions, cooldown}. -> decision."""
    coin, price, a = sig["coin"], sig["price"], sig.get("atr") or 0
    reasons, ok = [], True
    pos = account["positions"]
    if coin in pos:
        return {"approved": False, "reasons": ["already holding %s" % coin]}
    until = (account.get("cooldown") or {}).get(coin, 0)
    if now < until:
        return {"approved": False, "reasons": ["%s is cooling off after a stop" % coin]}
    if len(pos) >= cfg["max_open"]:
        return {"approved": False, "reasons": ["already %d open trades (max %d)" % (len(pos), cfg["max_open"])]}
    if a <= 0:
        return {"approved": False, "reasons": ["no ATR to set a stop from"]}
    eq = float(account["equity"])
    stop = price - cfg["stop_atr"] * a
    tp = price + cfg["tp_atr"] * a
    if stop <= 0:
        return {"approved": False, "reasons": ["the stop would be at or below zero"]}
    cost = (cfg["fee_pct"] + cfg["slippage_pct"]) / 100.0  # per side
    loss_per_unit = (price - stop) + cost * (price + stop)
    budget = eq * cfg["risk_pct"] / 100.0
    qty = budget / loss_per_unit
    caps = [("risk %g%% of the account" % cfg["risk_pct"], qty)]
    caps.append(("max %g%% of the account in one coin" % cfg["max_position_pct"],
                 eq * cfg["max_position_pct"] / 100.0 / price))
    caps.append(("the cash on hand", float(account["cash"]) * 0.98 / (price * (1 + cost))))
    open_risk = sum(p.get("risk_usd", 0) for p in pos.values())
    room = eq * cfg["max_total_risk_pct"] / 100.0 - open_risk
    caps.append(("max %g%% of the account at risk in total" % cfg["max_total_risk_pct"], room / loss_per_unit))
    why, qty = min(caps, key=lambda c: c[1])
    qty = max(0.0, qty)
    if why != caps[0][0]:
        reasons.append("size cut to fit %s" % why)
    notional = qty * price
    if notional < cfg["min_notional"]:
        ok = False
        reasons.append("only $%.2f fits the rules (min $%g)" % (notional, cfg["min_notional"]))
    risk_usd = qty * loss_per_unit
    reasons.insert(0, "risking $%.2f (%.2f%% of $%.2f) with stop %.6g and take-profit %.6g" % (
        risk_usd, 100 * risk_usd / eq if eq else 0, eq, stop, tp))
    cost_share = cost * (price + stop) / loss_per_unit
    reasons.append("fees and slippage are %.0f%% of what this trade risks%s" % (
        100 * cost_share, " (high: the stop is close compared with trading costs)" if cost_share > 0.3 else ""))
    return {"approved": ok, "reasons": reasons, "qty": round(qty, 8), "notional": round(notional, 2),
            "stop": stop, "tp": tp, "risk_usd": round(risk_usd, 2)}


def daily_loss_hit(day_start_equity, equity, cfg):
    """True when today's loss reached the kill-switch limit."""
    if not day_start_equity:
        return False
    return equity <= day_start_equity * (1 - cfg["daily_loss_kill_pct"] / 100.0)
