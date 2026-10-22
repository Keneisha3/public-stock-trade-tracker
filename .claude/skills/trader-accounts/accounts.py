#!/usr/bin/env python3
"""Your real accounts (Questrade, Wealthsimple, any broker) for trader-accounts.
Standard library only.

Each account has a strategy, and is reviewed against that strategy's rules:

  growth     aggressive, US stocks welcome: momentum and trend, a stop from
             your cost, trims winners that outgrow the position cap
  medium     6 to 24 months: trend-following, sells the idea when the trend
             breaks, moderate caps
  dividend   steady income: yield in a sane band, growing dividends, no cuts,
             low volatility, projected monthly income (US withholding aware)

    python3 accounts.py market                         # refresh trader/market.json (prices, dividends, FX)
    python3 accounts.py review                         # every account, flags and proposals
    python3 accounts.py review --contribute 1000       # where the next $1,000 should go
    python3 accounts.py review --json --write          # trader/proposals.json for the dashboard
    python3 accounts.py import wealthsimple holdings.csv
    python3 accounts.py sync questrade                 # Questrade API (read-only), refresh token
    python3 accounts.py cash wealthsimple 250 --currency CAD
    python3 accounts.py snapshot                       # add today's value to trader/history.json

Files (all under trader/, which is git-ignored):
  accounts.json            your accounts, strategies, rules, target mix, watchlists
  accounts/<id>.json       holdings per account: cash by currency, positions
  market.json              metrics per symbol, USD/CAD
  history.json             one value per day, for the chart
  state/questrade-<id>.json  the rotating Questrade refresh token (mode 600)

Nothing here places a trade. Proposals are a to-do list you place yourself in
the Questrade or Wealthsimple app, after you agree with them.
"""

import argparse
import copy
import csv
import datetime
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market as mk  # noqa: E402  (sits next to this file)

RULES = {
    "growth": {  # "aggressive": 3-month momentum, 30% cap, fully invested (won both test periods)
        "max_position_pct": 30, "trim_band_pct": 5, "cash_target_pct": 0, "cash_max_pct": 10,
        "stop_loss_pct": 25, "drawdown_review_pct": 30, "laggard_12m_pct": -10,
        "keep_score": 45, "min_trade": 100, "min_positions": 4,
        "momentum_months": 3, "review_every_days": 7, "rotate": False, "sell_score": 40, "size_top": 0,
    },
    "medium": {
        "max_position_pct": 15, "trim_band_pct": 4, "cash_target_pct": 3, "cash_max_pct": 10,
        "stop_loss_pct": 20, "drawdown_review_pct": 25, "laggard_12m_pct": -5,
        "keep_score": 50, "min_trade": 100, "min_positions": 6,
        "momentum_months": 6, "review_every_days": 7,
    },
    "dividend": {
        "max_position_pct": 12, "trim_band_pct": 3, "cash_target_pct": 2, "cash_max_pct": 8,
        "stop_loss_pct": 30, "drawdown_review_pct": 25, "min_yield_pct": 2.0, "max_yield_pct": 8.0,
        "max_volatility_pct": 30, "cut_pct": 10, "keep_score": 50, "min_trade": 100, "min_positions": 8,
        "review_every_days": 7,
    },
}
# The rules a person can tune: (label, min, max, strategies). Everything else stays internal.
TUNABLE = {
    "momentum_months": ("Momentum lookback (months)", 1, 12, ("growth", "medium")),
    "max_position_pct": ("Max per stock (%)", 5, 50, ("growth", "medium", "dividend")),
    "min_positions": ("Aim for at least N holdings", 1, 30, ("growth", "medium", "dividend")),
    "stop_loss_pct": ("Stop-loss from your cost (%)", 5, 60, ("growth", "medium", "dividend")),
    "cash_target_pct": ("Cash to keep (%)", 0, 30, ("growth", "medium", "dividend")),
    "trim_band_pct": ("Trim when over the cap by (points)", 0, 20, ("growth", "medium", "dividend")),
    "review_every_days": ("Rebalance every N days", 1, 92, ("growth", "medium", "dividend")),
    "min_yield_pct": ("Minimum dividend yield (%)", 0, 10, ("dividend",)),
    "max_yield_pct": ("Yield-trap warning above (%)", 4, 20, ("dividend",)),
}
MOMENTUM_CHOICES = (1, 3, 6, 12)


def check_rules(strategy, rules):
    """Keep only known, in-range tunables. Raises AccountsError on a bad value."""
    out = {}
    for k, v in (rules or {}).items():
        if k not in TUNABLE or strategy not in TUNABLE[k][3]:
            raise AccountsError("%s is not a setting for a %s account" % (k, strategy))
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise AccountsError("%s must be a number" % k)
        lo, hi = TUNABLE[k][1], TUNABLE[k][2]
        if not lo <= v <= hi:
            raise AccountsError("%s must be between %g and %g" % (TUNABLE[k][0], lo, hi))
        if k == "momentum_months" and int(v) not in MOMENTUM_CHOICES:
            raise AccountsError("momentum lookback must be 1, 3, 6 or 12 months")
        out[k] = int(v) if k in ("momentum_months", "min_positions", "review_every_days") else v
    return out


STRATEGY_LABEL = {"growth": "Aggressive growth", "medium": "Medium term", "dividend": "Steady dividend"}
NO_US_WITHHOLDING = {"RRSP", "RRIF", "LIRA", "SPOUSAL RRSP"}  # Canada-US treaty exemption
TFSA_LIKE = {"TFSA", "FHSA", "RESP", "RDSP"}  # 15% US withholding, not recoverable
QT_LOGIN = "https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token=%s"


class AccountsError(Exception):
    pass


# ---------------------------------------------------------------- files

def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return copy.deepcopy(default)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise AccountsError("%s is not valid JSON: %s" % (path, e))


