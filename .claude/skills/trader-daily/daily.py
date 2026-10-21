#!/usr/bin/env python3
"""The daily run for trader-daily. Standard library only.

One command, once a day (best after the 4 p.m. ET close):

  1. sync      Questrade positions (read-only API), if a token is saved
  2. market    prices, dividends and USD/CAD for every holding and watchlist name
  3. review    each account against its strategy -> trader/proposals.json
  4. history   today's total -> trader/history.json (the dashboard chart)
  5. paper     the ATR paper bot catches up and trades on paper
  6. news      new headlines (and 8-Ks, with an SEC user agent) on what you hold
  7. congress  new House stock-trade disclosures (PTRs)
  8. alerts    your price alerts, if trader/alerts.json exists

    python3 daily.py                 # everything, writes trader/briefing.json and briefing.md
    python3 daily.py --skip news congress
    python3 daily.py --offline DIR   # market + paper from saved charts, no network steps

A step that fails is reported in the briefing and the run carries on.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "trader-accounts"))
sys.path.insert(0, os.path.join(SKILLS, "trader-paper"))
sys.path.insert(0, os.path.join(SKILLS, "trader-team"))
import accounts as acc  # noqa: E402
import paper  # noqa: E402
import team  # noqa: E402

STEPS = ["sync", "market", "review", "history", "paper", "news", "congress", "alerts", "discover", "forward"]
NETWORK_ONLY = {"sync", "news", "congress", "alerts", "discover", "forward"}
IDEA_SOURCES = "trending,screens,news,fool,reddit"
# The live paper record is computed on GitHub every weekday (it needs the SEC and Congress data kept
# there); the briefing reads the published copy. "record_url" in trader/config.json overrides it.
RECORD_URL = "https://raw.githubusercontent.com/Keneisha3/public-stock-trade-tracker/replay-results/forward/record.json"
NOTES = {"(chosen)": "The main plan (C7): stocks in the top 5 holdings of at least 3 of the copycat's 23 investors, "
                     "from their latest 13F reports. It beat the S&P 500 from 2000 to 2017 (+7 pts a year) and in "
                     "training, but part of that edge came from choosing famous investors, and the live record has "
                     "to confirm it. An option, not an order: nothing is placed for you.",
         "(C4": "Stocks in the top 10 of at least 3 of the copycat's 23 investors, from their latest 13F reports. It "
                "beat the Nasdaq 100 in training and the S&P 500 in 22 of 28 windows, trailed in the held-out year, "
                "and is concentrated in a few large companies. An option, not an order."}


def _tool(folder, script, args, timeout=180):
    """Run another skill's script; return (parsed JSON or None, error text or None)."""
    cmd = [sys.executable, os.path.join(SKILLS, folder, script)] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "%s timed out" % script
    out = p.stdout.strip()
    if not out:
        return None, (p.stderr.strip() or "%s printed nothing" % script)[:400]
    try:
        return json.loads(out), None
    except ValueError:
        return None, out[:400]


def tested_plan(review, rec, marker="(chosen)"):
    """For each growth account: what a strategy of the live record (the one whose name contains
    `marker`: "(chosen)" for the plan, "(C4" for copycat consensus) would hold today, in the
    account's money, beside what it holds now."""
    if not rec:
        return []
    name = next((k for k in (rec.get("plan") or {}).get("strategies", {}) if marker in k), None)
    targets = (rec.get("targets") or {}).get(name) if name else None
    if not targets:
        return []
    out = []
    for a in review.get("accounts", []):
        if a.get("strategy") != "growth" or not a.get("total"):
            continue
        held = {p["ticker"]: p["value_base"] for p in a.get("positions", [])}
        rows = [{"ticker": t, "target_pct": round(100 * w, 1), "target": round(a["total"] * w, 2),
                 "now": round(held.get(t, 0.0), 2), "change": round(a["total"] * w - held.get(t, 0.0), 2)}
                for t, w in sorted(targets.items(), key=lambda kv: -kv[1])]
        out.append({"account": a["name"], "plan": name, "total": a["total"], "rows": rows, "note": NOTES.get(marker, ""),
                    "outside_plan": round(sum(v for t, v in held.items() if t not in targets), 2),
                    "as_of": rec.get("updated")})
    return out


