#!/usr/bin/env python3
"""What to buy: one ranked list from everything the project already produces.

    python3 picks.py --cash 1380 --account questrade      # rank, check, size for that account
    python3 picks.py --json

Candidates come from three places, each counted as one piece of evidence:
    - the tested plans on the live paper record: the main plan (chosen) and the copycat top 10 (C4)
    - near-consensus: stocks two of the 23 famous investors hold in their top 5 (the main plan needs three)
    - the whole-market scan (trader/discover/ideas.json, or the weekday GitHub run's copy): liquid, above
      the 200-day, ranked by momentum; only large companies (the S&P 500 and about 70 large Canadian
      ones) are used, so a wide scan cannot hand you a tiny stock that just ran 500 %
Each is checked against the rules the account review uses: above its 200-day average (the trend
test), not stretched (market.STRETCH_SIGNALS), not already held. Then ranked by evidence, then
12-month momentum, and sized: the cash split over the top names, no name over 10% of the account.

Only the main plan was tested walk-forward; the ranking says how much the project's evidence agrees,
not what will go up. Not financial advice: you place every order yourself.
"""

import argparse
import datetime as dt
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trader-accounts"))
sys.path.insert(0, HERE)
import market as mk  # noqa: E402
import signals as sigs  # noqa: E402

RAW = "https://raw.githubusercontent.com/Keneisha3/public-stock-trade-tracker/replay-results/"
RECORD_URL = RAW + "forward/record.json"
IDEAS_URL = RAW + "discover/latest-ideas.json"  # the weekday whole-market scan (about 9,500 stocks)
IDEAS_TOP = 20
F13_URL = RAW + "signals/f13.json.gz"
PLANS = {"(chosen)": "main plan", "(C4": "copycat top 10 (C4)"}
MAX_WEIGHT = 0.10   # of the account, per new name
CURRENCY = {"questrade": "USD", "wealthsimple": "CAD"}  # buy in the account's own currency: no conversion fee


def currency_of(ticker):
    return "CAD" if ticker.upper().endswith((".TO", ".V", ".NE", ".CN")) else "USD"
TOP = 3


def from_plans(record):
    """{ticker: [reasons]} from the tested plans' current targets on the live record."""
    out = {}
    for name, weights in (record.get("targets") or {}).items():
        label = next((v for k, v in PLANS.items() if k in name), None)
        if label:
            for t in weights:
                out.setdefault(t, []).append(label)
    return out


def near_consensus(sig, day, n=5, k=2):
    """{ticker: [reason]} for stocks exactly `k` of the famous investors hold in their top `n`."""
    count = {}
    for cik in sig.f13:
        h = sig.holdings_13f(cik, day)
        for t, _ in sorted((h or {}).items(), key=lambda kv: -kv[1][0])[:n]:
            count.setdefault(t, []).append(sig.managers.get(cik, cik))
    return {t: ["top 5 of 2 famous investors (%s)" % ", ".join(m.split(" (")[0] for m in who)]
            for t, who in count.items() if len(who) == k}


def from_ideas(ideas, large=None, top=IDEAS_TOP):
    """{ticker: [reason]} for the scan's momentum leaders among large companies: the scan's full ranking of
    the S&P 500 and large Canadian companies when it has one ("large"), else its top movers filtered to
    `large`."""
    rows = (ideas or {}).get("large")
    if rows is None:
        rows = [r for r in (ideas or {}).get("ideas", []) if large is None or r.get("symbol") in large]
    return {r["symbol"]: ["large-company momentum leader (market scan)"] for r in rows[:top] if r.get("symbol")}


def from_dip(get_metrics, rule, spy_off, giants=mk.GIANTS):
    """{ticker: [reason]} for the giants the dip rule fires on today. Nothing is fetched unless the
    S&P 500 is already down enough for the rule."""
    if not rule or spy_off is None or spy_off > -rule["market_off"]:
        return {}
    return {t: ["a giant on sale by the dip rule"] for t in giants if mk.dip_rule_fires(get_metrics(t), spy_off, rule)}


