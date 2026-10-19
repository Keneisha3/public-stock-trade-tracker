import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load
import _synth

acc = load("trader-accounts", "accounts")
mk = acc.mk

WS_CSV = """Holdings report as of 2026-10-16
,
Account Name,Account Type,Account Classification,Account Number,Symbol,Exchange,MIC,Name,Security Type,Quantity,Position Direction,Market Price,Market Price Currency,Book Value (CAD),Book Value Currency (CAD),Book Value (Market),Book Value Currency (Market),Market Value,Market Value Currency
Dividend TFSA,TFSA,Self-directed,HQ123,ENB,TSX,XTSE,Enbridge Inc,EQUITY,40,LONG,60.00,CAD,2200.00,CAD,2200.00,CAD,2400.00,CAD
Dividend TFSA,TFSA,Self-directed,HQ123,CTC.A,TSX,XTSE,Canadian Tire Corp Class A,EQUITY,3,LONG,160.00,CAD,450.00,CAD,450.00,CAD,480.00,CAD
Dividend TFSA,TFSA,Self-directed,HQ123,KO,NYSE,XNYS,Coca-Cola Co,EQUITY,10,LONG,70.00,USD,880.00,CAD,640.00,USD,700.00,USD
Dividend TFSA,TFSA,Self-directed,HQ123,ENB,TSX,XTSE,Enbridge Inc,EQUITY,10,LONG,60.00,CAD,500.00,CAD,500.00,CAD,600.00,CAD
Crypto,Crypto,Self-directed,C999,BTC,,,Bitcoin,CRYPTOCURRENCY,0.01,LONG,90000,CAD,800,CAD,800,CAD,900,CAD
"""


def config(**over):
    cfg = {
        "base_currency": "CAD",
        "mix": {"growth": 60, "dividend": 40},
        "accounts": [
            {"id": "questrade", "name": "Questrade", "broker": "questrade", "type": "TFSA",
             "strategy": "growth", "watchlist": ["NVDA"]},
            {"id": "wealthsimple", "name": "Wealthsimple", "broker": "wealthsimple", "type": "TFSA",
             "strategy": "dividend", "watchlist": ["BNS.TO"]},
        ],
    }
    cfg.update(over)
    return cfg


