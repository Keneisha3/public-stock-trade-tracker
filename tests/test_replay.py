import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import FIX, load
import _synth

replay = load("trader-replay", "replay")
ASOF = "2026-10-16"  # a Friday; _synth charts end here


def write_world(folder, end=_synth.END, crash_after=None):
    """Synthetic market + the real Pelosi filing of 2026-08-21 (BE and INTC buys)."""
    off = os.path.join(folder, "off")
    spec = {
        "SPY": dict(p0=500, growth=0.25, divs=_synth.quarterly("2024-12-20", "2026-09-19", 1.7)),
        "XIU.TO": dict(p0=35, growth=0.2, currency="CAD"),
        "AAA": dict(p0=100, growth=0.9),        # growth names
        "BBB": dict(p0=60, growth=0.4),
        "MMM": dict(p0=80, growth=0.3),         # medium
        "DIV.TO": dict(p0=40, growth=0.15, currency="CAD",
                       divs=_synth.quarterly("2023-01-15", "2026-10-15", 0.5, 0.01)),
        "BE": dict(p0=20, growth=0.8),
        "INTC": dict(p0=30, growth=0.2),
    }
    for sym, kw in spec.items():
        doc = _synth.chart(sym, n=520, wiggle=0.01, end=end, **kw)
        if crash_after:
            r = doc["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            for i, ts in enumerate(r["timestamp"]):
                if _synth.datetime.datetime.utcfromtimestamp(ts).date().isoformat() > crash_after:
                    for k in ("open", "high", "low", "close"):
                        q[k][i] = q[k][i] * 0.3
        _synth.write(off, sym, doc)
    _synth.write(off, "USDCAD=X", _synth.chart("USDCAD=X", p0=1.37, n=520, wiggle=0.002, currency="CAD", end=end))
    shutil.copy(os.path.join(FIX, "trader-pelosi", "2026FD.zip"), os.path.join(off, "2026FD.zip"))
    shutil.copy(os.path.join(FIX, "trader-pelosi", "ptr-20035143.txt"), os.path.join(off, "ptr-20035143.txt"))
    base = os.path.join(folder, "trader")
    os.makedirs(os.path.join(base, "paper"), exist_ok=True)
    with open(os.path.join(base, "accounts.json"), "w") as fh:
        json.dump({"accounts": [{"id": "q", "strategy": "growth", "watchlist": ["AAA", "BBB"]},
                                {"id": "m", "strategy": "medium", "watchlist": ["MMM", "AAA"]},
                                {"id": "w", "strategy": "dividend", "watchlist": ["DIV.TO"]}]}, fh)
    with open(os.path.join(base, "paper", "config.json"), "w") as fh:
        json.dump({"universe": ["AAA", "BBB", "MMM", "INTC"]}, fh)
    return base, off


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.base, cls.off = write_world(cls.dir)
        cls.out, cls.text = replay.replay(cls.base, ASOF, 100, skip=("crypto",), offline=cls.off, log=lambda m: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_windows_and_report(self):
        r = self.out["results"]
        self.assertEqual(list(r), ["6 months", "1 month", "2 weeks", "1 week"])
        self.assertEqual(r["1 week"]["start"], "2026-10-09")
        self.assertEqual(r["2 weeks"]["start"], "2026-10-02")
        for w in r.values():
            for k in ("growth", "medium", "dividend", "stock bot", "Pelosi copycat", "S&P 500 (SPY)", "cash"):
                self.assertIn(k, w)
        self.assertIn("Pelosi copycat (separate)", self.text)
        self.assertTrue(os.path.exists(os.path.join(self.base, "replay", "report.md")))

    def test_strategies_actually_invest(self):
        r = self.out["results"]["6 months"]
        self.assertGreater(r["growth"]["trades"], 0)
        self.assertTrue(r["growth"]["holdings"])
        self.assertGreater(r["dividend"]["dividends"], 0)  # quarterly payer held across ex-dates
        self.assertGreater(r["S&P 500 (SPY)"]["value"], 100)  # synthetic SPY rose
        bot = r["stock bot"]
        if bot["trades"] == 0:  # never traded: no FX round trip charged on money that never moved
            self.assertEqual((bot["value"], bot["fees"]), (100, 0.0))

    def test_pelosi_acts_only_after_the_filing_was_posted(self):
        six = self.out["results"]["6 months"]["Pelosi copycat"]
        self.assertEqual(six["filings_used"], ["2026-08-21"])
        self.assertEqual(sorted(six["basket"]), ["BE", "INTC"])
        one = self.out["results"]["1 month"]["Pelosi copycat"]  # filing was public before this start
        self.assertEqual(one["filings_used"], ["2026-08-21"])
        self.assertTrue(one["holdings"])

    def data(self):
        charts = {}
        for f in os.listdir(self.off):
            if f.startswith("chart-"):
                sym = f[6:-5]
                charts[sym] = replay.mk.get_chart(sym, offline=self.off)
        return replay.Data(charts, {})

    def test_pelosi_first_trade_date(self):
        d = self.data()
        filings, _ = replay.pelosi_filings([2026], offline=self.off)
        start = d.trading_day_on_or_before("2026-04-17")
        pf_out = replay.run_pelosi(d, filings, start, ASOF, 100)
        self.assertEqual(pf_out["filings_used"], ["2026-08-21"])
        # an order decided on the filing date fills at the next open, never the same day
        pf = replay.Portfolio(d, 100)
        orders = [{"side": "buy", "ticker": "BE", "cad": 50, "decided": "2026-08-21"}]
        for day in [x for x in d.days if x >= "2026-08-20"][:3]:
            orders = pf.fill(orders, day)
        self.assertEqual(pf.log[0]["day"], "2026-08-24")  # Aug 21 is a Friday: first open after is Monday

    def test_dividends_need_shares_before_the_ex_date(self):
        d = self.data()
        ex = [x for x, _ in d.charts["DIV.TO"]["dividends"] if x > "2026-06-01"][0]
        ex = d.trading_day_on_or_before(ex) if ex not in d.days else ex
        before = d.days[d.days.index(ex) - 1]
        early = replay.Portfolio(d, 100)
        early.fill([{"side": "buy", "ticker": "DIV.TO", "cad": 90, "decided": d.days[d.days.index(before) - 1]}], before)
        late = replay.Portfolio(d, 100)
        orders = [{"side": "buy", "ticker": "DIV.TO", "cad": 90, "decided": before}]
        for p, o in ((early, []), (late, orders)):
            p.pay_dividends(ex)
            p.fill(o, ex)
        self.assertGreater(early.dividends_cad, 0)
        self.assertEqual(late.dividends_cad, 0)

    def test_usd_costs_include_fx(self):
        d = self.data()
        pf = replay.Portfolio(d, 100)
        day = d.days[-10]
        pf.fill([{"side": "buy", "ticker": "AAA", "cad": 99, "decided": d.days[-11]}], day)
        self.assertGreater(pf.fees, 99 * 0.014)  # 1.5% conversion on the way in
        self.assertLess(pf.value(day), 100 * 0.99)


class Insights(unittest.TestCase):
    def test_notes_name_the_drivers(self):
        row = {"S&P 500 (SPY)": {"return_pct": 4.0}, "TSX 60 (XIU.TO)": {"return_pct": 2.0}, "cash": {"return_pct": 0},
               "growth": {"return_pct": 1.0, "fees": 3.1, "fx_fees": 3.0, "cash_drag_pct": 45, "trades": 4,
                          "contrib": [{"ticker": "AAA", "pnl": 2.5}, {"ticker": "BBB", "pnl": -1.2}]},
               "dividend": {"return_pct": 3.0, "fees": 0.1, "dividends": 0.8, "trades": 2, "contrib": []},
               "crypto team": {"return_pct": -3.0, "trades": 12, "win_rate_pct": 25, "fees": 2.0,
                               "exit_reasons": {"stop-loss": 9, "take-profit": 2}}}
        n = replay.insights(row, {"usdcad_pct": 1.2}, 100)
        g = " ".join(n["growth"]["not_going_well"])
        self.assertIn("trailed the S&P 500 by 3.0 points", g)
        self.assertIn("worst holding: BBB", g)
        self.assertIn("costs took 3.1%", g)
        self.assertIn("sat 45% in cash", g)
        self.assertIn("best holding: AAA", " ".join(n["growth"]["going_well"]))
        self.assertIn("lifted US holdings", " ".join(n["growth"]["going_well"]))
        self.assertIn("beat the TSX 60", " ".join(n["dividend"]["going_well"]))
        self.assertIn("collected $0.80 in dividends", " ".join(n["dividend"]["going_well"]))
        self.assertIn("stops too tight", " ".join(n["crypto team"]["not_going_well"]))
        self.assertNotIn("cash", n)

    def test_report_has_curves_contributions_and_notes(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None)
        finally:
            shutil.rmtree(d)
        six = out["results"]["6 months"]
        self.assertEqual(six["growth"]["curve"][0][0], six["start"])
        self.assertEqual(six["growth"]["curve"][-1], [ASOF, six["growth"]["value"]])
        self.assertTrue(six["growth"]["contrib"])
        self.assertIn("spy_pct", six["factors"])
        self.assertIn("growth", six["insights"])
        self.assertIn("What is going well, what is not", text)
        self.assertIn("growth", out["overall"])


class NoLookahead(unittest.TestCase):
    def test_identical_results_with_a_different_future(self):
        """Same past, different future: every number up to the as-of date is identical."""
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            base_a, off_a = write_world(a)
            base_b, off_b = write_world(b)
            out_a, _ = replay.replay(base_a, ASOF, 100, skip=("crypto",), offline=off_a, log=lambda m: None)
            for f in os.listdir(off_b):  # world B: same past, then 20 days of prices collapsing 80%
                if f.startswith("chart-"):
                    with open(os.path.join(off_b, f)) as fh:
                        doc = json.load(fh)
                    r = doc["chart"]["result"][0]
                    q = r["indicators"]["quote"][0]
                    last_ts = r["timestamp"][-1]
                    for i in range(1, 21):
                        r["timestamp"].append(last_ts + i * 86400)
                        for k in ("open", "high", "low", "close"):
                            q[k].append(q[k][-1] * 0.92)
                        q["volume"].append(1)
                    r["meta"]["regularMarketPrice"] = q["close"][-1]
                    r["meta"]["regularMarketTime"] = r["timestamp"][-1]
                    with open(os.path.join(off_b, f), "w") as fh:
                        json.dump(doc, fh)
            out_b, _ = replay.replay(base_b, ASOF, 100, skip=("crypto",), offline=off_b, log=lambda m: None)
        finally:
            shutil.rmtree(a)
            shutil.rmtree(b)
        for w in out_a["results"]:  # values, curves, holdings, fills, insights, factors: all identical
            for k, va in out_a["results"][w].items():
                self.assertEqual(va, out_b["results"][w][k], "%s %s" % (w, k))


class Crypto(unittest.TestCase):
    def test_crypto_window_runs_on_closed_bars(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            t1 = replay.market_close_utc(ASOF)
            n = 4 * 24 * 24  # 24 days of 15-minute bars
            steps = ([0.0015] * 120 + [-0.002] * 12 + [0.002] * 60) * 20
            for c in ("BTC", "ETH"):
                bars, px = [], 100.0
                for i in range(n):
                    o = px
                    px *= 1 + steps[i % len(steps)]
                    t = t1 - (n - i) * 900
                    bars.append({"t": t, "o": o, "h": max(o, px) * 1.001, "l": min(o, px) * 0.999, "c": px, "v": 5})
                with open(os.path.join(off, "candles-%s.json" % c), "w") as fh:
                    json.dump(bars, fh)
            out, text = replay.replay(base, ASOF, 100, skip=("pelosi",), offline=off, log=lambda m: None)
        finally:
            shutil.rmtree(d)
        one = out["results"]["1 week"]["crypto team"]
        self.assertIn("value", one)
        self.assertIsNotNone(out["results"]["1 week"]["Bitcoin (hold)"])
        self.assertIn("Crypto bot team", text)


if __name__ == "__main__":
    unittest.main()