def merge(*sources):
    out = {}
    for src in sources:
        for t, why in src.items():
            out.setdefault(t, []).extend(why)
    return out


def assess(t, why, metrics, rule=None, spy_off=None):
    """One candidate against the rules: {"ticker", "why", "evidence", "ok", "notes", "dip", ...metrics}.
    A stock below its 200-day average waits, unless the dip rule (market.load_dip_rule) fires and earned
    "buy" on its held-out years: then the crash-buying evidence overrides the trend test."""
    m = metrics or {}
    notes = []
    dip = bool(m) and rule is not None and mk.dip_rule_fires(m, spy_off, rule)
    dip_buy = dip and rule.get("verdict") == "buy"
    if not m:
        notes.append("no price data")
    elif not m.get("above_sma200"):
        if dip_buy:
            notes.append("on sale by the dip rule (%s; %s): a buy even below its 200-day average"
                         % (mk.describe_dip_rule(rule), rule.get("source", "")))
        else:
            notes.append("below its 200-day average: the trend test says wait")
    if dip and not dip_buy:
        notes.append("meets %s (%s), which has not earned a buy: information only"
                     % (rule.get("source", "the dip rule"), mk.describe_dip_rule(rule)))
    fired = mk.stretch_signals(m.get("stretch") or {})
    if fired:
        notes.append("stretched (%s): fine to own, consider a smaller first buy" % ", ".join(fired))
    ok = bool(m) and (bool(m.get("above_sma200")) or dip_buy)
    return {"ticker": t, "why": why, "evidence": len(why), "ok": ok, "notes": notes, "dip": dip,
            "price": m.get("price"), "ret_12m": m.get("ret_12m"), "off_high_pct": m.get("off_high_pct"),
            "vol_pct": m.get("vol_pct")}


def rank(rows):
    return sorted(rows, key=lambda r: (not r["ok"], -r["evidence"], -(r["ret_12m"] or -1e9)))


def size(rows, cash, account_total, top=TOP, cap=MAX_WEIGHT):
    """Split `cash` over the top `top` passing names, none over `cap` of the account after buying."""
    buy = [r for r in rows if r["ok"]][:top]
    if not buy or cash <= 0:
        return []
    each = min(cash / len(buy), cap * (account_total + cash))
    return [{"ticker": r["ticker"], "amount": round(each, 2),
             "shares": round(each / r["price"], 4) if r["price"] else None} for r in buy]


def held(base="trader"):
    out = set()
    folder = os.path.join(base, "accounts")
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                out |= {p["ticker"].upper() for p in json.load(fh).get("positions", [])}
        except (OSError, ValueError, KeyError):
            continue
    return out


def account_total(base, account):
    """The account's value from the last review (trader/proposals.json), in its own currency."""
    try:
        with open(os.path.join(base, "proposals.json"), encoding="utf-8") as fh:
            for a in json.load(fh).get("accounts", []):
                if a.get("id") == account or account.lower() in (a.get("name") or "").lower():
                    return a.get("total") or 0.0
    except (OSError, ValueError):
        pass
    return 0.0


def build(record, sig, ideas, exclude, get_metrics, day, large=None, currency=None, rule=None, spy_off=None):
    """Ranked candidates; `currency` keeps only those trading in it (USD or CAD), so the account can
    buy them without converting. `rule` and `spy_off` (the S&P 500's % below its high) apply the dip rule."""
    cands = merge(from_plans(record), near_consensus(sig, day) if sig else {}, from_ideas(ideas, large),
                  from_dip(get_metrics, rule, spy_off))
    rows = [assess(t, why, get_metrics(t), rule, spy_off) for t, why in cands.items()
            if t.upper() not in exclude and t != "SPY" and (currency is None or currency_of(t) == currency)]
    return rank(rows)


