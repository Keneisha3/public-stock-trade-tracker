"""The Executor: places PAPER or SIMULATED trades, and nothing else.

Two brokers:
  SimBroker          fake money kept in trader/team/state.json. No account, no keys.
                     Fills at the bar price plus slippage, minus fees.
  AlpacaPaperBroker  Alpaca's paper-trading account (fake money, real order flow).

The Alpaca one refuses to trade unless ALL of these hold:
  1. TRADING_MODE=paper is set in .env
  2. the API address is https://paper-api.alpaca.markets (the only address in
     this code: there is no live-trading address anywhere in this project)
  3. the key is a paper key (paper keys start with "PK"; live keys do not)
  4. Alpaca itself says the account is a paper account (number starts "PA")
Any doubt means no trade.
"""

import time

from candles import DataError, http_json, mask

PAPER_URL = "https://paper-api.alpaca.markets"


class PaperGuardError(Exception):
    pass


class SimBroker:
    label = "SIMULATED"

    def __init__(self, state, cfg):
        self.state, self.cfg = state, cfg
        state.setdefault("cash", float(cfg["start_cash"]))

    def _costs(self, notional):
        return notional * self.cfg["fee_pct"] / 100.0

    def buy(self, coin, qty, price):
        fill = price * (1 + self.cfg["slippage_pct"] / 100.0)
        fee = self._costs(qty * fill)
        if qty * fill + fee > self.state["cash"] + 1e-9:
            raise PaperGuardError("not enough simulated cash")
        self.state["cash"] -= qty * fill + fee
        return {"price": fill, "qty": qty, "fee": fee}

    def sell(self, coin, qty, price):
        fill = price * (1 - self.cfg["slippage_pct"] / 100.0)
        fee = self._costs(qty * fill)
        self.state["cash"] += qty * fill - fee
        return {"price": fill, "qty": qty, "fee": fee}

    def account(self, prices):
        pos = self.state.get("positions", {})
        eq = self.state["cash"] + sum(p["qty"] * prices.get(c, p["entry"]) for c, p in pos.items())
        return {"equity": eq, "cash": self.state["cash"]}


class AlpacaPaperBroker:
    label = "PAPER"

    def __init__(self, env, cfg, http=http_json, sleep=time.sleep):
        self.env, self.cfg, self.http, self.sleep = env, cfg, http, sleep
        self.base = PAPER_URL
        self.verified = False

    def _h(self):
        return {"APCA-API-KEY-ID": self.env.get("PAPER_API_KEY", ""),
                "APCA-API-SECRET-KEY": self.env.get("PAPER_API_SECRET", "")}

    def verify(self):
        """Refuse unless the environment is clearly paper. Returns the account."""
        e = self.env
        if str(e.get("TRADING_MODE", "")).strip().lower() != "paper":
            raise PaperGuardError("TRADING_MODE=paper is not set in .env: refusing to trade")
        url = str(e.get("PAPER_API_BASE_URL") or PAPER_URL).rstrip("/")
        if url != PAPER_URL:
            raise PaperGuardError("PAPER_API_BASE_URL is %s, not %s: refusing to trade" % (url, PAPER_URL))
        key, secret = str(e.get("PAPER_API_KEY", "")), str(e.get("PAPER_API_SECRET", ""))
        if not key or not secret:
            raise PaperGuardError("PAPER_API_KEY and PAPER_API_SECRET are missing from .env")
        if not key.startswith("PK"):
            raise PaperGuardError("the key %s is not a paper key (paper keys start with PK): refusing to trade"
                                  % mask(key))
        try:
            acct = self.http(self.base + "/v2/account", headers=self._h())
        except DataError as err:
            raise PaperGuardError("could not check the paper account: %s" % err)
        if not str(acct.get("account_number", "")).startswith("PA"):
            raise PaperGuardError("Alpaca did not confirm a paper account: refusing to trade")
        if acct.get("status") not in (None, "ACTIVE") or acct.get("crypto_status") not in (None, "ACTIVE"):
            raise PaperGuardError("the paper account is not active for crypto (status %s, crypto %s)" % (
                acct.get("status"), acct.get("crypto_status")))
        self.verified = True
        return acct

    def account(self, prices=None):
        if not self.verified:
            self.verify()
        a = self.http(self.base + "/v2/account", headers=self._h())
        return {"equity": float(a.get("equity") or 0), "cash": float(a.get("cash") or 0)}

    def positions(self):
        if not self.verified:
            self.verify()
        out = {}
        for p in self.http(self.base + "/v2/positions", headers=self._h()) or []:
            sym = str(p.get("symbol", "")).replace("/", "")
            if sym.endswith("USD"):
                out[sym[:-3]] = float(p.get("qty_available") or p.get("qty") or 0)
        return out

    def _order(self, coin, qty, side):
        if not self.verified:
            self.verify()
        body = {"symbol": "%s/USD" % coin, "qty": ("%.8f" % qty).rstrip("0").rstrip("."), "side": side,
                "type": "market", "time_in_force": "gtc"}
        o = self.http(self.base + "/v2/orders", headers=self._h(), data=body, method="POST")
        oid = o.get("id")
        for _ in range(15):
            if o.get("status") == "filled":
                break
            if o.get("status") in ("canceled", "expired", "rejected"):
                raise PaperGuardError("paper order %s was %s" % (oid, o.get("status")))
            self.sleep(1)
            o = self.http(self.base + "/v2/orders/%s" % oid, headers=self._h())
        if o.get("status") != "filled":
            try:
                self.http(self.base + "/v2/orders/%s" % oid, headers=self._h(), method="DELETE")
            except DataError:
                pass
            raise PaperGuardError("paper order %s did not fill in 15 s and was cancelled" % oid)
        price, filled = float(o["filled_avg_price"]), float(o["filled_qty"])
        return {"price": price, "qty": filled, "fee": filled * price * self.cfg["fee_pct"] / 100.0,
                "order_id": oid}

    def buy(self, coin, qty, price=None):
        return self._order(coin, qty, "buy")

    def sell(self, coin, qty, price=None):
        held = self.positions().get(coin, 0.0)
        return self._order(coin, min(qty, held) if held else qty, "sell")


def make_broker(cfg, state, env, http=http_json, sleep=time.sleep):
    mode = cfg["broker"]
    if mode == "sim":
        return SimBroker(state, cfg)
    if mode == "alpaca-paper":
        b = AlpacaPaperBroker(env, cfg, http=http, sleep=sleep)
        b.verify()
        return b
    raise PaperGuardError("broker must be \"sim\" or \"alpaca-paper\", not %r" % mode)
