"""The Analyst: decides whether a setup is worth a trade.

Strategy (trend + momentum, deliberately simple):
  BUY   the fast EMA (9 bars) just crossed ABOVE the slow EMA (21 bars) on the
        last closed bar, price is above the 50-bar EMA (the bigger trend is up),
        and RSI(14) is between 50 and 70 (momentum, but not already overheated)
  EXIT  the fast EMA crossed back BELOW the slow EMA (the move is over)

Stops and take-profits are set by the Risk Manager from ATR (how far the
coin normally moves in one bar), not by the Analyst.
"""


def ema(values, n):
    """Exponential moving average; None until there are n values."""
    out, k, cur = [], 2.0 / (n + 1), None
    for i, v in enumerate(values):
        if i + 1 < n:
            out.append(None)
            continue
        cur = sum(values[i + 1 - n:i + 1]) / n if cur is None else v * k + cur * (1 - k)
        out.append(cur)
    return out


def rsi(closes, n=14):
    """Wilder's RSI, 0-100. None until there is enough history."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def atr(bars, n=14):
    """Average true range, Wilder smoothing. None until there is enough history."""
    out, cur, trs = [None] * len(bars), None, []
    for i in range(1, len(bars)):
        b, pc = bars[i], bars[i - 1]["c"]
        tr = max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc))
        if cur is None:
            trs.append(tr)
            if len(trs) == n:
                cur = sum(trs) / n
        else:
            cur = (cur * (n - 1) + tr) / n
        out[i] = cur
    return out


def analyze(coin, bars, cfg):
    """One coin's closed bars -> a decision with the reasons spelled out."""
    need = max(cfg["ema_trend"], cfg["ema_slow"], cfg["rsi_period"], cfg["atr_period"]) + 2
    if len(bars) < need:
        return {"coin": coin, "action": "NONE", "reasons": ["only %d bars, need %d" % (len(bars), need)]}
    closes = [b["c"] for b in bars]
    f, s, t = ema(closes, cfg["ema_fast"]), ema(closes, cfg["ema_slow"]), ema(closes, cfg["ema_trend"])
    r, a = rsi(closes, cfg["rsi_period"]), atr(bars, cfg["atr_period"])
    out = {"coin": coin, "price": closes[-1], "bar_time": bars[-1]["t"], "ema_fast": f[-1], "ema_slow": s[-1],
           "ema_trend": t[-1], "rsi": r[-1], "atr": a[-1]}
    crossed_up = f[-2] <= s[-2] and f[-1] > s[-1]
    crossed_down = f[-2] >= s[-2] and f[-1] < s[-1]
    if crossed_down:
        out.update(action="EXIT", reasons=["fast EMA crossed below slow EMA: the up-move is over"])
        return out
    if not crossed_up:
        out.update(action="NONE", reasons=["no fresh EMA crossover on the last closed bar"])
        return out
    why, ok = ["fast EMA %.4g crossed above slow EMA %.4g" % (f[-1], s[-1])], True
    if closes[-1] <= t[-1]:
        ok = False
        why.append("but price is under the 50-bar EMA: the bigger trend is down")
    if not (cfg["rsi_min"] <= r[-1] <= cfg["rsi_max"]):
        ok = False
        why.append("but RSI %.0f is outside %g-%g" % (r[-1], cfg["rsi_min"], cfg["rsi_max"]))
    else:
        why.append("RSI %.0f shows momentum without being overheated" % r[-1])
    if not a[-1]:
        ok = False
        why.append("but ATR is zero: no movement to size a stop from")
    out.update(action="BUY" if ok else "NONE", reasons=why)
    return out