def render(rows, plan, rule=None):
    L = ["What to buy: candidates from the plans, the famous investors and the daily ideas, checked against your rules", ""]
    for i, r in enumerate(rows, 1):
        mark = "OK  " if r["ok"] else "WAIT"
        L.append("%2d. %s %-6s %s  12m %s  off high %s  | %s" % (
            i, mark, r["ticker"], ("$%.2f" % r["price"]) if r["price"] else "  n/a",
            ("%+.0f%%" % r["ret_12m"]) if r["ret_12m"] is not None else "n/a",
            ("%.0f%%" % r["off_high_pct"]) if r["off_high_pct"] is not None else "n/a", "; ".join(r["why"])))
        for n in r["notes"]:
            L.append("        - " + n)
    if plan:
        L += ["", "Sized for your cash (no new name over %d%% of the account):" % int(100 * MAX_WEIGHT)]
        L += ["  BUY %-6s about $%.2f (%s shares)" % (p["ticker"], p["amount"], p["shares"]) for p in plan]
    L += ["", "Dip rule in force: %s (%s)." % (mk.describe_dip_rule(rule), rule.get("source", "")) if rule else "",
          "Evidence = how many of the project's sources point at it. Only the main plan was tested walk-forward.",
          "Not financial advice: you place every order yourself."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="One ranked list of what to buy, checked against your rules.")
    ap.add_argument("--dir", default="trader")
    ap.add_argument("--cash", type=float, default=0.0, help="money to put to work")
    ap.add_argument("--account", default="questrade")
    ap.add_argument("--currency", choices=("USD", "CAD"), help="default: the account's (questrade USD, wealthsimple CAD)")
    ap.add_argument("--total", type=float, help="the account's value now, in the cash's currency (default: last review)")
    ap.add_argument("--exclude", nargs="*", default=[], help="more tickers to leave out (e.g. ones you just sold)")
    ap.add_argument("--offline", help="folder with record.json, f13.json.gz and chart-*.json (tests)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    day = dt.date.today().isoformat()
    if a.offline:
        with open(os.path.join(a.offline, "record.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        f13 = sigs.read(os.path.join(a.offline, "f13.json.gz"))
    else:
        record = json.loads(mk.fetch(RECORD_URL))
        try:
            import urllib.request
            with urllib.request.urlopen(F13_URL, timeout=60) as r:
                f13 = json.loads(gzip.decompress(r.read()).decode("utf-8"))
        except (OSError, ValueError):
            f13 = None
    try:
        with open(os.path.join(a.dir, "discover", "ideas.json"), encoding="utf-8") as fh:
            ideas = json.load(fh)
    except (OSError, ValueError):
        ideas = None
    if not (ideas or {}).get("ideas") and not a.offline:  # nothing local (or a cloud session): the GitHub copy
        try:
            ideas = json.loads(mk.fetch(IDEAS_URL))
        except (mk.MarketError, ValueError):
            ideas = None
    import universe
    large = set(universe.load().members_on(day)) | set(universe.CANADA)

    seen = {}

    def metrics(t):
        if t not in seen:
            try:
                seen[t] = mk.metrics(mk.get_chart(t, offline=a.offline, range_="2y"))
            except mk.MarketError:
                seen[t] = None
        return seen[t]
    exclude = held(a.dir) | {t.upper() for t in a.exclude}
    currency = a.currency or CURRENCY.get(a.account.lower())
    rule = mk.load_dip_rule()
    try:
        spy_off = mk.metrics(mk.get_chart("SPY", offline=a.offline, range_="5y")).get("off_peak_pct")
    except mk.MarketError:
        spy_off = None
    rows = build(record, sigs.Signals(f13=f13) if f13 else None, ideas, exclude, metrics, day, large, currency,
                 rule, spy_off)
    plan = size(rows, a.cash, a.total if a.total is not None else account_total(a.dir, a.account)) if a.cash else []
    print(json.dumps({"candidates": rows, "plan": plan}, indent=1) if a.json else render(rows, plan, rule))
    return 0


if __name__ == "__main__":
    sys.exit(main())
