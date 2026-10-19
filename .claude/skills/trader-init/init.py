#!/usr/bin/env python3
"""First-run setup for trader-init. Standard library only.

Creates the trader/ folder every other skill reads, without touching
anything that already exists (unless --force):

  trader/config.json         risk and budget limits (paper trading, no options/margin/shorts)
  trader/accounts.json       your accounts, their strategies, the target mix, watchlists
  trader/accounts/<id>.json  an empty holdings file per account
  trader/paper/config.json   the paper bot's stock universe
  trader/team/config.json    the crypto bot team's rules (simulated money by default)

    python3 init.py
    python3 init.py --sec-user-agent "Your Name you@example.com" --mix growth=50,medium=20,dividend=30 --with-medium
    python3 init.py --questrade-type RRSP --wealthsimple-type TFSA
    python3 init.py --demo          # sample holdings so the dashboard has something to show
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "trader-paper"))
import paper  # noqa: E402

# Starter ideas for each account's watchlist: names to SCORE, not recommendations.
WATCH = {
    "growth": ["NVDA", "MSFT", "AMZN", "META", "GOOGL", "AVGO", "CRWD", "NOW"],
    "medium": ["COST", "LLY", "V", "BRK-B", "SHOP.TO", "CSU.TO", "XEQT.TO"],
    "dividend": ["RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "ENB.TO", "FTS.TO", "EMA.TO", "CNR.TO", "T.TO", "XEI.TO"],
}
DEMO = {
    "questrade": {"cash": {"USD": 650.0, "CAD": 40.0}, "positions": [
        {"ticker": "NVDA", "shares": 25, "avg_cost": 95.0, "currency": "USD"},
        {"ticker": "MSFT", "shares": 6, "avg_cost": 380.0, "currency": "USD"},
        {"ticker": "AMZN", "shares": 12, "avg_cost": 175.0, "currency": "USD"},
        {"ticker": "AMD", "shares": 15, "avg_cost": 165.0, "currency": "USD"},
        {"ticker": "PLTR", "shares": 30, "avg_cost": 40.0, "currency": "USD"}]},
    "wealthsimple": {"cash": {"CAD": 420.0}, "positions": [
        {"ticker": "ENB.TO", "shares": 40, "avg_cost": 52.0, "currency": "CAD"},
        {"ticker": "RY.TO", "shares": 10, "avg_cost": 150.0, "currency": "CAD"},
        {"ticker": "FTS.TO", "shares": 20, "avg_cost": 58.0, "currency": "CAD"},
        {"ticker": "BCE.TO", "shares": 30, "avg_cost": 45.0, "currency": "CAD"},
        {"ticker": "XEI.TO", "shares": 50, "avg_cost": 24.0, "currency": "CAD"}]},
}


def parse_mix(text):
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            k, _, v = part.partition("=")
            out[k.strip()] = float(v)
    return out


def build(a):
    accts = [
        {"id": "questrade", "name": "Questrade (growth)", "broker": "questrade", "type": a.questrade_type,
         "strategy": "growth", "fractional": False, "questrade_account_number": "", "watchlist": WATCH["growth"],
         "rules": {}, "targets": {}},
        {"id": "wealthsimple", "name": "Wealthsimple (dividend)", "broker": "wealthsimple",
         "type": a.wealthsimple_type, "strategy": "dividend", "fractional": True, "watchlist": WATCH["dividend"],
         "rules": {}, "targets": {}},
    ]
    mix = parse_mix(a.mix) if a.mix else {"growth": 60, "dividend": 40}
    if a.with_medium:
        accts.insert(1, {"id": "medium", "name": "Medium term", "broker": "questrade", "type": a.medium_type,
                         "strategy": "medium", "fractional": False, "questrade_account_number": "",
                         "watchlist": WATCH["medium"], "rules": {}, "targets": {}})
        if not a.mix:
            mix = {"growth": 45, "medium": 20, "dividend": 35}
    return {
        "_help": "Edit freely. strategy: growth | medium | dividend. rules override the strategy defaults "
                 "(see the README's strategy table). targets: optional {TICKER: percent}. "
                 "mix: the share of your money you want in each strategy.",
        "base_currency": "CAD", "mix": mix, "accounts": accts,
    }


def risk_config(ua):
    return {"budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000,
            "min_order_usd": 5, "max_orders_per_day": 10, "fractional": True, "broker": "alpaca", "paper": True,
            "blocked": [], "allow_options": False, "allow_margin": False, "allow_short": False,
            "sec_user_agent": ua or "Your Name you@example.com"}


def write(path, doc, force, made):
    if os.path.exists(path) and not force:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    made.append(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create the trader/ folder with sensible defaults.")
    ap.add_argument("--dir", default="trader")
    ap.add_argument("--sec-user-agent", default=os.environ.get("SEC_USER_AGENT", ""))
    ap.add_argument("--mix", help="e.g. growth=60,dividend=40 or growth=50,medium=20,dividend=30")
    ap.add_argument("--questrade-type", default="TFSA")
    ap.add_argument("--wealthsimple-type", default="TFSA")
    ap.add_argument("--with-medium", action="store_true", help="add a medium-term account")
    ap.add_argument("--medium-type", default="Margin")
    ap.add_argument("--demo", action="store_true", help="fill sample holdings (overwrites holdings files)")
    ap.add_argument("--force", action="store_true", help="overwrite existing config files")
    a = ap.parse_args(argv)
    if a.mix:
        bad = set(parse_mix(a.mix)) - {"growth", "medium", "dividend"}
        if bad:
            ap.error("unknown strategy in --mix: %s" % ", ".join(sorted(bad)))
    made = []
    cfg = build(a)
    write(os.path.join(a.dir, "config.json"), risk_config(a.sec_user_agent), a.force, made)
    write(os.path.join(a.dir, "accounts.json"), cfg, a.force, made)
    with open(os.path.join(a.dir, "accounts.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    for acct in cfg["accounts"]:
        h = {"account": acct["id"], "source": "manual", "as_of": None, "cash": {}, "positions": []}
        if a.demo and acct["id"] in DEMO:
            h.update(DEMO[acct["id"]], source="demo")
        write(os.path.join(a.dir, "accounts", acct["id"] + ".json"), h, a.force or a.demo, made)
    write(os.path.join(a.dir, "paper", "config.json"), {"universe": paper.UNIVERSE}, a.force, made)
    with open(os.path.join(SKILLS, "trader-team", "config.example.json"), encoding="utf-8") as fh:
        write(os.path.join(a.dir, "team", "config.json"), json.load(fh), a.force, made)
    for p in made:
        print("wrote " + p)
    if not made:
        print("trader/ is already set up (use --force to start over)")
    print("next: import or sync your holdings (see /trader-accounts), then run the daily briefing or the dashboard")
    if not a.sec_user_agent:
        print("tip: set SEC_USER_AGENT=\"Your Name you@example.com\" (or sec_user_agent in %s) for SEC filings"
              % os.path.join(a.dir, "config.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