class Symbols(unittest.TestCase):
    def test_broker_symbols_become_yahoo_symbols(self):
        self.assertEqual(mk.yahoo_symbol("BNS.TO"), "BNS.TO")
        self.assertEqual(mk.yahoo_symbol("shop", "TSX"), "SHOP.TO")
        self.assertEqual(mk.yahoo_symbol("CTC.A", "TSX"), "CTC-A.TO")
        self.assertEqual(mk.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(mk.yahoo_symbol("XYZ.VN"), "XYZ.V")
        self.assertEqual(mk.yahoo_symbol("ABC", "XCNQ"), "ABC.CN")
        self.assertEqual(mk.yahoo_symbol("USDCAD=X"), "USDCAD=X")
        self.assertEqual(mk.native_currency("ENB.TO"), "CAD")
        self.assertEqual(mk.native_currency("AAPL"), "USD")


class Metrics(unittest.TestCase):
    def test_returns_dividends_and_growth(self):
        divs = _synth.quarterly("2021-11-01", "2026-08-01", 0.80, step=0.01)
        doc = _synth.chart("ENB.TO", p0=50, growth=0.2, wiggle=0.005, currency="CAD", divs=divs)
        m = mk.metrics(mk.parse_chart(json.dumps(doc), "ENB.TO"))
        self.assertEqual(m["currency"], "CAD")
        self.assertEqual(m["div_payments_ttm"], 4)
        self.assertGreater(m["div_ttm"], 3.6)
        self.assertGreater(m["yield_pct"], 5)
        self.assertGreater(m["div_growth_3y_pct"], 1)
        self.assertIsNone(m["div_cut_pct"])
        self.assertTrue(m["above_sma200"])
        self.assertAlmostEqual(m["ret_12m"], 100 * (pow(2.718281828, 0.2 * 252 / 1259) - 1), delta=1.5)

    def test_a_dividend_cut_is_caught_and_a_special_is_not(self):
        divs = _synth.quarterly("2024-11-01", "2026-05-01", 1.00) + [("2026-08-01", 0.50)]
        m = mk.metrics(mk.parse_chart(json.dumps(_synth.chart("CUT", divs=divs)), "CUT"))
        self.assertEqual(m["div_cut_pct"], 50)
        divs = _synth.quarterly("2024-11-01", "2026-08-01", 1.00)
        divs.insert(-1, ("2026-06-15", 5.00))  # one-off special before the last regular payment
        m = mk.metrics(mk.parse_chart(json.dumps(_synth.chart("SPEC", divs=divs)), "SPEC"))
        self.assertTrue(m["div_cut_pct"] is None or m["div_cut_pct"] < 10, m["div_cut_pct"])

    def test_a_cut_more_than_a_year_old_shows_in_the_yearly_totals(self):
        divs = _synth.quarterly("2024-01-15", "2025-04-15", 0.92) + _synth.quarterly("2025-07-15", "2026-07-15", 0.44)
        m = mk.metrics(mk.parse_chart(json.dumps(_synth.chart("BCE.TO", divs=divs)), "BCE.TO"))
        self.assertGreater(m["div_cut_pct"], 30)  # a year straddling the cut: a lower bound, well over the 10% flag

    def test_quarterly_to_monthly_is_not_a_cut(self):
        divs = _synth.quarterly("2024-01-15", "2025-07-15", 0.90)
        divs += [("2025-%02d-15" % mo, 0.30) for mo in range(10, 13)] + [("2026-%02d-15" % mo, 0.30) for mo in range(1, 10)]
        m = mk.metrics(mk.parse_chart(json.dumps(_synth.chart("MTH", divs=divs)), "MTH"))
        self.assertTrue(m["div_cut_pct"] is None or m["div_cut_pct"] < 10, m["div_cut_pct"])

    def test_unknown_symbol_is_a_clear_error(self):
        bad = json.dumps({"chart": {"result": None, "error": {"description": "No data found"}}})
        with self.assertRaises(mk.MarketError) as e:
            mk.parse_chart(bad, "NOPE")
        self.assertIn("No data found", str(e.exception))


class Retries(unittest.TestCase):
    def test_throttled_then_ok_and_query2_fallback(self):
        import urllib.error
        seen = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            seen.append(req.full_url)
            if len(seen) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
            return Resp(b'{"ok": 1}')
        old_open, old_waits = mk.urllib.request.urlopen, mk.RETRY_WAITS
        mk.urllib.request.urlopen, mk.RETRY_WAITS = fake, (0, 0)
        try:
            self.assertEqual(mk.fetch("https://query1.finance.yahoo.com/v8/finance/chart/SPY"), '{"ok": 1}')
        finally:
            mk.urllib.request.urlopen, mk.RETRY_WAITS = old_open, old_waits
        self.assertIn("//query1.", seen[0])
        self.assertIn("//query2.", seen[1])

    def test_unknown_symbol_is_not_retried(self):
        import urllib.error
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        old_open = mk.urllib.request.urlopen
        mk.urllib.request.urlopen = fake
        try:
            with self.assertRaises(mk.MarketError):
                mk.fetch("https://query1.finance.yahoo.com/v8/finance/chart/NOPE")
        finally:
            mk.urllib.request.urlopen = old_open
        self.assertEqual(len(calls), 1)


class NoMarketData(unittest.TestCase):
    def test_stop_and_cap_still_fire_without_price_history(self):
        a = {"id": "w", "name": "W", "strategy": "dividend", "type": "TFSA", "fractional": True,
             "rules": dict(acc.RULES["dividend"])}
        h = {"cash": {}, "positions": [
            {"ticker": "T.TO", "shares": 32, "avg_cost": 18.95, "last_price": 11.69, "currency": "CAD"},
            {"ticker": "APTX", "shares": 31, "avg_cost": 32.3, "last_price": 31.72, "currency": "CAD"},
            {"ticker": "RY.TO", "shares": 3, "avg_cost": 235.0, "last_price": 277.4, "currency": "CAD"}]}
        r = acc.review_account(a, h, {"symbols": {}, "fx": {}})
        codes = {p["ticker"]: {f["code"] for f in p["flags"]} for p in r["positions"]}
        self.assertIn("stop", codes["T.TO"])  # down 38% vs a 30% stop, with no market history at all
        self.assertIn("no_data", codes["T.TO"])
        trims = [o for o in r["proposals"] if o["side"] == "sell"]
        for o in trims:
            gain = [p for p in r["positions"] if p["ticker"] == o["ticker"]][0]["gain_pct"]
            self.assertIn("lock in part of the gain" if gain > 0 else "cut the concentration", o["reason"])


class CsvImport(unittest.TestCase):
    def test_wealthsimple_holdings_report(self):
        doc = acc.parse_holdings_csv(WS_CSV, "wealthsimple", filter_text="HQ123")
        by = {p["ticker"]: p for p in doc["positions"]}
        self.assertEqual(sorted(by), ["CTC-A.TO", "ENB.TO", "KO"])
        self.assertEqual(by["ENB.TO"]["shares"], 50)  # two lots merged
        self.assertAlmostEqual(by["ENB.TO"]["avg_cost"], 54.0)
        self.assertEqual(by["KO"]["currency"], "USD")
        self.assertAlmostEqual(by["KO"]["avg_cost"], 64.0)  # market-currency book value, not CAD

    def test_generic_broker_csv(self):
        text = "Symbol,Description,Quantity,Average Cost,Currency\nAAPL,Apple,5,150,USD\nCASH,,100,,\nSHOP.TO,Shopify,2,$1,000.00,CAD\n"
        text = text.replace("$1,000.00", "\"$1,000.00\"")
        doc = acc.parse_holdings_csv(text, "questrade")
        by = {p["ticker"]: p for p in doc["positions"]}
        self.assertEqual(by["AAPL"]["avg_cost"], 150)
        self.assertEqual(by["SHOP.TO"]["avg_cost"], 1000)
        self.assertEqual(doc["skipped_rows"], 1)

    def test_no_header_is_explained(self):
        with self.assertRaises(acc.AccountsError):
            acc.parse_holdings_csv("a,b,c\n1,2,3\n", "x")


class Questrade(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = acc.Paths(self.dir)
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def http(self, url, token=None):
        self.calls.append((url, token))
        if "oauth2/token" in url:
            return {"access_token": "AT", "refresh_token": "NEXT", "api_server": "https://api01.iq.questrade.com/"}
        if url.endswith("/v1/accounts"):
            return {"accounts": [{"type": "TFSA", "number": "51234567"}]}
        if url.endswith("/positions"):
            return {"positions": [
                {"symbol": "NVDA", "symbolId": 1, "openQuantity": 12, "averageEntryPrice": 120.5, "currentPrice": 180},
                {"symbol": "SHOP.TO", "symbolId": 2, "openQuantity": 4, "averageEntryPrice": 90, "currentPrice": 150},
                {"symbol": "OLD", "symbolId": 3, "openQuantity": 0}]}
        if url.endswith("/balances"):
            return {"perCurrencyBalances": [{"currency": "CAD", "cash": 250.5}, {"currency": "USD", "cash": 1000}]}
        if "symbols?ids=" in url:
            self.assertIn("ids=1,2", url)
            return {"symbols": [{"symbolId": 1, "currency": "USD", "description": "NVIDIA CORP"},
                                {"symbolId": 2, "currency": "CAD", "description": "SHOPIFY INC"}]}
        raise AssertionError(url)

    def test_sync_reads_positions_and_rotates_the_token(self):
        a = {"id": "questrade", "name": "Q"}
        doc = acc.sync_questrade(a, self.paths, token="FIRST", http=self.http)
        self.assertIn("refresh_token=FIRST", self.calls[0][0])
        self.assertEqual([c[1] for c in self.calls[1:]], ["AT"] * (len(self.calls) - 1))
        self.assertEqual([p["ticker"] for p in doc["positions"]], ["NVDA", "SHOP.TO"])
        self.assertEqual(doc["positions"][0]["name"], "NVIDIA CORP")
        self.assertEqual(doc["cash"], {"CAD": 250.5, "USD": 1000.0})
        tok = self.paths.token("questrade")
        with open(tok) as fh:
            self.assertEqual(json.load(fh)["refresh_token"], "NEXT")
        self.assertEqual(stat.S_IMODE(os.stat(tok).st_mode), 0o600)
        # next sync uses the saved token, not the spent one
        self.calls.clear()
        acc.sync_questrade(a, self.paths, http=self.http)
        self.assertIn("refresh_token=NEXT", self.calls[0][0])

    def test_several_accounts_need_a_number(self):
        def http(url, token=None):
            if "oauth2" in url:
                return {"access_token": "AT", "refresh_token": "N", "api_server": "https://x/"}
            return {"accounts": [{"type": "TFSA", "number": "1"}, {"type": "Margin", "number": "2"}]}
        with self.assertRaises(acc.AccountsError) as e:
            acc.sync_questrade({"id": "q"}, self.paths, token="T", http=http)
        self.assertIn("questrade_account_number", str(e.exception))


class Review(unittest.TestCase):
    """A growth Questrade TFSA with US stocks and a dividend Wealthsimple TFSA."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = acc.Paths(self.dir)
        off = os.path.join(self.dir, "offline")
        W = _synth.write
        W(off, "NVDA", _synth.chart("NVDA", p0=60, growth=1.2, wiggle=0.01))       # big winner
        W(off, "AMD", _synth.chart("AMD", p0=150, growth=-0.6, wiggle=0.01))       # loser, below cost
        W(off, "MSFT", _synth.chart("MSFT", p0=300, growth=0.4, wiggle=0.005))
        W(off, "ENB.TO", _synth.chart("ENB.TO", p0=45, growth=0.25, wiggle=0.004, currency="CAD",
                                       divs=_synth.quarterly("2021-11-01", "2026-08-01", 0.85, 0.02)))
        W(off, "TECH.TO", _synth.chart("TECH.TO", p0=20, growth=0.3, currency="CAD"))  # no dividend
        W(off, "CUT.TO", _synth.chart("CUT.TO", p0=30, growth=-0.1, currency="CAD", divs=_synth.quarterly(
            "2024-11-01", "2026-05-01", 0.6) + [("2026-08-01", 0.3)]))
        W(off, "KO", _synth.chart("KO", p0=55, growth=0.2, wiggle=0.004,
                                  divs=_synth.quarterly("2021-12-01", "2026-09-01", 0.44, 0.01)))
        W(off, "BNS.TO", _synth.chart("BNS.TO", p0=60, growth=0.15, wiggle=0.004, currency="CAD",
                                       divs=_synth.quarterly("2021-10-28", "2026-07-28", 0.9, 0.012)))
        W(off, "USDCAD=X", _synth.chart("USDCAD=X", p0=1.38, n=22, wiggle=0, currency="CAD"))
        acc.write_json(self.paths.config, config())
        acc.write_json(self.paths.holdings("questrade"), {
            "account": "questrade", "cash": {"USD": 900, "CAD": 50}, "positions": [
                {"ticker": "NVDA", "shares": 60, "avg_cost": 50, "currency": "USD"},
                {"ticker": "AMD", "shares": 20, "avg_cost": 150, "currency": "USD"},
                {"ticker": "MSFT", "shares": 4, "avg_cost": 300, "currency": "USD"}]})
        acc.write_json(self.paths.holdings("wealthsimple"), {
            "account": "wealthsimple", "cash": {"CAD": 1500}, "positions": [
                {"ticker": "ENB.TO", "shares": 60, "avg_cost": 48, "currency": "CAD"},
                {"ticker": "TECH.TO", "shares": 20, "avg_cost": 20, "currency": "CAD"},
                {"ticker": "CUT.TO", "shares": 30, "avg_cost": 32, "currency": "CAD"},
                {"ticker": "KO", "shares": 10, "avg_cost": 55, "currency": "USD"}]})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(acc.main(["--dir", self.dir, "market", "--offline", off]), 0)
        self.cfg = acc.load_config(self.paths.config)
        self.market = acc.read_json(self.paths.market)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def review(self, **kw):
        return acc.review_all(self.cfg, self.paths, self.market, **kw)

    def acct(self, res, i):
        return {a["id"]: a for a in res["accounts"]}[i]

    def codes(self, a, t):
        return {f["code"] for p in a["positions"] if p["ticker"] == t for f in p["flags"]}

    def test_market_file_has_fx_and_every_symbol(self):
        self.assertAlmostEqual(self.market["fx"]["USDCAD"], 1.38, places=2)
        self.assertIn("BNS.TO", self.market["symbols"])  # watchlist names too

    def test_growth_account_trims_the_winner_and_flags_the_loser(self):
        q = self.acct(self.review(), "questrade")
        self.assertEqual(q["positions"][0]["ticker"], "NVDA")
        self.assertIn("over_cap", self.codes(q, "NVDA"))
        self.assertIn("stop", self.codes(q, "AMD"))
        sells = [o for o in q["proposals"] if o["side"] == "sell"]
        self.assertEqual([o["ticker"] for o in sells], ["NVDA"])
        self.assertEqual(sells[0]["shares"], int(sells[0]["shares"]))  # Questrade: whole shares
        self.assertGreater(q["positions"][0]["score"], q["positions"][-1]["score"])
        buys = [o["ticker"] for o in q["proposals"] if o["side"] == "buy"]
        self.assertNotIn("AMD", buys)  # never average down into a stop
        self.assertNotIn("NVDA", buys)

    def test_dividend_account_flags_and_income(self):
        w = self.acct(self.review(), "wealthsimple")
        self.assertIn("no_dividend", self.codes(w, "TECH.TO"))
        self.assertIn("div_cut", self.codes(w, "CUT.TO"))
        self.assertIn("withholding", self.codes(w, "KO"))
        self.assertIn("div_growth", self.codes(w, "ENB.TO"))
        ko = [p for p in w["positions"] if p["ticker"] == "KO"][0]
        self.assertAlmostEqual(ko["income_net_base"], ko["income_base"] * 0.85, places=1)
        self.assertGreater(w["income"], 0)
        buys = [o for o in w["proposals"] if o["side"] == "buy"]
        self.assertTrue(buys)
        self.assertTrue({o["ticker"] for o in buys} <= {"ENB.TO", "KO", "BNS.TO"}, buys)

    def test_rrsp_keeps_the_whole_us_dividend(self):
        self.cfg["accounts"][1]["type"] = "RRSP"
        w = self.acct(self.review(), "wealthsimple")
        ko = [p for p in w["positions"] if p["ticker"] == "KO"][0]
        self.assertEqual(ko["income_net_base"], ko["income_base"])
        self.assertNotIn("withholding", self.codes(w, "KO"))

    def test_contribution_goes_toward_the_target_mix(self):
        res = self.review(contribute=2000)
        before = {m["strategy"]: m["pct"] for m in res["mix"]}
        under = min(before, key=lambda s: before[s] - {"growth": 60, "dividend": 40}[s])
        top = max(res["contribution_split"], key=res["contribution_split"].get)
        self.assertEqual(self.acct(res, top)["strategy"], under)
        self.assertAlmostEqual(sum(res["contribution_split"].values()), 2000, places=0)

    def test_report_text_and_cli(self):
        text = acc.report(self.review())
        self.assertIn("Aggressive growth", text)
        self.assertIn("Steady dividend", text)
        self.assertIn("Not financial advice", text)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(acc.main(["--dir", self.dir, "review", "--write", "--json"]), 0)
        self.assertTrue(os.path.exists(self.paths.proposals))

    def test_snapshot_keeps_one_point_per_day(self):
        res = self.review()
        acc.snapshot(self.paths.history, res, "2026-10-15")
        acc.snapshot(self.paths.history, res, "2026-10-16")
        hist = acc.snapshot(self.paths.history, res, "2026-10-16")
        self.assertEqual([p["date"] for p in hist["points"]], ["2026-10-15", "2026-10-16"])

    def test_no_buy_takes_a_holding_past_the_cap(self):
        for contribute in (0, 5000, 50000):
            res = self.review(contribute=contribute)
            for a in res["accounts"]:
                new = res["contribution_split"].get(a["id"], 0)
                after = {p["ticker"]: p["value_base"] for p in a["positions"]}
                for o in a["proposals"]:
                    after[o["ticker"]] = after.get(o["ticker"], 0) + (1 if o["side"] == "buy" else -1) * o["value_base"]
                limit = (a["total"] + new) * a["cap_pct"] / 100 + 1
                for t in {o["ticker"] for o in a["proposals"] if o["side"] == "buy"}:
                    self.assertLessEqual(after[t], limit, "%s %s with %s new" % (a["id"], t, contribute))

    def test_few_holdings_get_an_equal_share_cap_not_forced_sells(self):
        r = acc.RULES["dividend"]
        self.assertEqual(acc.effective_cap(r, 20), 12)
        self.assertEqual(acc.effective_cap(r, 5), 19.6)

    def test_medium_term_strategy_sells_a_broken_trend(self):
        self.cfg["accounts"][0]["strategy"] = "medium"
        self.cfg["accounts"][0]["rules"] = dict(acc.RULES["medium"])
        q = self.acct(self.review(), "questrade")
        self.assertIn("trend_broken", self.codes(q, "AMD"))
        self.assertEqual(q["strategy_label"], "Medium term")


if __name__ == "__main__":
    unittest.main()