def write_json(path, doc, private=False):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Paths:
    def __init__(self, base="trader"):
        self.base = base
        self.config = os.path.join(base, "accounts.json")
        self.market = os.path.join(base, "market.json")
        self.history = os.path.join(base, "history.json")
        self.proposals = os.path.join(base, "proposals.json")

    def holdings(self, acct_id):
        return os.path.join(self.base, "accounts", "%s.json" % acct_id)

    def token(self, acct_id):
        return os.path.join(self.base, "state", "questrade-%s.json" % acct_id)


def load_config(path):
    cfg = read_json(path)
    if not cfg:
        raise AccountsError("no %s yet: run python3 trade.py init" % path)
    cfg.setdefault("base_currency", "CAD")
    cfg.setdefault("mix", {})
    for a in cfg.get("accounts", []):
        if not a.get("id"):
            raise AccountsError("every account in %s needs an id" % path)
        s = a.setdefault("strategy", "growth")
        if s not in RULES:
            raise AccountsError("account %s: strategy must be one of %s" % (a["id"], ", ".join(RULES)))
        rules = dict(RULES[s])
        rules.update(a.get("rules") or {})
        a["rules"] = rules
        a.setdefault("name", a["id"])
        a.setdefault("type", "TFSA")
        a.setdefault("fractional", a.get("broker") == "wealthsimple")
    return cfg


def account(cfg, acct_id):
    for a in cfg.get("accounts", []):
        if a["id"] == acct_id:
            return a
    raise AccountsError("no account %r in accounts.json (have: %s)" % (
        acct_id, ", ".join(a["id"] for a in cfg.get("accounts", []))))


def empty_holdings(acct_id):
    return {"account": acct_id, "source": "manual", "as_of": None, "cash": {}, "positions": []}


# ---------------------------------------------------------------- CSV import

ALIASES = {
    "symbol": ["symbol", "ticker", "security symbol", "stock symbol", "code"],
    "exchange": ["exchange", "listing exchange", "mic", "market"],
    "quantity": ["quantity", "qty", "shares", "open quantity", "units", "position"],
    "avg_cost": ["average cost", "avg cost", "average entry price", "average price", "avg price",
                 "cost per share", "book cost per share", "acb per share"],
    "book_value": ["book value (market)", "book value", "total cost", "book cost", "cost basis",
                   "book value (cad)", "acb"],
    "book_ccy": ["book value currency (market)", "book value currency"],
    "price": ["market price", "current price", "price", "last price", "last"],
    "currency": ["market price currency", "currency", "market value currency", "price currency"],
    "name": ["name", "description", "security name", "security"],
    "type": ["security type", "asset type", "type"],
    "acct_name": ["account name", "account type", "account"],
    "acct_number": ["account number", "account #", "account no"],
}


def _norm(h):
    return re.sub(r"\s+", " ", str(h or "").replace("﻿", "").strip().lower())