def picks_change(state_path, rec, marker="(C4"):
    """{"added", "removed", "as_of"} when a strategy's picks differ from the last briefing's (new 13F
    reports change C4 a few times a year), else None. Remembers today's picks in `state_path`."""
    name = next((k for k in ((rec or {}).get("plan") or {}).get("strategies", {}) if marker in k), None)
    now = sorted(((rec or {}).get("targets") or {}).get(name) or {}) if name else []
    if not now:
        return None
    before = acc.read_json(state_path, None)
    acc.write_json(state_path, {"tickers": now, "as_of": rec.get("updated")})
    if not before or before.get("tickers") == now:
        return None
    old = set(before.get("tickers") or [])
    return {"added": [t for t in now if t not in old], "removed": sorted(old - set(now)), "as_of": rec.get("updated")}


def run(base="trader", skip=(), offline=None, today=None):
    paths = acc.Paths(base)
    cfg = acc.load_config(paths.config)
    brief = {"date": today or datetime.date.today().isoformat(), "generated": acc._now(), "steps": {}}
    log = brief["steps"]
    skip = set(skip) | (NETWORK_ONLY if offline else set())

    def did(step, ok, detail=""):
        log[step] = {"ok": ok, "detail": detail}

    if "sync" not in skip:
        for a in [x for x in cfg["accounts"] if x.get("broker") == "questrade"]:
            if not (os.path.exists(paths.token(a["id"])) or os.environ.get("QUESTRADE_REFRESH_TOKEN")):
                did("sync", True, "no Questrade token saved: using the last imported holdings")
                continue
            try:
                doc = acc.sync_questrade(a, paths)
                acc.write_json(paths.holdings(a["id"]), doc)
                did("sync", True, "%s: %d positions" % (a["id"], len(doc["positions"])))
            except acc.AccountsError as e:
                did("sync", False, str(e))
    if "market" not in skip:
        syms = acc.all_symbols(cfg, paths)
        if syms:
            res = acc.mk.refresh(syms, offline=offline, today=today)
            res["as_of"] = acc._now()
            old = acc.read_json(paths.market, {}) or {}
            merged = dict(old.get("symbols", {}))
            merged.update(res["symbols"])
            res["symbols"] = merged
            res["fx"] = res["fx"] or old.get("fx", {})
            acc.write_json(paths.market, res)
            did("market", not res["errors"] or bool(res["symbols"]),
                "%d symbols%s" % (len(res["symbols"]), ("; " + "; ".join(res["errors"][:3])) if res["errors"] else ""))
        else:
            did("market", True, "no holdings yet")
    if "market" not in skip:
        try:  # the VIX agent's read: fear gauge level, regime, and what it would do today
            import vix
            brief["vix"] = vix.status(acc.mk.get_chart("^VIX", offline=offline, range_="6mo")["bars"])
        except acc.mk.MarketError as e:
            did("vix", False, str(e)) if not offline else None
    market = acc.read_json(paths.market, {"symbols": {}, "fx": {}})
    review = acc.review_all(cfg, paths, market)
    if "review" not in skip:
        acc.write_json(paths.proposals, review)
        did("review", True, "%d to-dos" % len(review["todo"]))
    brief["portfolio"] = {k: review[k] for k in ("total", "day_change", "day_pct", "income", "income_net", "mix",
                                                 "todo", "base_currency")}
    brief["proposals"] = [dict(o, account=r["name"]) for r in review["accounts"] for o in r["proposals"]]
    if "history" not in skip and review["total"]:
        acc.snapshot(paths.history, review, today)
        did("history", True, "recorded %s" % acc.money(review["total"]))
    if "paper" not in skip:
        try:
            ppath = os.path.join(base, "paper", "ledger.json")
            led, errors = paper.run_live(ppath, paper.universe(os.path.join(base, "paper", "config.json")),
                                         offline=offline, today=today)
            s = paper.summary(led)
            brief["paper"] = {k: s[k] for k in ("equity", "start_cash", "regime", "stats", "buy_hold", "pending")}
            did("paper", True, "equity %.2f, %d open, regime %s" % (s["equity"], len(s["positions"]), s["regime"]))
        except (paper.PaperError, acc.mk.MarketError) as e:
            did("paper", False, str(e))
    held = sorted({p["ticker"] for r in review["accounts"] for p in r["positions"]})
    if "news" not in skip and held:
        doc, err = _tool("trader-news", "news.py", ["--tickers"] + held + [
            "--hours", "36", "--json", "--state", os.path.join(base, "state", "news.json"),
            "--config", os.path.join(base, "config.json")])
        items = (doc or {}).get("items", [])
        brief["news"] = [{k: i.get(k) for k in ("ticker", "title", "link", "source", "time", "tags", "kind")}
                         for i in items if i.get("new", True)][:25]
        did("news", doc is not None, err or "%d new items" % len(brief["news"]))
    if "congress" not in skip:
        us = [t for t in held if "." not in t]
        doc, err = _tool("trader-pelosi", "ptr.py", ["new", "--json", "--state",
                                                    os.path.join(base, "state", "pelosi.json"),
                                                    "--portfolio", os.path.join(base, "portfolio.json")]
                         + (["--tickers"] + us if us else []))
        fresh = (doc or {}).get("new", [])
        brief["congress"] = [{k: r.get(k) for k in ("name", "district", "filed", "url", "type_name")}
                             for r in fresh][:15]
        did("congress", doc is not None, err or "%d new filings" % len(fresh))
    if "discover" not in skip:  # today's idea lists, archived, then ranked (leads, not advice)
        snap, err = _tool("trader-discover", "discover.py", ["--dir", base, "snapshot", "--only", IDEA_SOURCES, "--json"],
                          timeout=300)
        doc, err2 = _tool("trader-discover", "discover.py", ["--dir", base, "funnel", "--json", "--top", "15"],
                          timeout=600) if snap else (None, err)
        brief["ideas"] = (doc or {}).get("ideas", [])
        did("discover", doc is not None, err2 or "%d ideas from %d candidates" % (len(brief["ideas"]),
                                                                              (doc or {}).get("candidates", 0)))
    rec_path = os.path.join(base, "forward", "record.json")
    if "forward" not in skip:  # the live paper record, as published by the weekday GitHub run
        err = None
        try:
            rec = json.loads(acc.mk.fetch(acc.read_json(paths.config, {}).get("record_url") or RECORD_URL))
            if not isinstance(rec, dict) or "days" not in rec:
                raise ValueError("not a live record")
            acc.write_json(rec_path, rec)
        except (acc.mk.MarketError, ValueError) as e:
            err = "could not fetch the live record (%s): using the last copy" % e
        rec = acc.read_json(rec_path, None)
        if rec and rec.get("days"):
            last = rec["days"][max(rec["days"])]
            brief["forward"] = {"start": rec["start"], "updated": rec.get("updated"), "values": last,
                                "days": len(rec["days"]), "cash": rec["plan"].get("cash", 100)}
        did("forward", err is None, err or "%d days on the record" % len((rec or {}).get("days", {})))
    rec = acc.read_json(rec_path, None)
    brief["plan"] = tested_plan(review, rec)
    brief["c4"] = tested_plan(review, rec, "(C4")
    brief["c4_change"] = picks_change(os.path.join(base, "state", "c4.json"), rec)
    rules = os.path.join(base, "alerts.json")
    if "alerts" not in skip and os.path.exists(rules):
        doc, err = _tool("trader-alerts", "alerts.py", ["check", "--json", "--rules", rules,
                                                       "--state", os.path.join(base, "state", "alerts.json"),
                                                       "--prices-out", os.path.join(base, "prices.json")])
        brief["alerts"] = (doc or {}).get("rings", []) if isinstance(doc, dict) else []
        did("alerts", doc is not None, err or "%d rang" % len(brief["alerts"]))
    tdir = os.path.join(base, "team")
    if os.path.exists(os.path.join(tdir, "state.json")):
        s = team.trade_log.summary(tdir)
        brief["crypto_team"] = {"summary": s, "kill": team.read_kill(team.Paths(tdir))}
    acc.write_json(os.path.join(base, "briefing.json"), brief)
    with open(os.path.join(base, "briefing.md"), "w", encoding="utf-8") as fh:
        fh.write(render(brief))
    return brief


