"""The Scanner: looks at every coin each cycle and picks the ones worth a closer look.

It does two jobs:
  1. data checks: enough closed bars, the last one is recent, the price moved
     at all, there was volume. A coin with bad data is skipped, with the reason.
  2. setups: a coin whose fast EMA is crossing (or about to cross) its slow EMA
     goes to the Analyst. Coins you already hold always go to the Analyst too,
     so it can call an exit.
"""

from analyst import ema


def scan(bars_by, cfg, now, held=()):
    setups, skipped = [], []
    stale = 2 * cfg["interval_min"] * 60
    for coin in cfg["coins"]:
        bars = bars_by.get(coin) or []
        if len(bars) < cfg["ema_trend"] + 2:
            skipped.append({"coin": coin, "reason": "not enough history (%d bars)" % len(bars)})
            continue
        last = bars[-1]
        if now - (last["t"] + cfg["interval_min"] * 60) > stale:
            skipped.append({"coin": coin, "reason": "last closed bar is stale"})
            continue
        if max(b["h"] for b in bars[-8:]) == min(b["l"] for b in bars[-8:]):
            skipped.append({"coin": coin, "reason": "price has not moved (market closed or bad data)"})
            continue
        if coin in held:
            setups.append({"coin": coin, "why": "held: check for an exit"})
            continue
        if sum(b["v"] for b in bars[-4:]) <= 0:
            skipped.append({"coin": coin, "reason": "no volume in the last hour"})
            continue
        closes = [b["c"] for b in bars]
        f, s = ema(closes, cfg["ema_fast"]), ema(closes, cfg["ema_slow"])
        gap_now, gap_before = f[-1] - s[-1], f[-2] - s[-2]
        if gap_before <= 0 < gap_now:
            setups.append({"coin": coin, "why": "fast EMA just crossed above slow EMA"})
        elif gap_now <= 0 and gap_now > gap_before and abs(gap_now) < 0.002 * closes[-1]:
            skipped.append({"coin": coin, "reason": "close to a crossover, watching"})
    return setups, skipped
