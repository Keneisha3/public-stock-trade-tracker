"""The VIX agent: reads the market's fear gauge and decides risk-on or risk-off.

The VIX is the S&P 500's expected volatility over the next 30 days, as
priced by options (Yahoo symbol ^VIX). High VIX = fear. The agent is a plain rule,
like the crypto team's roles, and only ever looks at closes up to today:

  level   risk-on while the VIX closes at or under a threshold (default 25)
  trend   risk-on while the VIX closes at or under its own N-day average (default 50):
          fear is not rising

Risk-on means hold the S&P 500; risk-off means step aside to cash. The
decision is made at the close and acted on at the next open.
"""

REGIMES = ((15.0, "calm"), (20.0, "normal"), (30.0, "nervous"), (float("inf"), "fear"))
DEFAULT_RULE = {"mode": "level", "threshold": 25.0}


def regime(level):
    """calm (<15), normal (15-20), nervous (20-30), fear (30+)."""
    if level is None:
        return None
    for top, name in REGIMES:
        if level < top:
            return name
    return "fear"


def decide(closes, rule=None):
    """closes: VIX closes up to and including today, oldest first. -> (risk_on, reason)."""
    rule = dict(DEFAULT_RULE, **(rule or {}))
    if not closes:
        return True, "no VIX data: stay invested"
    now = closes[-1]
    if rule["mode"] == "trend":
        n = int(rule.get("days", 50))
        if len(closes) < n:
            return True, "not enough VIX history for a %d-day average: stay invested" % n
        avg = sum(closes[-n:]) / n
        on = now <= avg
        return on, "VIX %.1f is %s its %d-day average %.1f" % (now, "at or under" if on else "above", n, avg)
    t = float(rule.get("threshold", 25))
    on = now <= t
    return on, "VIX %.1f is %s %g" % (now, "at or under" if on else "above", t)


def status(bars, rule=None):
    """Today's read for the briefing: level, change, regime, 50-day average, what the agent says."""
    closes = [b["c"] for b in bars if b.get("c") is not None]
    if not closes:
        return None
    on, why = decide(closes, rule)
    avg = sum(closes[-50:]) / len(closes[-50:])
    prev = closes[-2] if len(closes) > 1 else None
    return {"level": round(closes[-1], 2), "day_change_pct": round(100 * (closes[-1] / prev - 1), 1) if prev else None,
            "regime": regime(closes[-1]), "avg_50d": round(avg, 2), "risk_on": on,
            "agent": "hold the S&P 500" if on else "step aside to cash", "reason": why,
            "date": bars[-1].get("d")}