def render(b):
    p = b.get("portfolio", {})
    L = ["# Daily briefing, %s" % b["date"], ""]
    if p.get("total"):
        L.append("**Portfolio %s %s**, today %s (%+.2f%%). Dividends about %s a month after US withholding." % (
            acc.money(p["total"]), p["base_currency"], acc.money(p["day_change"]), p["day_pct"],
            acc.money(p["income_net"] / 12)))
        if p.get("mix"):
            L.append("Mix: " + ", ".join("%s %.0f%%%s" % (m["label"], m["pct"], (" of %.0f%% target" % m["target_pct"])
                                                         if m["target_pct"] is not None else "") for m in p["mix"]))
        L.append("")
    ch = b.get("c4_change")
    if ch:
        L.append("**Copycat consensus (C4) changed** (new 13F reports, as of %s): %s%s. See the C4 section below." % (
            ch["as_of"], ("added " + ", ".join(ch["added"])) if ch["added"] else "",
            ("; removed " + ", ".join(ch["removed"])) if ch["removed"] else ""))
        L.append("")
    v = b.get("vix")
    if v:
        L.append("**VIX %.1f** (%s, %s today; 50-day average %.1f). The VIX agent says: %s (%s)." % (
            v["level"], v["regime"], ("%+.1f%%" % v["day_change_pct"]) if v.get("day_change_pct") is not None else "n/a",
            v["avg_50d"], v["agent"], v["reason"]))
        L.append("")
    if p.get("todo"):
        L.append("## To do")
        for t in p["todo"]:
            L.append("- %s%s: %s" % (t["account"], (" " + t["ticker"]) if t["ticker"] else "", t["text"]))
        L.append("")
    if b.get("proposals"):
        L.append("## Proposed trades (you place them, only if you agree)")
        for o in b["proposals"]:
            L.append("- %s: %s %s %s (~%s %s): %s" % (o["account"], o["side"].upper(), o["shares"], o["ticker"],
                                                       acc.money(o["value"]), o["currency"], o["reason"]))
        L.append("")
    if b.get("paper"):
        pp = b["paper"]
        st = pp.get("stats") or {}
        L.append("## Paper bot")
        L.append("Equity %.2f from %.2f (%s), regime %s. Buy-and-hold over the same days: %s." % (
            pp["equity"], pp["start_cash"], ("%+.2f%%" % st["total_pct"]) if st else "first day",
            pp["regime"], ("%+.2f%%" % pp["buy_hold"]["total_pct"]) if pp.get("buy_hold") else "n/a"))
        for o in pp.get("pending", []):
            L.append("- buys %s at the next open (%.1f ATR up-move)" % (o["ticker"], o["move_atr"]))
        L.append("")
    if b.get("crypto_team"):
        L.append("## Crypto bot team (paper)")
        if b["crypto_team"].get("kill"):
            L.append("Kill switch ON: %s" % b["crypto_team"]["kill"]["reason"])
        L.append(team.trade_log.render(b["crypto_team"]["summary"]).split("\n", 1)[1])
        L.append("")
    if b.get("news"):
        L.append("## News on your holdings")
        for n in b["news"]:
            L.append("- **%s** [%s](%s)" % (n["ticker"], n["title"], n["link"]))
        L.append("")
    if b.get("congress"):
        L.append("## New Congress stock-trade filings")
        for c in b["congress"]:
            L.append("- %s (%s) filed %s: %s" % (c["name"], c["district"], c["filed"], c["url"]))
        L.append("")
    for p in (b.get("plan") or []) + (b.get("c4") or []):
        L.append("## %s for %s (targets as of %s)" % (p["plan"], p["account"], p["as_of"]))
        for r in p["rows"]:
            L.append("- %s %.0f%%: %s (now %s, %s %s)" % (r["ticker"], r["target_pct"], acc.money(r["target"]),
                                                        acc.money(r["now"]), "buy" if r["change"] > 0 else "sell",
                                                        acc.money(abs(r["change"]))))
        if p["outside_plan"]:
            L.append("- In holdings outside the plan: %s" % acc.money(p["outside_plan"]))
        L.append("- " + (p.get("note") or "An option, not an order. Nothing is placed for you."))
        L.append("")
    if b.get("forward"):
        f = b["forward"]
        L.append("## Live paper record (since %s, %d trading days, $%g each)" % (f["start"], f["days"], f["cash"]))
        for name, v in f["values"].items():
            if v is not None:
                L.append("- %s: $%.2f (%+.1f%%)" % (name, v, 100.0 * (v / f["cash"] - 1)))
        L.append("")
    if b.get("ideas"):
        L.append("## Ideas from the market (leads to research, not advice)")
        for i in b["ideas"]:
            L.append("- %s %s: %+.0f%% over 12 months (last month left out), from %s" % (
                i["symbol"], (i.get("name") or "")[:30], i["momentum_12_1"], ", ".join(i["sources"])))
        L.append("")
    bad = {k: v for k, v in b["steps"].items() if not v["ok"]}
    if bad:
        L.append("## Steps that need attention")
        for k, v in bad.items():
            L.append("- %s: %s" % (k, v["detail"]))
        L.append("")
    L.append("_Not financial advice. Delayed public data; nothing here places a trade._")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="The daily run: sync, review, paper bot, news, Congress, alerts.")
    ap.add_argument("--dir", default="trader")
    ap.add_argument("--skip", nargs="*", default=[], choices=STEPS)
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--today")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        b = run(a.dir, a.skip, a.offline, a.today)
    except acc.AccountsError as e:
        print("daily: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(b, indent=2) if a.json else render(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