def _num(v):
    s = str(v or "").strip().replace("$", "").replace(",", "").replace("CAD", "").replace("USD", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _columns(header):
    cols = {}
    normed = [_norm(h) for h in header]
    for key, names in ALIASES.items():
        for n in names:  # first alias wins, so the order above is the preference
            if n in normed:
                cols[key] = normed.index(n)
                break
    return cols


def parse_holdings_csv(text, acct_id, filter_text=None):
    """A holdings export (Wealthsimple, Questrade, most brokers) -> holdings doc.

    Finds the header row by itself, reads symbol + quantity (+ exchange, cost,
    currency, name), skips cash and totals rows, merges duplicate symbols.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    start, cols = None, None
    for i, r in enumerate(rows[:30]):
        c = _columns(r)
        if "symbol" in c and "quantity" in c:
            start, cols = i, c
            break
    if start is None:
        raise AccountsError("could not find a header row with a symbol and a quantity column")
    want = (filter_text or "").lower()
    merged, skipped = {}, 0
    for r in rows[start + 1:]:
        if not any(x.strip() for x in r):
            continue

        def get(k):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        if want and want not in (get("acct_name") + " " + get("acct_number")).lower():
            continue
        sym, qty = get("symbol"), _num(get("quantity"))
        kind = get("type").lower()
        if not sym or qty is None or qty == 0 or "cash" in kind or sym.upper() in ("CASH", "TOTAL"):
            skipped += 1
            continue
        if qty < 0:
            raise AccountsError("%s has a short position (%s): this tool only tracks long holdings" % (sym, qty))
        ticker = mk.yahoo_symbol(sym, get("exchange"))
        ccy = (get("currency") or get("book_ccy") or mk.native_currency(ticker)).upper()[:3]
        avg = _num(get("avg_cost"))
        book = _num(get("book_value"))
        cost = avg * qty if avg is not None else book
        p = merged.setdefault(ticker, {"ticker": ticker, "broker_symbol": sym, "name": get("name"),
                                       "shares": 0.0, "cost": 0.0, "currency": ccy, "last_price": None})
        p["shares"] += qty
        p["cost"] += cost or 0.0
        price = _num(get("price"))
        if price:
            p["last_price"] = price
    positions = []
    for p in merged.values():
        p["avg_cost"] = round(p["cost"] / p["shares"], 4) if p["cost"] else None
        p["shares"] = round(p["shares"], 6)
        del p["cost"]
        positions.append(p)
    if not positions:
        raise AccountsError("no holdings found in the file%s" % (" for %r" % filter_text if filter_text else ""))
    return {"account": acct_id, "source": "csv", "as_of": _today(), "positions": positions,
            "skipped_rows": skipped}


# ---------------------------------------------------------------- Questrade (read-only API)

def _http_json(url, token=None, timeout=25):
    headers = {"User-Agent": mk.UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            raise AccountsError("Questrade refused the token (HTTP %d). Make a new one: Questrade web > "
                                "App Hub > Personal apps > Generate new token, then run sync --token NEW" % e.code)
        raise AccountsError("Questrade answered HTTP %d for %s" % (e.code, url.split("?")[0]))
    except urllib.error.URLError as e:
        raise AccountsError("could not reach Questrade: %s" % e.reason)


def questrade_login(refresh_token, http=_http_json):
    doc = http(QT_LOGIN % urllib.parse.quote(refresh_token.strip()))
    if not doc.get("access_token") or not doc.get("api_server"):
        raise AccountsError("Questrade login did not return a token")
    return doc


def sync_questrade(acct, paths, token=None, http=_http_json):
    """Positions + balances for one Questrade account. Returns the holdings doc.

    The refresh token works once: Questrade hands back a new one every login,
    and we keep it in trader/state/questrade-<id>.json (mode 600). Order of
    preference: --token, the saved one, QUESTRADE_REFRESH_TOKEN.
    """
    state_path = paths.token(acct["id"])
    saved = (read_json(state_path, {}) or {}).get("refresh_token")
    rt = token or saved or os.environ.get("QUESTRADE_REFRESH_TOKEN")
    if not rt:
        raise AccountsError("no Questrade token. In Questrade web: App Hub > Personal apps > register an app "
                            "(read-only scopes) > Generate new token. Then: accounts.py sync %s --token TOKEN"
                            % acct["id"])
    login = questrade_login(rt, http=http)
    write_json(state_path, {"refresh_token": login["refresh_token"], "saved": _now()}, private=True)
    api, at = login["api_server"].rstrip("/") + "/v1/", login["access_token"]
    accts = http(api + "accounts", at).get("accounts", [])
    number = str(acct.get("questrade_account_number") or "")
    if not number:
        if len(accts) != 1:
            raise AccountsError("Questrade has %d accounts (%s). Put the right one in accounts.json as "
                                "\"questrade_account_number\"." % (len(accts), ", ".join(
                                    "%s %s" % (a.get("type"), a.get("number")) for a in accts)))
        number = str(accts[0]["number"])
    match = [a for a in accts if str(a.get("number")) == number]
    if not match:
        raise AccountsError("Questrade account %s not found" % number)
    raw = http(api + "accounts/%s/positions" % number, at).get("positions", [])
    bal = http(api + "accounts/%s/balances" % number, at)
    ids = [str(p["symbolId"]) for p in raw if p.get("symbolId") and p.get("openQuantity")]
    info = {}
    if ids:
        for s in http(api + "symbols?ids=" + ",".join(ids), at).get("symbols", []):
            info[s.get("symbolId")] = s
    positions = []
    for p in raw:
        q = float(p.get("openQuantity") or 0)
        if not q:
            continue
        s = info.get(p.get("symbolId"), {})
        ticker = mk.yahoo_symbol(p["symbol"])
        positions.append({"ticker": ticker, "broker_symbol": p["symbol"], "name": s.get("description", ""),
                          "shares": q, "avg_cost": p.get("averageEntryPrice"),
                          "currency": (s.get("currency") or mk.native_currency(ticker)).upper(),
                          "last_price": p.get("currentPrice")})
    cash = {b["currency"]: round(float(b.get("cash") or 0), 2) for b in bal.get("perCurrencyBalances", [])}
    return {"account": acct["id"], "source": "questrade-api", "as_of": _now(),
            "questrade_type": match[0].get("type"), "cash": cash, "positions": positions}


# ---------------------------------------------------------------- review

def _today():
    return datetime.date.today().isoformat()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fx_rate(fx, frm, to):
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return 1.0
    if fx.get(frm + to):
        return float(fx[frm + to])
    if fx.get(to + frm):
        return 1.0 / float(fx[to + frm])
    return None


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def score(strategy, m, rules=None):
    """0-100. A rough heuristic to rank holdings inside one account, not a forecast.

    momentum_months picks the lookback that drives growth and medium scores; returns over
    shorter lookbacks are scaled to a yearly pace so the score ranges stay comparable."""
    if not m:
        return None
    g = lambda k: m.get(k) or 0.0  # noqa: E731
    up = m.get("above_sma200")
    mm = int((rules or {}).get("momentum_months") or (12 if strategy == "growth" else 6))
    fast = 3 if mm >= 6 else 1
    if strategy == "growth":
        s = 50 + _clip(g("ret_%dm" % mm) * (12.0 / mm) / 2, -20, 25) + _clip(g("ret_%dm" % fast) * (3.0 / fast) / 2, -10, 10)
        s += 10 if up else (-10 if up is False else 0)
        s -= 10 if g("off_high_pct") <= -30 else 0
    elif strategy == "medium":
        slow = 12 if mm < 12 else 6
        s = 50 + _clip(g("ret_%dm" % mm) * (6.0 / mm) / 2, -15, 20) + _clip(g("ret_%dm" % slow) * (12.0 / slow) / 4, -10, 10)
        s += 12 if up else (-12 if up is False else 0)
        s -= 8 if g("vol_pct") > 45 else 0
    else:
        y = g("yield_pct")
        s = 40
        s += 20 if 3 <= y <= 6.5 else 10 if (2 <= y < 3 or 6.5 < y <= 8) else -5 if y > 8 else -30 if y == 0 else 0
        s += _clip(g("div_growth_3y_pct") * 2, -15, 15)
        s -= 25 if (m.get("div_cut_pct") or 0) >= 10 else 0
        v = m.get("vol_pct")
        s += 0 if v is None else 10 if v < 20 else 5 if v < 30 else -10 if v > 35 else 0
        s += 5 if up else 0
    return int(round(_clip(s, 0, 100)))


def _stretch_verdicts(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "stretch_verdicts.json")):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("verdicts", {})
    except (OSError, ValueError):
        return {}


STRETCH_VERDICTS = _stretch_verdicts()  # from the stretch test (trader-replay/stretch.py), rule v15


def _flag(level, code, text):
    return {"level": level, "code": code, "text": text}


def effective_cap(r, n_positions):
    """The cap, but never below an equal share: with 5 holdings a 12% cap would force
    selling good stocks into idle cash. The 'concentrated' flag asks for more names instead."""
    if n_positions <= 0:
        return r["max_position_pct"]
    return max(r["max_position_pct"], round((100.0 - r["cash_target_pct"]) / n_positions, 2))


def position_flags(strategy, r, p, m, weight, acct_type, cap=None):
    """Flags for one holding. level: action (do something), watch, good, info."""
    f = []
    cap = r["max_position_pct"] if cap is None else cap
    if weight > cap + r.get("trim_band_pct", 0):
        f.append(_flag("action", "over_cap", "%.1f%% of the account, over your %g%% cap: trim" % (weight, cap)))
    gain = p.get("gain_pct")  # the stop only needs your cost and today's price, not market history
    if gain is not None and gain <= -r["stop_loss_pct"]:
        f.append(_flag("action", "stop", "down %.0f%% from your cost (stop is %g%%): decide to cut or keep, "
                       "write down why" % (-gain, r["stop_loss_pct"])))
    if not m:
        f.append(_flag("watch", "no_data", "no market data (check the ticker or run market)"))
        return f
    off = m.get("off_high_pct")
    if off is not None and off <= -r["drawdown_review_pct"]:
        f.append(_flag("watch", "drawdown", "%.0f%% below its 52-week high" % -off))
    r12 = m.get("ret_12m")
    if strategy in ("growth", "medium"):
        if r12 is not None and r12 < r.get("laggard_12m_pct", -10) and (gain or 0) < 0:
            f.append(_flag("watch", "laggard", "%.0f%% over 12 months and below your cost: consider "
                           "replacing it with a stronger name" % r12))
        if strategy == "medium" and m.get("above_sma200") is False and (m.get("ret_6m") or 0) < 0:
            f.append(_flag("action", "trend_broken", "below its 200-day average and down over 6 months: "
                           "the medium-term trend is broken"))
        if (m.get("ret_6m") or 0) > 25 and m.get("above_sma200"):
            f.append(_flag("good", "momentum", "strong momentum: +%.0f%% over 6 months" % m["ret_6m"]))
    fired = mk.stretch_signals(m.get("stretch") or {})
    if fired:  # rule v15: "trim" only for signals the stretch test showed falling behind; else risk info
        st, trim = m["stretch"], [x for x in fired if STRETCH_VERDICTS.get(x) == "trim"]
        what = "; ".join(mk.STRETCH_SIGNALS[x] for x in fired)
        if trim:
            f.append(_flag("action", "stretched", "%s: in the test (S&P 500, 2014-2026) stocks like this fell "
                           "behind over the next 3 months: consider trimming some, or a trailing stop" % what))
        else:
            f.append(_flag("watch", "stretched", "%s (%s%% above its 200-day, volatility %sx its usual). Tested: "
                           "stocks like this did not reliably fall behind, so this is not a sell signal; a trailing "
                           "stop or a small trim protects the gain if you want to" % (
                               what, st.get("above_sma200_pct"), st.get("vol_ratio"))))
    if strategy == "dividend":
        y = m.get("yield_pct") or 0
        if not m.get("div_ttm"):
            f.append(_flag("action", "no_dividend", "pays no dividend: does not fit the steady dividend account"))
        elif y < r["min_yield_pct"]:
            f.append(_flag("watch", "low_yield", "yield %.1f%% is under your %g%% floor" % (y, r["min_yield_pct"])))
        elif y > r["max_yield_pct"]:
            f.append(_flag("watch", "yield_trap", "yield %.1f%% is very high: check the payout is covered "
                           "before trusting it" % y))
        cut = m.get("div_cut_pct")
        if cut is not None and cut >= r["cut_pct"]:
            f.append(_flag("action", "div_cut", "dividend down %.0f%% from what it paid before: possible cut, "
                           "check the company's announcement" % cut))
        g3 = m.get("div_growth_3y_pct")
        if g3 is not None and g3 >= 5:
            f.append(_flag("good", "div_growth", "dividend up %.1f%% a year over 3 years" % g3))
        elif g3 is not None and g3 < 0:
            f.append(_flag("watch", "div_shrink", "dividend down %.1f%% a year over 3 years" % -g3))
        v = m.get("vol_pct")
        if v is not None and v > r["max_volatility_pct"]:
            f.append(_flag("watch", "volatile", "%.0f%% annual volatility, above your %g%% for a steady "
                           "account" % (v, r["max_volatility_pct"])))
        if m.get("div_ttm") and p["currency"] == "USD" and acct_type.upper() in TFSA_LIKE:
            f.append(_flag("info", "withholding", "US dividend in a %s: 15%% US tax is withheld and not "
                           "recoverable. US dividend payers fit better in an RRSP" % acct_type.upper()))
    return f


def review_account(acct, holdings, market, base="CAD", contribute=0.0):
    strategy, r = acct["strategy"], acct["rules"]
    fx = market.get("fx", {})
    msym = market.get("symbols", {})
    notes = []
    rows, invested = [], 0.0
    for p in holdings.get("positions", []):
        t = p["ticker"].upper()
        m = msym.get(t)
        ccy = ((m or {}).get("currency") or p.get("currency") or mk.native_currency(t)).upper()
        price = (m or {}).get("price") or p.get("last_price")
        rate = fx_rate(fx, ccy, base)
        if rate is None:
            notes.append("no %s/%s rate: %s counted 1:1 (run market)" % (ccy, base, t))
            rate = 1.0
        value = float(p["shares"]) * float(price or 0)
        row = {"ticker": t, "name": p.get("name") or (m or {}).get("name", ""), "shares": p["shares"],
               "currency": ccy, "price": price, "avg_cost": p.get("avg_cost"), "value": round(value, 2),
               "value_base": round(value * rate, 2), "fx": rate, "metrics": m}
        row["gain_pct"] = (round(100.0 * (price / p["avg_cost"] - 1), 2)
                           if price and p.get("avg_cost") else None)
        row["day_change_base"] = (round(value * rate * (m["day_pct"] or 0) / (100 + (m["day_pct"] or 0)), 2)
                                  if m and m.get("day_pct") is not None else 0.0)
        div = (m or {}).get("div_ttm") or 0.0
        gross = div * float(p["shares"]) * rate
        net = gross * (0.85 if ccy == "USD" and acct["type"].upper() not in NO_US_WITHHOLDING else 1.0)
        row["income_base"] = round(gross, 2)
        row["income_net_base"] = round(net, 2)
        row["yield_on_cost"] = round(100.0 * div / p["avg_cost"], 2) if div and p.get("avg_cost") else None
        if price is None:
            notes.append("%s has no price: run market" % t)
        invested += value * rate
        rows.append(row)
    cash_by = {k.upper(): float(v) for k, v in (holdings.get("cash") or {}).items()}
    cash = 0.0
    for c, v in cash_by.items():
        rate = fx_rate(fx, c, base)
        cash += v * (rate if rate is not None else 1.0)
    total = invested + cash
    cap = effective_cap(r, len(rows))
    for row in rows:
        row["weight"] = round(100.0 * row["value_base"] / total, 2) if total else 0.0
        row["score"] = score(strategy, row["metrics"], r)
        row["flags"] = position_flags(strategy, r, row, row["metrics"], row["weight"], acct["type"], cap)
    acct_flags = []
    cash_pct = 100.0 * cash / total if total else 0.0
    if cash < -0.5:
        acct_flags.append(_flag("action", "negative_cash", "cash is negative: you are borrowing on margin"))
    elif cash_pct > r["cash_max_pct"]:
        acct_flags.append(_flag("action", "idle_cash", "%.0f%% in cash (%s idle): put it to work" % (
            cash_pct, money(cash - total * r["cash_target_pct"] / 100.0, base))))
    if 0 < len(rows) < r.get("min_positions", 0):
        acct_flags.append(_flag("watch", "concentrated", "only %d holdings: one bad stock moves the whole "
                                "account" % len(rows)))
    top3 = sum(sorted((x["weight"] for x in rows), reverse=True)[:3])
    if len(rows) > 3 and top3 > 65:
        acct_flags.append(_flag("watch", "top_heavy", "your top 3 are %.0f%% of the account" % top3))
    proposals = propose(acct, rows, cash_by, total, cash, market, base, contribute, notes, cap)
    income = sum(x["income_base"] for x in rows)
    income_net = sum(x["income_net_base"] for x in rows)
    scored = [x for x in rows if x["score"] is not None]
    avg_score = (round(sum(x["score"] * x["weight"] for x in scored) / max(sum(x["weight"] for x in scored), 1e-9))
                 if scored else None)
    day = sum(x["day_change_base"] for x in rows)
    cost_base = sum(float(x["avg_cost"]) * float(x["shares"]) * x["fx"] for x in rows if x.get("avg_cost"))
    return {
        "id": acct["id"], "name": acct["name"], "broker": acct.get("broker", ""), "type": acct["type"],
        "strategy": strategy, "strategy_label": STRATEGY_LABEL[strategy], "rules": r, "cap_pct": cap,
        "as_of": holdings.get("as_of"), "source": holdings.get("source"),
        "total": round(total, 2), "invested": round(invested, 2), "cash": round(cash, 2), "cash_by": cash_by,
        "cash_pct": round(cash_pct, 2), "day_change": round(day, 2),
        "day_pct": round(100.0 * day / (total - day), 2) if total - day else 0.0,
        "gain": round(invested - cost_base, 2) if cost_base else None,
        "gain_pct": round(100.0 * (invested / cost_base - 1), 2) if cost_base else None,
        "income": round(income, 2), "income_net": round(income_net, 2),
        "yield_pct": round(100.0 * income / total, 2) if total else 0.0,
        "score": avg_score, "positions": sorted(rows, key=lambda x: -x["value_base"]),
        "flags": acct_flags, "proposals": proposals, "notes": notes,
    }


def _keepers(acct, rows, market, cap):
    """Holdings (and watchlist names) that deserve new money, with their target %."""
    strategy, r = acct["strategy"], acct["rules"]
    targets = {k.upper(): float(v) for k, v in (acct.get("targets") or {}).items()}
    cand = {}
    for x in rows:
        bad = any(f["level"] == "action" for f in x["flags"])
        if (x["score"] or 0) >= r["keep_score"] and not bad and x["price"]:
            cand[x["ticker"]] = x
    for t in acct.get("watchlist") or []:
        t = mk.yahoo_symbol(t)
        m = market.get("symbols", {}).get(t)
        if t in cand or not m or any(x["ticker"] == t for x in rows):
            continue
        sc = score(strategy, m, r)
        new = {"ticker": t, "name": m.get("name", ""), "shares": 0, "currency": m["currency"], "price": m["price"],
               "value_base": 0.0, "weight": 0.0, "score": sc, "metrics": m, "watchlist": True,
               "flags": position_flags(strategy, r, {"gain_pct": None, "currency": m["currency"]}, m, 0.0,
                                       acct["type"])}
        if (sc or 0) >= r["keep_score"] + 5 and not any(f["level"] == "action" for f in new["flags"]):
            cand[t] = new
    if targets:
        return {t: (cand[t], min(targets[t], cap)) for t in cand if t in targets}
    if not cand:
        return {}
    n = max(len(rows) + sum(1 for x in cand.values() if x.get("watchlist")), r.get("min_positions", 1))
    each = min(cap, (100.0 - r["cash_target_pct"]) / n)
    return {t: (x, each) for t, x in cand.items()}


def _shares(value_native, price, fractional):
    if not price:
        return 0
    q = value_native / price
    return round(q, 4) if fractional else math.floor(q + 1e-9)


ROTATE_CODES = ("stop", "trend_broken")


def propose(acct, rows, cash_by, total, cash, market, base, contribute, notes, cap=None):
    """Trims of anything over the cap, then buys with spare cash (+ a contribution).
    No buy ever takes a holding past the cap. With rules["rotate"], first sell holdings whose
    trend broke, that hit the stop, or whose score fell under sell_score, so the money moves
    to stronger names instead of riding losers while trimming winners."""
    r, out = acct["rules"], []
    cap = r["max_position_pct"] if cap is None else cap
    frac = bool(acct.get("fractional"))
    proceeds = 0.0
    sold = set()
    if r.get("rotate"):
        for x in rows:
            codes = {f["code"] for f in x["flags"] if f["level"] == "action"}
            weak = x["score"] is not None and x["score"] < r.get("sell_score", 0)
            if not x["price"] or not (weak or codes & set(ROTATE_CODES)):
                continue
            q = float(x["shares"])
            proceeds += q * x["price"] * x["fx"]
            sold.add(x["ticker"])
            why = ("stop hit" if "stop" in codes else "trend broken" if "trend_broken" in codes
                   else "score %s under %g" % (x["score"], r["sell_score"]))
            out.append({"side": "sell", "ticker": x["ticker"], "shares": q, "price": x["price"],
                        "currency": x["currency"], "value": round(q * x["price"], 2),
                        "value_base": round(q * x["price"] * x["fx"], 2),
                        "reason": "rotate out (%s): the money goes to stronger names" % why})
    for x in rows:
        if x["ticker"] in sold:
            continue
        cap_value = total * cap / 100.0
        if x["weight"] > cap + r.get("trim_band_pct", 0) and x["price"]:
            sell_base = x["value_base"] - cap_value
            q = _shares(sell_base / x["fx"], x["price"], frac)
            if q:
                proceeds += q * x["price"] * x["fx"]
                out.append({"side": "sell", "ticker": x["ticker"], "shares": q, "price": x["price"],
                            "currency": x["currency"], "value": round(q * x["price"], 2),
                            "value_base": round(q * x["price"] * x["fx"], 2),
                            "reason": "trim back to the %g%% cap (%s)" % (cap, "lock in part of the gain"
                                       if (x.get("gain_pct") or 0) > 0 else "cut the concentration")})
    new_total = total + contribute
    spare = cash + proceeds + contribute - new_total * r["cash_target_pct"] / 100.0
    if spare < r["min_trade"]:
        return out
    keep = {t: v for t, v in _keepers(acct, rows, market, cap).items() if t not in sold}
    if not keep:
        notes.append("spare cash but no holding qualifies for new money: add ideas to this account's "
                     "watchlist in accounts.json")
        return out
    gaps, room = {}, {}
    for t, (x, tgt) in keep.items():
        now = x["value_base"] - sum(o["value_base"] for o in out if o["ticker"] == t)
        gaps[t] = max(0.0, new_total * tgt / 100.0 - now)
        room[t] = max(0.0, new_total * cap / 100.0 - now)
    if sum(gaps.values()) < r["min_trade"]:  # everything at target: lean toward the best scores, up to the cap
        gaps = {t: float(x["score"] or 1) for t, (x, _) in keep.items() if room[t] >= r["min_trade"]}
        spare_use = min(spare, sum(room[t] for t in gaps))
    else:
        spare_use = min(spare, sum(gaps.values()))
    tot_gap = sum(gaps.values()) or 1.0
    buys = []
    for t, g in sorted(gaps.items(), key=lambda kv: -kv[1]):
        x = keep[t][0]
        amt_base = min(spare_use * g / tot_gap, room[t])
        if amt_base < r["min_trade"]:
            continue
        rate = fx_rate(market.get("fx", {}), x["currency"], base) or 1.0
        q = _shares(amt_base / rate, x["price"], frac)
        if not q:
            continue
        buys.append({"side": "buy", "ticker": t, "shares": q, "price": x["price"], "currency": x["currency"],
                     "value": round(q * x["price"], 2), "value_base": round(q * x["price"] * rate, 2),
                     "reason": ("new idea from your watchlist, score %s" % x["score"]) if x.get("watchlist")
                     else "under its target weight, score %s" % x["score"]})
    out.extend(buys)
    left = spare - sum(b["value_base"] for b in buys)
    if left >= max(r["min_trade"], 0.02 * new_total):
        notes.append("%s stays in cash after these trades: no other name qualifies for new money. Add ideas to this account's "
                     "watchlist in accounts.json and they will be scored next time" % money(left, base))
    need = {}
    for b in buys:
        need[b["currency"]] = need.get(b["currency"], 0.0) + b["value"]
    for c, v in need.items():
        have = cash_by.get(c, 0.0) + (contribute if c == base else 0.0)
        have += sum(o["value"] for o in out if o["side"] == "sell" and o["currency"] == c)
        if v > have + 1:
            notes.append("the buys need %s %s but the account holds %s %s: convert currency first "
                         "(for large amounts Norbert's gambit is cheaper than the broker's FX)" % (
                             money(v, c), c, money(have, c), c))
    return out


def plan_contribution(cfg, reviews, amount):
    """Split new money between strategies, toward the target mix."""
    mix = {k: float(v) for k, v in (cfg.get("mix") or {}).items() if float(v) > 0}
    if not mix or amount <= 0:
        return {}
    have = {}
    for r in reviews:
        have[r["strategy"]] = have.get(r["strategy"], 0.0) + r["total"]
    total = sum(have.values()) + amount
    msum = sum(mix.values())
    gaps = {s: max(0.0, total * w / msum - have.get(s, 0.0)) for s, w in mix.items()}
    gsum = sum(gaps.values())
    split = {s: amount * (g / gsum if gsum else mix[s] / msum) for s, g in gaps.items()}
    out = {}
    for s, amt in split.items():
        accts = [r for r in reviews if r["strategy"] == s]
        if not accts:
            continue
        out[accts[0]["id"]] = out.get(accts[0]["id"], 0.0) + round(amt, 2)
    return {k: v for k, v in out.items() if v >= 0.01}


def review_all(cfg, paths, market, contribute=0.0, only=None):
    base = cfg["base_currency"]
    accts = [a for a in cfg.get("accounts", []) if not only or a["id"] == only]
    holdings = {a["id"]: read_json(paths.holdings(a["id"]), empty_holdings(a["id"])) for a in accts}
    first = [review_account(a, holdings[a["id"]], market, base) for a in accts]
    split = plan_contribution(cfg, first, contribute) if contribute else {}
    if contribute and not split and accts:
        split = {accts[0]["id"]: contribute}
    reviews = [review_account(a, holdings[a["id"]], market, base, split.get(a["id"], 0.0)) if split.get(a["id"])
               else r for a, r in zip(accts, first)]
    total = sum(r["total"] for r in reviews)
    by_strategy = {}
    for r in reviews:
        by_strategy[r["strategy"]] = by_strategy.get(r["strategy"], 0.0) + r["total"]
    mix = cfg.get("mix") or {}
    msum = sum(float(v) for v in mix.values()) or 0
    mix_rows = [{"strategy": s, "label": STRATEGY_LABEL[s], "value": round(by_strategy.get(s, 0.0), 2),
                 "pct": round(100.0 * by_strategy.get(s, 0.0) / total, 2) if total else 0.0,
                 "target_pct": round(100.0 * float(mix.get(s, 0)) / msum, 2) if msum else None}
                for s in RULES if s in by_strategy or s in mix]
    day = sum(r["day_change"] for r in reviews)
    todo = []
    for r in reviews:
        for f in r["flags"]:
            if f["level"] == "action":
                todo.append({"account": r["name"], "ticker": None, "text": f["text"]})
        for p in r["positions"]:
            for f in p["flags"]:
                if f["level"] == "action":
                    todo.append({"account": r["name"], "ticker": p["ticker"], "text": f["text"]})
    return {
        "as_of": _now(), "base_currency": base, "market_as_of": market.get("as_of"),
        "total": round(total, 2), "day_change": round(day, 2),
        "day_pct": round(100.0 * day / (total - day), 2) if total - day else 0.0,
        "income": round(sum(r["income"] for r in reviews), 2),
        "income_net": round(sum(r["income_net"] for r in reviews), 2),
        "mix": mix_rows, "contribute": contribute, "contribution_split": split,
        "accounts": reviews, "todo": todo, "fx": market.get("fx", {}),
        "market_errors": market.get("errors", []),
        "disclaimer": "Not financial advice. Heuristics on delayed public data; you decide and you place every trade.",
    }


def snapshot(path, res, day=None):
    hist = read_json(path, {"points": []})
    day = day or _today()
    pt = {"date": day, "total": res["total"], "accounts": {r["id"]: r["total"] for r in res["accounts"]}}
    hist["points"] = [p for p in hist.get("points", []) if p["date"] != day] + [pt]
    hist["points"].sort(key=lambda p: p["date"])
    write_json(path, hist)
    return hist


# ---------------------------------------------------------------- text

def money(x, ccy="CAD"):
    x = float(x or 0)
    s = "{:,.2f}".format(abs(x))
    return ("-" if x < -0.004 else "") + "$" + s


def _pct(x):
    return "n/a" if x is None else "%+.1f%%" % x


def report(res):
    b = res["base_currency"]
    L = ["Portfolio %s %s   today %s (%s)   dividends %s/yr (%s/mo)" % (
        money(res["total"]), b, money(res["day_change"]), _pct(res["day_pct"]),
        money(res["income_net"]), money(res["income_net"] / 12))]
    if res["mix"]:
        L.append("Mix: " + "   ".join("%s %.0f%%%s" % (m["label"], m["pct"], (" (target %.0f%%)" % m["target_pct"])
                                                         if m["target_pct"] is not None else "") for m in res["mix"]))
    for r in res["accounts"]:
        L.append("")
        L.append("== %s  [%s, %s]  %s  cash %s (%.0f%%)  score %s" % (
            r["name"], r["strategy_label"], r["type"], money(r["total"]), money(r["cash"]), r["cash_pct"],
            r["score"] if r["score"] is not None else "n/a"))
        L.append("   %-9s %9s %10s %8s %7s %8s %7s %5s" % ("ticker", "shares", "value", "weight", "gain",
                                                          "12m", "yield", "score"))
        for p in r["positions"]:
            m = p["metrics"] or {}
            L.append("   %-9s %9s %10s %7.1f%% %7s %8s %6.1f%% %5s" % (
                p["ticker"], ("%.4f" % float(p["shares"])).rstrip("0").rstrip("."), money(p["value_base"]),
                p["weight"], _pct(p["gain_pct"]), _pct(m.get("ret_12m")), m.get("yield_pct") or 0.0,
                p["score"] if p["score"] is not None else "-"))
            for f in p["flags"]:
                if f["level"] != "info":
                    L.append("      %-6s %s" % (f["level"].upper(), f["text"]))
        for f in r["flags"]:
            L.append("   %-6s %s" % (f["level"].upper(), f["text"]))
        if r["proposals"]:
            L.append("   Proposed (you place these yourself in %s, only if you agree):" % (r["broker"] or "the app"))
            for o in r["proposals"]:
                L.append("     %-4s %s %s @ ~%s %s = %s %s   %s" % (
                    o["side"].upper(), o["shares"], o["ticker"], money(o["price"]), o["currency"],
                    money(o["value"]), o["currency"], o["reason"]))
        for n in r["notes"]:
            L.append("   note: " + n)
    if res["contribution_split"]:
        L.append("")
        L.append("New money %s goes: %s" % (money(res["contribute"]), ", ".join(
            "%s %s" % (k, money(v)) for k, v in res["contribution_split"].items())))
    for e in res.get("market_errors", []):
        L.append("market note: " + e)
    L.append("")
    L.append(res["disclaimer"])
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- CLI

def all_symbols(cfg, paths):
    syms = []
    for a in cfg.get("accounts", []):
        h = read_json(paths.holdings(a["id"]), empty_holdings(a["id"]))
        syms += [p["ticker"] for p in h.get("positions", [])]
        syms += [mk.yahoo_symbol(t) for t in a.get("watchlist") or []]
    syms += [mk.yahoo_symbol(t) for t in cfg.get("watchlist") or []]
    return list(dict.fromkeys(s.upper() for s in syms if s))


def cmd_market(a, cfg, paths):
    syms = all_symbols(cfg, paths) + [s.upper() for s in a.extra or []]
    if not syms:
        raise AccountsError("no holdings yet: import or sync an account first")
    res = mk.refresh(syms, offline=a.offline, today=a.today)
    res["as_of"] = _now()
    old = read_json(paths.market, {}) or {}
    keep = dict(old.get("symbols", {}))
    keep.update(res["symbols"])
    res["symbols"] = keep
    res["fx"] = res["fx"] or old.get("fx", {})
    write_json(paths.market, res)
    print("market: %d symbols, USD/CAD %s -> %s" % (len(res["symbols"]), res["fx"].get("USDCAD", "n/a"), paths.market))
    for e in res["errors"]:
        print("note: " + e, file=sys.stderr)
    return 0


def cmd_review(a, cfg, paths):
    market = read_json(paths.market, {"symbols": {}, "fx": {}})
    res = review_all(cfg, paths, market, contribute=a.contribute or 0.0, only=a.account)
    if a.write:
        write_json(paths.proposals, res)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        sys.stdout.write(report(res))
    return 0


def cmd_import(a, cfg, paths):
    acct = account(cfg, a.account)
    with open(a.file, encoding="utf-8-sig", errors="replace") as fh:
        doc = parse_holdings_csv(fh.read(), acct["id"], a.filter)
    old = read_json(paths.holdings(acct["id"]), empty_holdings(acct["id"]))
    doc["cash"] = old.get("cash", {})
    if a.cash is not None:
        doc["cash"][a.currency.upper()] = a.cash
    write_json(paths.holdings(acct["id"]), doc)
    print("%s: %d holdings imported (%d rows skipped) -> %s" % (
        acct["id"], len(doc["positions"]), doc.get("skipped_rows", 0), paths.holdings(acct["id"])))
    if not doc["cash"]:
        print("tip: set the cash too: accounts.py cash %s AMOUNT --currency CAD" % acct["id"])
    return 0


def cmd_sync(a, cfg, paths):
    ids = [a.account] if a.account else [x["id"] for x in cfg["accounts"] if x.get("broker") == "questrade"]
    if not ids:
        raise AccountsError("no account with \"broker\": \"questrade\" in accounts.json")
    for i in ids:
        acct = account(cfg, i)
        doc = sync_questrade(acct, paths, token=a.token)
        write_json(paths.holdings(i), doc)
        print("%s: %d positions, cash %s -> %s" % (i, len(doc["positions"]), doc["cash"], paths.holdings(i)))
    return 0


def cmd_cash(a, cfg, paths):
    acct = account(cfg, a.account)
    doc = read_json(paths.holdings(acct["id"]), empty_holdings(acct["id"]))
    doc.setdefault("cash", {})[a.currency.upper()] = a.amount
    write_json(paths.holdings(acct["id"]), doc)
    print("%s cash: %s" % (acct["id"], doc["cash"]))
    return 0


def cmd_snapshot(a, cfg, paths):
    market = read_json(paths.market, {"symbols": {}, "fx": {}})
    res = review_all(cfg, paths, market)
    hist = snapshot(paths.history, res, a.today)
    print("history: %d days, today %s" % (len(hist["points"]), money(res["total"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Review your real accounts against their strategies.")
    ap.add_argument("--dir", default="trader", help="data folder (default trader/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("market", help="refresh prices, dividends and FX for every holding")
    p.add_argument("extra", nargs="*", help="more symbols to include")
    p.add_argument("--offline", metavar="DIR")
    p.add_argument("--today")
    p = sub.add_parser("review", help="flags and proposals per account")
    p.add_argument("--account")
    p.add_argument("--contribute", type=float, help="new money to place, in the base currency")
    p.add_argument("--write", action="store_true", help="also write trader/proposals.json")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("import", help="import a holdings CSV export")
    p.add_argument("account")
    p.add_argument("file")
    p.add_argument("--filter", help="only rows whose account name/number contains this")
    p.add_argument("--cash", type=float)
    p.add_argument("--currency", default="CAD")
    p = sub.add_parser("sync", help="pull positions and cash from the Questrade API (read-only)")
    p.add_argument("account", nargs="?")
    p.add_argument("--token", help="a fresh refresh token from Questrade's App Hub")
    p = sub.add_parser("cash", help="set an account's cash balance")
    p.add_argument("account")
    p.add_argument("amount", type=float)
    p.add_argument("--currency", default="CAD")
    p = sub.add_parser("snapshot", help="record today's value in history.json")
    p.add_argument("--today")
    a = ap.parse_args(argv)
    paths = Paths(a.dir)
    try:
        cfg = load_config(paths.config)
        return {"market": cmd_market, "review": cmd_review, "import": cmd_import, "sync": cmd_sync,
                "cash": cmd_cash, "snapshot": cmd_snapshot}[a.cmd](a, cfg, paths)
    except (AccountsError, mk.MarketError) as e:
        print("accounts: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
