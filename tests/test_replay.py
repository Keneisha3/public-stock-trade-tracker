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
        "SPY": dict(p0=500, growth=0.25, divs=_synth.quarterly("2024-12-20", "2026-09-19", 1.7),
                    gaps={461: -7, 481: 5}),  # a sell-off in late August, half recovered in September
        "^VIX": dict(p0=15, growth=0.0, wiggle=0.03, gaps={460: 140, 480: -58}),  # fear spikes the day before
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
        kw.setdefault("wiggle", 0.01)
        doc = _synth.chart(sym, n=520, end=end, **kw)
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


def fake_universe(days):
    """AAA and MMM in the index all along, BBB joins on day 450, INTC leaves on day 400."""
    return replay.univ.Universe({"licence": "test", "last_snapshot": days[-1], "members": {
        "AAA": [["2014-01-01", None]], "MMM": [["2014-01-01", None]], "BBB": [[days[450], None]],
        "INTC": [["2014-01-01", days[400]]], "BE": [["2014-01-01", None]]}})


def load_data(off):
    charts = {f[6:-5]: replay.mk.get_chart(f[6:-5], offline=off) for f in os.listdir(off) if f.startswith("chart-")}
    return replay.Data(charts, {})


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.base, cls.off = write_world(cls.dir)
        cls.out, cls.text = replay.replay(cls.base, ASOF, 100, skip=("crypto",), offline=cls.off, log=lambda m: None, mc_runs=200, rolling_spec=None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_windows_and_report(self):
        r = self.out["results"]
        self.assertEqual(list(r), ["12 months", "6 months", "3 months", "1 month", "2 weeks", "1 week"])
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
        self.assertEqual(bot["fx_fees"], 0.0)  # US-dollar cash for a US-stock bot: nothing converted
        if bot["trades"] == 0:  # never traded: its US dollars only moved with USD/CAD
            d = self.data()
            self.assertAlmostEqual(bot["value"], 100 * d.fx(ASOF) / d.fx(r["start"]), delta=0.02)

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

    def test_each_currency_trades_in_its_own_cash(self):
        d = self.data()
        day, before = d.days[-10], d.days[-11]
        usd = replay.Portfolio(d, 100, split={"USD": 1.0}, start=before)
        usd.fill([{"side": "buy", "ticker": "AAA", "cad": 99, "decided": before}], day)
        self.assertEqual(usd.fx_fees, 0.0)  # US stock, US dollars: no conversion
        self.assertEqual(usd.pos["AAA"]["currency"], "USD")
        usd.fill([{"side": "sell", "ticker": "AAA", "shares": usd.pos["AAA"]["shares"], "decided": day}], d.days[-9])
        self.assertEqual(usd.fx_fees, 0.0)  # sold back into US dollars, not converted to CAD
        self.assertGreater(usd.cash_by["USD"], 0)
        self.assertLess(usd.cash_by["CAD"], 1e-9)
        cad = replay.Portfolio(d, 100)  # only Canadian dollars: buying a US stock forces a conversion
        cad.fill([{"side": "buy", "ticker": "AAA", "cad": 99, "decided": before}], day)
        self.assertGreater(cad.fx_fees, 99 * 0.014)
        self.assertLess(cad.value(day), 100 * 0.99)
        mixed = replay.Portfolio(d, 100, split={"USD": 1, "CAD": 1}, start=before)
        mixed.fill([{"side": "buy", "ticker": "AAA", "cad": 49, "decided": before},
                    {"side": "buy", "ticker": "DIV.TO", "cad": 49, "decided": before}], day)
        self.assertEqual(mixed.fx_fees, 0.0)
        self.assertEqual(sorted(mixed.pos), ["AAA", "DIV.TO"])


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
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
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


class MonteCarlo(unittest.TestCase):
    def test_bootstrap_is_reproducible_and_sane(self):
        up = [["d%03d" % i, 100 * 1.001 ** i] for i in range(120)]           # steady riser
        flat = [["d%03d" % i, 100.0] for i in range(120)]                    # cash
        wobble = [["d%03d" % i, 100 * (1 + 0.02 * ((-1) ** i))] for i in range(120)]
        curves = {"S&P 500 (SPY)": wobble, "growth": up, "cash": flat}
        a = replay.monte_carlo(curves, runs=400, horizon=60)
        b = replay.monte_carlo(curves, runs=400, horizon=60)
        self.assertEqual(a, b)  # seeded: same answer every time
        g = a["strategies"]["growth"]
        self.assertEqual(g["prob_profit_pct"], 100.0)
        self.assertAlmostEqual(g["median"], 100 * 1.001 ** 60, places=1)
        self.assertLessEqual(g["p5"], g["median"])
        self.assertLessEqual(g["median"], g["p95"])
        self.assertEqual(a["strategies"]["cash"]["median"], 100.0)
        self.assertEqual(a["strategies"]["cash"]["prob_profit_pct"], 0.0)
        self.assertIsNone(a["strategies"]["S&P 500 (SPY)"]["prob_beat_bench_pct"])
        self.assertEqual(g["fan"][0][1:], [100.0, 100.0, 100.0])

    def test_risk_stats(self):
        dip = [["d%02d" % i, v] for i, v in enumerate([100, 110, 99, 105] + [105 + i for i in range(20)])]
        r = replay.risk_stats(dip)
        self.assertEqual(r["max_dd_pct"], -10.0)
        self.assertGreater(r["sharpe"], 0)
        self.assertIsNone(replay.risk_stats(dip[:5]))

    def test_replay_report_includes_monte_carlo(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
        finally:
            shutil.rmtree(d)
        self.assertIn("growth", out["monte_carlo"]["strategies"])
        self.assertIn("risk", out["results"]["12 months"]["growth"])  # risk stats on the longest window
        self.assertIn("## Monte Carlo", text)


class Settings(unittest.TestCase):
    def test_check_rules(self):
        acc = replay.acc
        self.assertEqual(acc.check_rules("growth", {"momentum_months": "3", "max_position_pct": 30}),
                         {"momentum_months": 3, "max_position_pct": 30.0})
        for bad in ({"momentum_months": 5}, {"max_position_pct": 90}, {"min_yield_pct": 3}, {"leverage": 2},
                    {"stop_loss_pct": "lots"}):
            with self.assertRaises(acc.AccountsError):
                acc.check_rules("growth", bad)
        self.assertEqual(acc.check_rules("dividend", {"min_yield_pct": 3.5}), {"min_yield_pct": 3.5})

    def test_momentum_lookback_changes_the_score(self):
        m = {"ret_1m": 1, "ret_3m": 15, "ret_6m": 2, "ret_12m": -5, "above_sma200": True, "off_high_pct": -5}
        long = replay.acc.score("growth", m, {"momentum_months": 12})
        short = replay.acc.score("growth", m, {"momentum_months": 3})
        self.assertGreater(short, long)  # a hot 3 months counts for more with a short lookback
        self.assertEqual(replay.acc.score("growth", m), long)  # default is 12 months

    def test_rebalance_every(self):
        days = ["2026-%02d-%02d" % (mo, d) for mo in range(4, 10) for d in (1, 8, 15, 22, 29)]
        weekly = replay._review_days(days, days[0], days[-1], 7)
        monthly = replay._review_days(days, days[0], days[-1], 28)
        self.assertGreater(len(weekly), len(monthly))
        self.assertIn(days[0], monthly)

    def test_scenarios_show_inputs_and_outputs(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            with open(os.path.join(base, "accounts.json")) as fh:
                cfg = json.load(fh)
            cfg["accounts"][0]["rules"] = {"momentum_months": 3, "max_position_pct": 40}
            with open(os.path.join(base, "accounts.json"), "w") as fh:
                json.dump(cfg, fh)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
        finally:
            shutil.rmtree(d)
        sc = {x["name"]: x for x in out["scenarios"]}
        self.assertIn("Your settings (q)", sc)
        self.assertEqual(sc["Your settings (q)"]["inputs"], {"momentum_months": 3, "max_position_pct": 40})
        conc = sc["Concentrated: 40% cap, 3+ names"]
        div = sc["Diversified: 10% cap, 10+ names"]
        self.assertEqual(conc["settings"]["max_position_pct"], 40)
        self.assertNotEqual(conc["results"]["6 months"]["value"], div["results"]["6 months"]["value"])
        self.assertEqual(set(conc["results"]), {"12 months", "6 months", "3 months", "1 month", "2 weeks", "1 week"})
        self.assertIn("## Scenarios", text)

    def test_monte_carlo_leaves_out_short_histories(self):
        long = [["d%03d" % i, 100 * 1.001 ** i] for i in range(120)]
        out = {"6 months": {"start": "x", "S&P 500 (SPY)": {"curve": long, "return_pct": 1},
                            "growth": {"curve": long, "return_pct": 1},
                            "crypto team": {"curve": long[:30], "return_pct": 1}}}
        curves, short = replay.mc_curves(out["6 months"])
        self.assertEqual(short, ["crypto team"])
        self.assertEqual(sorted(curves), ["S&P 500 (SPY)", "growth"])
        mc = replay.monte_carlo(curves, runs=100, horizon=40)
        self.assertEqual(mc["sample_days"], 119)  # the full 6 months, not the short curve's 29 days


class Vix(unittest.TestCase):
    def test_regimes_and_rules(self):
        v = replay.vix
        self.assertEqual([v.regime(x) for x in (12, 17, 25, 40)], ["calm", "normal", "nervous", "fear"])
        self.assertEqual(v.decide([14, 31])[0], False)  # default: out above 30
        self.assertEqual(v.decide([14, 30])[0], True)
        self.assertEqual(v.decide([14, 26], {"threshold": 25})[0], False)
        self.assertEqual(v.decide([30] * 49 + [29], {"mode": "trend", "days": 50})[0], True)
        self.assertEqual(v.decide([20] * 49 + [22], {"mode": "trend", "days": 50})[0], False)
        self.assertEqual(v.decide([18, 22], {"mode": "term"}, [20, 23])[0], True)   # calm shape
        self.assertEqual(v.decide([18, 24], {"mode": "term"}, [20, 23])[0], False)  # stress: backwardation
        self.assertEqual(v.decide([18, 24], {"mode": "term"})[0], True)  # no 3-month data: stay in
        st = v.status([{"d": "2026-10-15", "c": 18.0}, {"d": "2026-10-16", "c": 27.0}])
        self.assertEqual((st["regime"], st["risk_on"], st["agent"]), ("nervous", True, "hold the Nasdaq 100"))
        self.assertEqual(st["day_change_pct"], 50.0)
        st = v.status([{"d": "2026-10-15", "c": 18.0}, {"d": "2026-10-16", "c": 27.0}], {"threshold": 25, "asset": "SPY"})
        self.assertEqual((st["risk_on"], st["agent"]), (False, "step aside to cash"))
        self.assertEqual(v.status([{"d": "2026-10-16", "c": 12.0}], {"asset": "SPY"})["agent"], "hold the S&P 500")

    def test_agent_steps_aside_during_the_spike(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
            days = load_data(off).days
        finally:
            shutil.rmtree(d)
        six = out["results"]["6 months"]
        agent, spy = six["VIX agent"], six["S&P 500 (SPY)"]
        self.assertGreaterEqual(agent["switches"], 2)          # out at the spike, back in after it
        self.assertLess(agent["risk_on_days_pct"], 100)
        self.assertGreater(agent["value"], spy["value"])       # it dodged the sell-off
        sells = [f for f in agent["fills"] if f["side"] == "sell"]
        self.assertEqual(sells[0]["day"], days[461])  # VIX spiked at the close of day 460: out at the next open
        self.assertIn("vix_end", six["factors"])
        self.assertIn("calm", six["S&P 500 (SPY)"]["vix_regimes"])
        self.assertIn("## By VIX regime", text)
        self.assertTrue(any(x["strategy"] == "vix" for x in out["scenarios"]))

    def test_risk_off_cancels_a_waiting_buy(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
            days = data.days
            spike = days[460]
            # start the day of the spike: decided risk-off at that close, so never buys
            r = replay.run_vix_agent(data, spike, days[465], 100)
        finally:
            shutil.rmtree(d)
        self.assertEqual(r["trades"], 0)
        self.assertAlmostEqual(r["value"], 100 * data.fx(days[465]) / data.fx(spike), delta=0.02)  # US-dollar cash

    def test_switches_stay_in_us_dollars(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
            r = replay.run_vix_agent(data, data.days[400], data.days[519], 100)
        finally:
            shutil.rmtree(d)
        self.assertGreaterEqual(r["switches"], 2)
        self.assertEqual(r["fx_fees"], 0)
        self.assertEqual(r["cash_by"]["CAD"], 0)


class AgentVariants(unittest.TestCase):
    def test_pelosi_keep_every_buy(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        filings = [("2026-06-01", [{"ticker": "BE", "type": "P"}, {"ticker": "INTC", "type": "P"}]),
                   ("2026-08-03", [{"ticker": "BE", "type": "S"}])]
        start = data.trading_day_on_or_before("2026-05-15")
        mirror = replay.run_pelosi(data, filings, start, ASOF, 100)
        hold = replay.run_pelosi(data, filings, start, ASOF, 100, mode="hold")
        self.assertEqual(mirror["basket"], ["INTC"])
        self.assertEqual(sorted(hold["basket"]), ["BE", "INTC"])

    def test_every_agent_has_scenarios(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            _synth.write(off, "QQQ", _synth.chart("QQQ", p0=400, growth=0.3, wiggle=0.01, n=520))
            _synth.write(off, "^VIX3M", _synth.chart("^VIX3M", p0=17, growth=0.0, wiggle=0.01, n=520))
            t1 = replay.market_close_utc(ASOF)
            for c in ("BTC", "ETH"):
                bars, px = [], 100.0
                for i in range(420):  # 420 days of daily bars
                    o, px = px, px * (1.01 if (i // 20) % 3 else 0.985)
                    bars.append({"t": t1 - (420 - i) * 86400, "o": o, "h": max(o, px) * 1.01,
                                 "l": min(o, px) * 0.99, "c": px, "v": 5})
                with open(os.path.join(off, "candles-%s-1440.json" % c), "w") as fh:
                    json.dump(bars, fh)
            out, text = replay.replay(base, ASOF, 100, offline=off, log=lambda m: None, mc_runs=100,
                                      rolling_spec=None, windows=replay.parse_windows("6m,1m"))
        finally:
            shutil.rmtree(d)
        kinds = {x["strategy"] for x in out["scenarios"]}
        self.assertTrue({"growth", "medium", "dividend", "stock bot", "vix", "pelosi", "crypto"} <= kinds, kinds)
        daily = [x for x in out["scenarios"] if x["name"] == "Crypto team: 1-day bars (default)"][0]
        self.assertIsNotNone(daily["results"]["6 months"])
        bot = {x["name"]: x for x in out["scenarios"] if x["strategy"] == "stock bot"}
        self.assertIn("SPY", bot["Stock bot: trades + idle cash in SPY"]["results"]["6 months"]["holdings"])
        self.assertIn("QQQ", bot["Stock bot: trades + idle cash in QQQ (default)"]["results"]["6 months"]["holdings"])
        self.assertIn("Nasdaq 100 (QQQ)", out["results"]["6 months"])
        self.assertIn("| crypto | Crypto team: 1-day bars (default) |", text)


    def test_a_kill_switch_leaves_flat_cash_to_the_end(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
            t1 = replay.market_close_utc(ASOF)
            candles = {"BTC": [{"t": t1 - (300 - i) * 86400, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 1}
                               for i in range(300)]}
            calls = []
            real = replay.team.cycle

            def cycle(state, window, now, broker, cfg, paths, log=print):
                calls.append(now)
                rep = real(state, window, now, broker, cfg, paths, log)
                if len(calls) == 20:
                    rep["killed"] = "test"
                return rep
            replay.team.cycle = cycle
            try:
                start = data.trading_day_on_or_before("2026-07-17")
                r = replay.run_crypto(candles, data, start, ASOF, 100, os.path.join(d, "w"))
            finally:
                replay.team.cycle = real
        finally:
            shutil.rmtree(d)
        self.assertEqual(r["killed"], "test")
        self.assertEqual(r["curve"][-1][0], ASOF)  # flat cash after the kill, not a curve that stops


class PointInTimeUniverse(unittest.TestCase):
    def test_membership_spans(self):
        doc = replay.univ.build("date,tickers\n2013-06-03,\"AAA,BRK.B\"\n2015-01-05,\"AAA,BRK.B,CCC\"\n"
                                "2016-03-01,\"BRK.B,CCC\"\n")
        u = replay.univ.Universe(doc)
        self.assertEqual(sorted(u.members_on("2014-06-01")), ["AAA", "BRK-B"])
        self.assertEqual(sorted(u.members_on("2015-06-01")), ["AAA", "BRK-B", "CCC"])
        self.assertEqual(sorted(u.members_on("2016-03-01")), ["BRK-B", "CCC"])  # AAA left that day
        self.assertEqual(u.ever("2016-06-01", "2016-12-31"), ["BRK-B", "CCC"])
        real = replay.univ.load()
        self.assertGreater(len(real.members_on("2020-03-20")), 490)
        self.assertNotIn("TSLA", real.members_on("2020-06-01"))  # joined in December 2020
        self.assertIn("TSLA", real.members_on("2021-06-01"))

    def test_never_picks_a_stock_before_it_joined_or_after_it_left(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
            uni = fake_universe(data.days)
            join, left = data.days[450], data.days[400]
            for st in ("growth", "medium"):
                r = replay.run_account(data, st, [], data.days[300], ASOF, 100, "TFSA", uni=uni)
                self.assertTrue(r["fills"], st)
                for f in r["fills"]:
                    if f["side"] == "buy":
                        self.assertFalse(f["ticker"] == "BBB" and f["day"] <= join, f)
                        self.assertFalse(f["ticker"] == "INTC" and f["day"] > left, f)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto", "pelosi"), offline=off, log=lambda m: None,
                                      mc_runs=100, rolling_spec=None, uni=uni)
        finally:
            shutil.rmtree(d)
        six = out["results"]["6 months"]
        self.assertEqual(six["coverage"]["members"], 4)  # AAA, MMM, BBB, BE (INTC has left)
        self.assertIn("**Universe:**", text)
        names = {x["name"] for x in out["scenarios"]}
        self.assertIn("Today's hand-picked watchlist (hindsight)", names)
        self.assertIn("Stock bot: today's 30 hand-picked large caps (hindsight)", names)
        self.assertTrue(any(c["name"].startswith("point-in-time universe") for c in out["checks"]))

    def test_scanner_ranks_by_momentum_above_the_trend(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        uni = fake_universe(data.days)
        top = replay.shortlist(data, "growth", data.days[500], {"momentum_months": 3}, uni, k=2)
        q = {s: data.quick(s, data.days[500], 63) for s in top}
        self.assertEqual(len(top), 2)
        self.assertTrue(all(x["above200"] for x in q.values()))
        self.assertGreaterEqual(q[top[0]]["ret"], q[top[1]]["ret"])
        self.assertIsNone(data.quick("BBB", data.days[150], 63))  # under 200 days of history


    def test_momentum_agent_holds_the_strongest_members_only(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        uni = fake_universe(data.days)
        r = replay.run_momentum(data, uni, data.days[300], ASOF, 100, n=2)
        self.assertTrue(r["fills"])
        for day, picks in r["picks"]:
            self.assertLessEqual(len(picks), 2)
            members = uni.members_on(day)
            self.assertTrue(all(t in members for t in picks), (day, picks))
        for f in r["fills"]:
            self.assertFalse(f["side"] == "buy" and f["ticker"] == "BBB" and f["day"] <= data.days[450], f)
        self.assertEqual(r["cash_by"]["CAD"], 0)  # US stocks, US dollars

    def test_dual_momentum_falls_back_to_bonds(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            for sym, g in (("XLK", 0.6), ("XLE", -0.5), ("SHY", 0.02), ("IEF", 0.03)):
                _synth.write(off, sym, _synth.chart(sym, p0=50, growth=g, wiggle=0.005, n=520))
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        r = replay.run_dual(data, data.days[300], ASOF, 100, k=3)
        last = r["picks"][-1][1]
        self.assertEqual(sorted(last), ["IEF", "SPY", "XLK"])  # XLE is under the short-bond hurdle: its share goes to IEF
        one = replay.run_dual(data, data.days[300], ASOF, 100)  # default: the single best fund
        self.assertEqual(len(one["picks"][-1][1]), 1)
        core = replay.run_dual(data, data.days[300], ASOF, 100, core="IEF", core_weight=0.7)
        self.assertEqual(sorted(core["picks"][-1][1]), ["IEF", "XLK"])  # 70% core + the best fund
        calm = replay.run_dual(data, data.days[300], ASOF, 100, vol_target=1)  # a tiny target: mostly bonds
        self.assertIn("IEF", calm["picks"][-1][1])
        self.assertIn("XLK", calm["picks"][-1][1])
        held = {h: 1 for h in calm["holdings"]}
        self.assertIn("IEF", held)
        w = replay.dual_weights(data, data.days[500], core="XLE", core_weight=0.7, core_trend=True)
        self.assertNotIn("XLE", w)                      # the core is under its 200-day: its share sits in bonds
        self.assertAlmostEqual(w["IEF"], 0.7, places=6)
        w = replay.dual_weights(data, data.days[500], core="XLK", core_weight=0.7, core_trend=True)
        self.assertAlmostEqual(w["XLK"], 1.0, places=6)  # above its 200-day: 70% core + it is also the best fund
        blended = replay.dual_weights(data, data.days[500], k=3, lookbacks=[1, 3, 6, 12])
        self.assertEqual(sorted(blended), ["IEF", "SPY", "XLK"])
        trend = replay.run_dual(data, data.days[300], ASOF, 100, k=3, trend=True)
        self.assertNotIn("XLE", trend["picks"][-1][1])
        self.assertIn("XLK", r["holdings"])
        self.assertNotIn("XLE", r["holdings"])

    def test_signal_baskets_wait_for_the_filing_and_membership(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        uni = fake_universe(data.days)
        filed, bbb_filed = data.days[350], data.days[440]
        sig = replay.sigs.Signals(
            insiders={"rows": [[filed, "AAA", "1", "officer", 10, 100, 1000], [filed, "AAA", "2", "director", 5, 100, 500],
                               [bbb_filed, "BBB", "3", "officer", 10, 60, 600], [bbb_filed, "BBB", "4", "other", 10, 60, 600],
                               [filed, "ZZZ", "5", "officer", 1, 1, 1], [filed, "ZZZ", "6", "officer", 1, 1, 1]]},
            congress={"rows": [[filed, "Ann A", "MMM", "buy", 1001, 15000, filed, "self"],
                               [filed, "Ben B", "MMM", "buy", 1001, 15000, filed, "self"]]})
        r = replay.run_signals(data, uni, sig, data.days[300], ASOF, 100, n=3, every=7)
        for day, picks in r["picks"]:
            names = set(picks) - {"SPY"}
            self.assertTrue(names <= {"AAA", "BBB"}, picks)       # ZZZ is not an index member
            if day < filed:
                self.assertEqual(names, set())                    # nothing public yet: all in SPY
            if "BBB" in names:
                self.assertGreaterEqual(day, data.days[450])       # filed before it joined: only once a member
        c = replay.run_signals(data, uni, sig, data.days[300], data.days[400], 100, source="congress", n=2, every=7)
        self.assertTrue(any("MMM" in p for _, p in c["picks"]))
        m = replay.run_momentum_signals(data, uni, sig, data.days[300], ASOF, 100, n=2)
        self.assertTrue(all(set(p) - {"SPY"} <= {"AAA", "BBB", "MMM"} for _, p in m["picks"]))

    def test_blend_is_the_sum_of_its_parts(self):
        a = {"curve": [["d1", 50.0], ["d2", 60.0]], "holdings": ["X"], "trades": 1, "fees": 0.2}
        b = {"curve": [["d1", 50.0], ["d2", 40.0]], "holdings": ["Y"], "trades": 2, "fees": 0.4}
        r = replay.blend([a, b, None], 100)
        self.assertEqual(r["curve"], [["d1", 50.0], ["d2", 50.0]])  # two halves of $100: averages of $100 runs
        self.assertEqual((r["return_pct"], r["holdings"], r["trades"]), (-50.0, ["X", "Y"], 3))
        self.assertIsNone(replay.blend([None], 100))

    def test_walk_forward_keeps_the_last_year_out_of_training(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("walkforward", os.path.join(FIX, "..", "..", "scripts", "walkforward.py"))
        wf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wf)

        def rep(asof, rets, spy, sc=None):
            res = {w: {"growth": {"return_pct": g}, "S&P 500 (SPY)": {"return_pct": s},
                       "coverage": {"priced": 480, "members": 503}} for w, g, s in zip(
                ["24 months", "12 months", "6 months", "1 month"], rets, spy)}
            return {"asof": asof, "windows": list(res), "checks": [{"name": "x", "ok": True}], "results": res,
                    "scenarios": [{"strategy": "growth", "name": "A", "risk": {"max_dd_pct": -20.0},
                                   "results": {w: {"return_pct": g + 1} for w, g in zip(res, rets)}}]}
        reports = [rep("2026-10-16", [30, 20, 9, 1], [25, 10, 5, 2]), rep("2020-10-16", [30, 1, 1, 1], [12, 1, 1, 1]),
                   rep("2022-10-14", [-10, 1, 1, 1], [-15, 1, 1, 1]), rep("2025-12-19", [5, 5, 5, 5], [1, 1, 1, 1])]
        train, last, cut = wf.split(reports)
        self.assertEqual([r["asof"] for r in train], ["2020-10-16", "2022-10-14"])  # 2025-12 is inside the test year
        self.assertEqual((last["asof"], cut), ("2026-10-16", "2025-10-16"))
        text = wf.table(reports)
        self.assertIn("| Growth (Questrade) | +30.0% (+18.0) | -10.0% (+5.0) | 2 of 2 | +11.5 pts |", text)
        self.assertIn("| Growth (Questrade) | +20.0% (+10.0) | +9.0% (+4.0) | +1.0% (-1.0) |", text)  # the held-out test
        self.assertIn("| growth | A | +12.5 pts | -20.0% | +11.0 pts |", text)  # chosen on training, checked on the last year
        self.assertIn("480 of 503 index members priced", text)


class ForwardRecord(unittest.TestCase):
    def test_record_grows_and_never_rewrites_a_day(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            for sym, g in (("XLK", 0.6), ("IEF", 0.03), ("SHY", 0.02), ("QQQ", 0.4)):
                _synth.write(off, sym, _synth.chart(sym, p0=50, growth=g, wiggle=0.005, n=520))
            days = load_data(off).days
            plan = {"start": days[480], "cash": 100.0, "strategies": {
                "Dual": {"kind": "dual", "opts": {}}, "Nasdaq 100 (QQQ)": {"kind": "hold", "weights": {"QQQ": 1.0}}}}
            rec = replay.forward(plan, None, offline=off, today=days[500], log=lambda m: None)
            self.assertEqual(sorted(rec["days"])[0], days[480])
            self.assertEqual(sorted(rec["days"])[-1], days[500])
            frozen = json.loads(json.dumps(rec["days"]))
            plan["strategies"]["Dual"]["opts"] = {"k": 3}  # even if the code or settings change later...
            rec = replay.forward(plan, rec, offline=off, today=days[510], log=lambda m: None)
            early = replay.forward(dict(plan, start=days[510]), None, offline=off, today=days[509], log=lambda m: None)
            self.assertEqual(early["days"], {})          # the start's prices are not out yet: nothing recorded
            bad = {"start": days[505], "plan": plan, "days": {days[504]: {"Dual": 100.0}}}
            fixed = replay.forward(dict(plan, start=days[505]), bad, offline=off, today=days[506], log=lambda m: None)
            self.assertEqual(min(fixed["days"]), days[505])  # a day before the plan existed is dropped
            plan2 = dict(plan, start=days[505])  # a new plan starts a new record and archives the old one untouched
            rec2 = replay.forward(plan2, json.loads(json.dumps(rec)), offline=off, today=days[510], log=lambda m: None)
        finally:
            shutil.rmtree(d)
        for day, vals in frozen.items():
            self.assertEqual(rec["days"][day], vals)  # ...days already recorded stay exactly as they were
        self.assertEqual(sorted(rec["days"])[-1], days[510])
        self.assertEqual(rec["targets"]["Nasdaq 100 (QQQ)"], {"QQQ": 1.0})
        self.assertAlmostEqual(sum(rec["targets"]["Dual"].values()), 1.0, places=3)  # today's weights, for the review
        self.assertIn("Live paper record since", replay.render_forward(rec))
        with open(replay.FORWARD_PLAN) as fh:
            real = json.load(fh)
        self.assertIn("S&P 500 (SPY)", real["strategies"])
        self.assertEqual(sum("(chosen)" in k for k in real["strategies"]), 1)
        self.assertEqual(sorted(rec2["days"])[0], days[505])
        self.assertEqual(rec2["earlier"][0]["days"], rec["days"])


class CongressRecords(unittest.TestCase):
    def test_members_are_judged_only_on_outcomes_known_at_the_time(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        days = data.days
        rows = []
        for i in range(100, 400, 20):  # Good keeps buying the strong stock, Bad the weak one
            rows += [[days[i], "Good", "AAA", "buy", 15001, 50000, days[i], "self"],
                     [days[i], "Bad", "INTC", "buy", 15001, 50000, days[i], "self"]]
        sig = replay.sigs.Signals(congress={"rows": rows})
        rec = replay.member_records(data, sig, days[420])
        self.assertGreater(rec["Good"], rec["Bad"])
        early = replay.member_records(data, sig, days[150])  # only one buy each has a known outcome by then
        self.assertEqual(early, {})
        uni = fake_universe(days)
        r = replay.run_signals(data, uni, sig, days[300], days[420], 100, source="congress", weighted=True, n=2,
                               every=7)
        self.assertTrue(any("AAA" in p for _, p in r["picks"]))


class NewsAndPlan(unittest.TestCase):
    def world(self, d):
        base, off = write_world(d)
        _synth.write(off, "ERN", _synth.chart("ERN", p0=50, growth=0.1, wiggle=0.003, n=520, gaps={450: 9}))
        for sym, g in (("XLK", 0.6), ("IEF", 0.03), ("SHY", 0.02), ("QQQ", 0.4)):
            _synth.write(off, sym, _synth.chart(sym, p0=50, growth=g, wiggle=0.005, n=520))
        data = load_data(off)
        members = {t: [["2014-01-01", None]] for t in ("AAA", "BBB", "MMM", "BE", "ERN")}
        uni = replay.univ.Universe({"licence": "t", "last_snapshot": data.days[-1], "members": members})
        days = data.days
        sig = replay.sigs.Signals(events={"rows": [[days[450], "ERN", "2.02,9.01", days[449]],
                                                   [days[300], "BBB", "5.02", days[300]]]})
        return base, off, data, uni, sig

    def test_earnings_drift_waits_for_the_reaction(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        self.assertEqual(replay.pead_pick(data, uni, sig, days[449]), [])   # filed after the close: not yet
        self.assertEqual(replay.pead_pick(data, uni, sig, days[450]), ["ERN"])  # the jump is known at this close
        self.assertEqual(replay.pead_pick(data, uni, sig, days[450], min_move=20.0), [])
        self.assertEqual(replay.pead_pick(data, uni, sig, days[515]), [])   # more than 60 days later
        r = replay.run_events(data, uni, sig, days[440], days[480], 100, n=2)
        self.assertTrue(any(f["ticker"] == "ERN" and f["day"] > days[450] for f in r["fills"] if f["side"] == "buy"))

    def test_news_shock_bot_needs_a_filing(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        r = replay.run_stockbot(data, [], days[400], days[519], 100, {"idle": None}, uni=uni, news=sig)
        self.assertTrue(all(c["ticker"] in ("ERN",) for c in r["contrib"]), r["contrib"])  # only names with news

    def test_plan_variants(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        w = replay.dual_weights(data, days[500], skip=1)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
        kept = replay.dual_weights(data, days[500], prev="SPY", margin=500.0)  # a huge margin: keep what is held
        self.assertIn("SPY", kept)
        r = replay.run_plan(data, uni, sig, days[440], days[480], 100, sleeves={"dual": 0.5, "drift": 0.5})
        last = dict(r["picks"])[max(dict(r["picks"]))]
        self.assertIn("QQQ", last)
        self.assertIn("ERN", last)                               # the drift sleeve
        m = replay.run_plan(data, uni, None, days[440], days[480], 100, sleeves={"momentum": 1.0}, n=2)
        self.assertTrue(set(m["picks"][-1][1]) - {"QQQ"} <= {"AAA", "BBB", "MMM", "BE", "ERN"})
        b = replay.run_dual(data, days[440], days[480], 100, core="QQQ", core_weight=0.7, every=14)
        self.assertGreater(len(b["picks"]), 2)                  # reviewed every 2 weeks

    def test_slices_spread_the_rebalance_dates(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        one = replay.run_dual(data, days[440], days[515], 100, core="QQQ", core_weight=0.7)
        same = replay.run_dual(data, days[440], days[515], 100, core="QQQ", core_weight=0.7, tranches=1)
        self.assertEqual(one["curve"], same["curve"])           # one slice is the plain plan
        four = replay.run_dual(data, days[440], days[515], 100, core="QQQ", core_weight=0.7, tranches=4)
        self.assertGreaterEqual(len(four["picks"]), 3 * len(one["picks"]))  # a slice re-chosen every week
        for _, held in four["picks"]:
            self.assertIn("QQQ", held)                          # the core stays in every slice

    def test_conversion_fee_when_money_starts_in_cad(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        opts = {"core": "QQQ", "core_weight": 0.7, "start_ccy": "CAD"}
        bank = replay.run_dual(data, days[440], days[515], 100, fx_fee=1.5, **opts)
        norbert = replay.run_dual(data, days[440], days[515], 100, fx_fee=0.1, **opts)
        usd = replay.run_dual(data, days[440], days[515], 100, core="QQQ", core_weight=0.7)
        self.assertGreater(bank["fx_fees"], 1.0)                # about 1.5% of the $100, once
        self.assertLess(norbert["fx_fees"], 0.2)
        self.assertEqual(usd["fx_fees"], 0.0)                   # already in US dollars
        self.assertGreater(norbert["value"], bank["value"])

    def test_earnings_drift_can_wait_for_the_eps(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        end = (replay._date(days[450]) - replay.datetime.timedelta(days=30)).isoformat()
        year_ago = (replay._date(end) - replay.datetime.timedelta(days=364)).isoformat()

        def with_eps(now):
            return replay.sigs.Signals(events={"rows": sig.events}, eps={"rows": [
                [year_ago, "ERN", year_ago, 1.0], [days[460], "ERN", end, now]]})
        up, down = with_eps(1.3), with_eps(0.8)
        self.assertEqual(replay.pead_pick(data, uni, up, days[455], eps="up"), [])       # 10-Q not filed yet
        self.assertEqual(replay.pead_pick(data, uni, up, days[460], eps="up"), ["ERN"])  # filed: EPS beat
        self.assertEqual(replay.pead_pick(data, uni, down, days[460], eps="up"), [])     # EPS fell: skip
        self.assertEqual(replay.pead_pick(data, uni, down, days[460]), ["ERN"])          # no filter: the jump alone


class Statistics(unittest.TestCase):
    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("stats", os.path.join(FIX, "..", "..", "scripts", "stats.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_confidence_range_and_reality_check(self):
        st = self.load()
        import random
        rng = random.Random(3)
        spy = [rng.gauss(8, 10) for _ in range(28)]
        table = {"S&P 500 (SPY)": {"runs": [{"return_pct": x} for x in spy]},
                 "edge": {"runs": [{"return_pct": x + 6 + rng.gauss(0, 2)} for x in spy]},   # a steady edge
                 "noise": {"runs": [{"return_pct": x + rng.gauss(0, 15)} for x in spy]}}      # luck only
        a = st.analyse({"asof": "2025-10-17", "rolling": {"table": table, "horizon_days": 365, "step_days": 91}},
                       runs=2000)
        rows = {r["strategy"]: r for r in a["rows"]}
        self.assertEqual(a["best"], "edge")
        self.assertGreater(rows["edge"]["lo90"], 0)                       # its whole range is above zero
        self.assertLess(rows["noise"]["lo90"], 0)
        self.assertLess(a["reality_check_p"], 0.1)
        self.assertIn("Reality check", st.render(a))
        self.assertEqual(replay.parse_rolling("365,91,28"), {"horizon_days": 365, "step_days": 91, "count": 28})


class LearnedScore(unittest.TestCase):
    def world(self, folder, crash_after=None):
        off = os.path.join(folder, "off")
        names = ["S%02d" % i for i in range(14)]
        for i, sym in enumerate(names):
            doc = _synth.chart(sym, p0=30 + i, growth=-0.4 + 0.08 * i, wiggle=0.012, n=700)
            if crash_after:
                r = doc["chart"]["result"][0]
                q = r["indicators"]["quote"][0]
                for j, ts in enumerate(r["timestamp"]):
                    if _synth.datetime.datetime.utcfromtimestamp(ts).date().isoformat() > crash_after:
                        for k in ("open", "high", "low", "close"):
                            q[k][j] = q[k][j] * (0.3 if i % 2 else 2.5)
            _synth.write(off, sym, doc)
        _synth.write(off, "SPY", _synth.chart("SPY", p0=400, growth=0.2, n=700))
        _synth.write(off, "USDCAD=X", _synth.chart("USDCAD=X", p0=1.37, n=700, wiggle=0.002, currency="CAD"))
        data = load_data(off)
        uni = replay.univ.Universe({"licence": "t", "last_snapshot": data.days[-1],
                                    "members": {n: [["2014-01-01", None]] for n in names}})
        return data, uni

    def test_math_helpers(self):
        self.assertEqual([round(x, 6) for x in replay._solve([[2, 0], [0, 4]], [2, 8])], [1.0, 2.0])
        z = replay._zscore([[i, 1.0] for i in range(12)])
        self.assertAlmostEqual(sum(r[0] for r in z), 0.0, places=9)
        self.assertIsNone(replay._zscore([[1.0]] * 5))  # too few stocks that day

    def test_learns_only_from_the_past(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            data, uni = self.world(a)
            cutoff = data.days[600]
            m1 = replay.fit_model(data, uni, None, cutoff, first="2000-01-01")
            data2, uni2 = self.world(b, crash_after=cutoff)  # a different future after the cutoff
            m2 = replay.fit_model(data2, uni2, None, cutoff, first="2000-01-01")
            r = replay.run_model(data, uni, None, data.days[520], data.days[690], 100, n=3)
        finally:
            shutil.rmtree(a)
            shutil.rmtree(b)
        self.assertGreater(m1["samples"], 100)
        self.assertEqual(m1["coef"], m2["coef"])  # identical: nothing after the cutoff was used
        self.assertGreater(m1["coef"][0], 0)      # steady winners keep winning: momentum gets a positive weight
        self.assertTrue(r["models"])
        self.assertTrue(all(len(set(p) - {"SPY"}) <= 3 for _, p in r["picks"]))


class YourHoldingsAndRolling(unittest.TestCase):
    def test_parse_windows(self):
        self.assertEqual(replay.parse_windows("1w,3m,12m"), [("12 months", 365), ("3 months", 91), ("1 week", 7)])
        self.assertIsNone(replay.parse_windows(""))

    def test_your_holdings_rows_and_rolling_windows(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            os.makedirs(os.path.join(base, "accounts"), exist_ok=True)
            with open(os.path.join(base, "accounts", "q.json"), "w") as fh:  # your real Questrade mix
                json.dump({"account": "q", "source": "questrade-api", "cash": {}, "positions": [
                    {"ticker": "AAA", "shares": 3}, {"ticker": "BE", "shares": 20}]}, fh)
            csv = os.path.join(d, "ws.csv")
            with open(csv, "w") as fh:
                fh.write("Symbol,Exchange,Quantity\nDIV,TSX,40\n")
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None,
                                      mc_runs=100, holdings=["w=" + csv],
                                      rolling_spec={"horizon_days": 30, "step_days": 30, "count": 3})
        finally:
            shutil.rmtree(d)
        one = out["results"]["1 month"]
        for k in ("mine:q:held", "mine:q:rules", "mine:w:held", "mine:w:rules"):
            self.assertIn(k, one)
            self.assertIn(k, out["labels"])
        self.assertEqual(sorted(one["mine:q:held"]["holdings"]), ["AAA", "BE"])
        self.assertEqual(one["mine:w:held"]["holdings"], ["DIV.TO"])
        self.assertIn("Your q, held as is", text)
        roll = out["rolling"]["table"]
        self.assertEqual(roll["growth"]["windows"], 3)
        self.assertIn("mine:q:held", roll)
        self.assertIsNone(roll["S&P 500 (SPY)"]["beat_spy"])
        self.assertLessEqual(roll["growth"]["beat_spy"], 3)
        self.assertIn("## Rolling 30-day windows", text)

    def test_self_checks_pass_on_a_clean_run_and_catch_bad_numbers(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            out, text = replay.replay(base, ASOF, 100, skip=("crypto",), offline=off, log=lambda m: None,
                                      mc_runs=100, rolling_spec={"horizon_days": 30, "step_days": 30, "count": 3})
            data = load_data(off)
        finally:
            shutil.rmtree(d)
        self.assertTrue(all(c["ok"] for c in out["checks"]), out["checks"])
        self.assertIn("## Self-checks", text)
        out["results"]["1 week"]["growth"]["value"] = float("nan")
        out["results"]["1 week"]["S&P 500 (SPY)"]["return_pct"] += 9
        del out["results"]["1 month"]["dividend"]
        failed = {c["name"] for c in replay.checks(out, data, None) if not c["ok"]}
        self.assertIn("values are positive and finite", failed)
        self.assertIn("every window has every core strategy", failed)
        self.assertTrue(any(n.startswith("S&P 500 row matches") for n in failed))

    def test_demo_holdings_are_ignored(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            os.makedirs(os.path.join(base, "accounts"), exist_ok=True)
            with open(os.path.join(base, "accounts", "q.json"), "w") as fh:
                json.dump({"account": "q", "source": "demo", "positions": [{"ticker": "AAA", "shares": 3}]}, fh)
            self.assertEqual(replay.my_holdings(base), {})
        finally:
            shutil.rmtree(d)


class NoLookahead(unittest.TestCase):
    def test_identical_results_with_a_different_future(self):
        """Same past, different future: every number up to the as-of date is identical."""
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            base_a, off_a = write_world(a)
            base_b, off_b = write_world(b)
            uni = fake_universe(load_data(off_a).days)
            out_a, _ = replay.replay(base_a, ASOF, 100, skip=("crypto",), offline=off_a, log=lambda m: None, mc_runs=200, rolling_spec=None)
            ua, _ = replay.replay(base_a, ASOF, 100, skip=("crypto",), offline=off_a, log=lambda m: None, mc_runs=200,
                                  rolling_spec=None, uni=uni)
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
            out_b, _ = replay.replay(base_b, ASOF, 100, skip=("crypto",), offline=off_b, log=lambda m: None, mc_runs=200, rolling_spec=None)
            ub, _ = replay.replay(base_b, ASOF, 100, skip=("crypto",), offline=off_b, log=lambda m: None, mc_runs=200,
                                  rolling_spec=None, uni=uni)
        finally:
            shutil.rmtree(a)
            shutil.rmtree(b)
        for x, y in ((out_a, out_b), (ua, ub)):  # watchlists, then the point-in-time universe
            for w in x["results"]:  # values, curves, holdings, fills, insights, factors: all identical
                for k, va in x["results"][w].items():
                    self.assertEqual(va, y["results"][w][k], "%s %s" % (w, k))
            self.assertEqual(x["scenarios"], y["scenarios"])


class Crypto(unittest.TestCase):
    def test_crypto_window_runs_on_closed_bars(self):
        d = tempfile.mkdtemp()
        try:
            base, off = write_world(d)
            t1 = replay.market_close_utc(ASOF)
            iv = replay.team.DEFAULTS["interval_min"]
            n = 300 * 24 * 60 // iv // 4  # 75 days of bars at the team's interval
            steps = ([0.006] * 30 + [-0.008] * 4 + [0.008] * 15) * 40
            for c in ("BTC", "ETH"):
                bars, px = [], 100.0
                for i in range(n):
                    o = px
                    px *= 1 + steps[i % len(steps)]
                    t = t1 - (n - i) * iv * 60
                    bars.append({"t": t, "o": o, "h": max(o, px) * 1.001, "l": min(o, px) * 0.999, "c": px, "v": 5})
                name = "candles-%s.json" % c if iv == 15 else "candles-%s-%d.json" % (c, iv)
                with open(os.path.join(off, name), "w") as fh:
                    json.dump(bars, fh)
            out, text = replay.replay(base, ASOF, 100, skip=("pelosi",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
        finally:
            shutil.rmtree(d)
        one = out["results"]["1 week"]["crypto team"]
        self.assertIn("value", one)
        self.assertIsNotNone(out["results"]["1 week"]["Bitcoin (hold)"])
        self.assertIn("Crypto bot team", text)


if __name__ == "__main__":
    unittest.main()


class LongHistory(unittest.TestCase):
    def test_splice_keeps_the_newer_prices_and_carries_the_older_moves(self):
        d = tempfile.mkdtemp()
        try:
            _synth.write(d, "IEF", _synth.chart("IEF", p0=100, growth=0.05, n=300))
            _synth.write(d, "VFITX", _synth.chart("VFITX", p0=10, growth=0.2, n=800,
                                                  divs=_synth.quarterly("2023-01-15", "2025-01-15", 0.1)))
            ief, fund = (replay.mk.get_chart(s, offline=d) for s in ("IEF", "VFITX"))
        finally:
            shutil.rmtree(d)
        s = replay.splice(ief, fund, "VFITX")
        self.assertEqual(len(s["bars"]), 800)
        self.assertEqual(s["bars"][500:], ief["bars"])                     # the ETF's own prices untouched
        k = ief["bars"][0]["c"] / fund["bars"][500]["c"]
        self.assertAlmostEqual(s["bars"][499]["c"], fund["bars"][499]["c"] * k)  # older moves, rescaled
        self.assertAlmostEqual(s["dividends"][0][1], 0.1 * k)
        self.assertEqual(s["spliced"]["until"], ief["bars"][0]["d"])
        self.assertIs(replay.splice(ief, None), ief)

    def test_fred_rates_skip_holidays(self):
        c = replay.fred_chart("DATE,DEXCAUS\n2001-01-02,1.5\n2001-01-03,.\n2001-01-04,1.51\n")
        self.assertEqual([b["d"] for b in c["bars"]], ["2001-01-02", "2001-01-04"])
        self.assertEqual(c["price"], 1.51)

    def test_long_run_offline(self):
        d = tempfile.mkdtemp()
        try:
            off = os.path.join(d, "off")
            for sym, n, g in (("SPY", 900, 0.3), ("QQQ", 900, 0.5), ("XLK", 900, 0.6), ("XLU", 900, 0.1),
                              ("VFITX", 900, 0.05), ("VFISX", 900, 0.02), ("IEF", 400, 0.03), ("SHY", 400, 0.01)):
                _synth.write(off, sym, _synth.chart(sym, p0=50, growth=g, wiggle=0.005, n=n))
            days = [x.isoformat() for x in _synth.trading_days(900)]
            with open(os.path.join(off, "fred-DEXCAUS.csv"), "w") as fh:
                fh.write("DATE,DEXCAUS\n" + "".join("%s,1.4\n" % x for x in days))
            charts, notes = replay.long_charts(off, log=lambda m: None)
            out = replay.long_run(replay.Data(charts, {}), first=days[300], until=days[-1], horizon=120, step=60,
                                  period_ends=(days[-1],), notes=notes)
        finally:
            shutil.rmtree(d)
        self.assertEqual(len(charts["IEF"]["bars"]), 900)                  # stitched back with VFITX
        self.assertIn("VFITX", notes["IEF"])
        self.assertIn("FRED", notes["USDCAD=X"])
        self.assertNotIn("VFITX", charts)
        t = out["rolling"]["table"]
        self.assertEqual(set(t), set(out["names"]))
        self.assertGreater(out["rolling"]["count"], 3)
        self.assertTrue(all(len(v["runs"]) == out["rolling"]["count"] for v in t.values()))
        self.assertEqual(len(out["periods"]), 1)
        text = replay.render_long(out)
        self.assertIn("before anything was chosen", text)
        f13 = {"managers": {"A": "a", "B": "b", "C": "c"}, "rows": [
            [days[290], m, days[260], days[290], 0, [["XLK", 9, 1], ["XLU", 5, 1], ["GONE", 7, 1]]] for m in "ABC"]}
        sig = replay.sigs.Signals(f13=f13)
        with_c4 = replay.long_run(replay.Data(charts, {}), first=days[300], until=days[-1], horizon=120, step=60,
                                  period_ends=(days[-1],), notes=notes, sig=sig)
        self.assertIn("Copycat consensus (C4)", with_c4["rolling"]["table"])
        self.assertEqual(with_c4["periods"][0]["c4_coverage"], 66.7)   # GONE has no prices
        self.assertIn("C4's would-be picks that had prices", replay.render_long(with_c4))
        self.assertIn("70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen)", text)

    def test_daily_bars_are_required_and_max_asks_for_dates(self):
        c = replay.mk.parse_chart(json.dumps(_synth.chart("SPY", n=300)), "SPY")
        self.assertTrue(replay.daily(c))
        monthly = dict(c, bars=c["bars"][::21])
        self.assertFalse(replay.daily(monthly))
        seen = []
        real = replay.mk.fetch
        replay.mk.fetch = lambda url, timeout=25: seen.append(url) or json.dumps(_synth.chart("SPY", n=30))
        try:
            replay.mk.get_chart("SPY", range_="max")
            replay.mk.get_chart("SPY", range_="10y")
        finally:
            replay.mk.fetch = real
        self.assertIn("period1=631152000", seen[0])                 # range=max would give monthly bars
        self.assertIn("range=10y", seen[1])


class UpstreamAgents(unittest.TestCase):
    def world(self, d):
        base, off = write_world(d)
        for sym, g in (("XLK", 0.6), ("IEF", 0.03), ("SHY", 0.02), ("QQQ", 0.4)):
            _synth.write(off, sym, _synth.chart(sym, p0=50, growth=g, wiggle=0.005, n=520))
        data = load_data(off)
        days = data.days
        uni = fake_universe(days)
        f13 = {"managers": {"A": "Ann", "B": "Bob", "C": "Cy"}, "rows": [
            [days[300], "A", days[260], days[300], 0, [["AAA", 900, 10], ["BBB", 50, 5], ["MMM", 50, 5]]],
            [days[300], "B", days[260], days[300], 0, [["AAA", 500, 10], ["MMM", 400, 10], ["INTC", 100, 1]]],
            [days[300], "C", days[260], days[300], 0, [["AAA", 10, 1], ["MMM", 5, 1], ["ZZZ", 99, 1]]],
            [days[360], "A", days[320], days[360], 0, [["AAA", 900, 10], ["BE", 300, 30], ["MMM", 50, 5]]]]}
        fund = {"rows": []}
        ends = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
        for t, growth, op in (("AAA", 30, 30), ("MMM", 4, 40), ("BBB", 50, 5)):
            for k, e in enumerate(ends):
                v = 100.0 if k == 0 else 100.0 + growth  # the last quarter is `growth`% above a year earlier
                filed = (replay._date(e) + replay.datetime.timedelta(days=40)).isoformat()
                fund["rows"] += [[filed, t, e, key, x] for key, x in (("revenue", v), ("operating_income", v * op / 100.0),
                                                                      ("eps_diluted", 0.5))]
        congress = {"rows": [[days[300], "Hon. Nancy Pelosi", "AAA", "buy", 1000001, 5000000, days[290], "SP"],
                             [days[310], "Hon. Nancy Pelosi", "BBB", "buy", 15001, 50000, days[300], "SP"],
                             [days[350], "Hon. Nancy Pelosi", "AAA", "sell", 1000001, 5000000, days[340], "SP"],
                             [days[310], "Someone Else", "MMM", "buy", 15001, 50000, days[300], "SP"],
                             [days[310], "Someone Else", "MMM", "buy", None, None, days[300], "SP"]]}  # no amount
        sig = replay.sigs.Signals(congress=congress, f13=f13, fundamentals=fund)
        return base, off, data, uni, sig

    def test_copycat_versions_see_only_filed_reports(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        cw = lambda day, **o: replay.copycat_weights(data, sig, day, **dict(replay.COPY_DEFAULT, **o))  # noqa: E731
        self.assertEqual(cw(days[299]), {"SPY": 1.0})                       # nothing filed yet
        top1 = cw(days[300], n=1)
        self.assertEqual(top1, {"AAA": 1.0})                                # everyone's biggest is AAA
        book = cw(days[300], mode="book", who=["A"])
        self.assertAlmostEqual(book["AAA"], 0.9)                            # Ann's own weights
        self.assertNotIn("ZZZ", cw(days[300]))                              # no prices: skipped
        self.assertEqual(set(cw(days[300], mode="consensus", n=2, min_count=3)), {"AAA"})
        new = cw(days[361], mode="new", who=["A"])
        self.assertEqual(set(new), {"BE"})                                  # Ann's only new position
        r = replay.run_copycat(data, sig, days[290], days[330], 100)
        self.assertTrue(all(f["day"] > days[300] for f in r["fills"] if f["ticker"] == "AAA"))

    def test_rule_based_list_uses_only_the_list_public_that_day(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        rows = [[days[300], m, days[260], days[300], 0, [["AAA", 9, 1], ["BBB", 5, 1]]] for m in "XYZ"]
        lists = [{"year": 1, "usable_from": days[305], "ciks": ["X", "Y", "Z"]}]
        b = replay.sigs.Signals(f13_broad={"rows": rows, "lists": lists})
        cw = lambda day, **o: replay.copycat_weights(data, b, day, **dict(replay.COPY_DEFAULT, broad=True, **o))  # noqa
        self.assertEqual(cw(days[302], mode="consensus", n=10), {"SPY": 1.0})     # list not public yet
        self.assertEqual(set(cw(days[306], mode="consensus", n=10)), {"AAA", "BBB"})
        self.assertEqual(set(cw(days[306], mode="consensus", n=10, min_count=4)), {"SPY"})
        self.assertEqual(cw(days[306], mode="consensus", n=10, min_count=1, top_managers=1), {"AAA": 0.5, "BBB": 0.5})
        f = {"managers": {}, "rows": [[days[300], m, days[260], days[300], 0, h] for m, h in
                                      (("X", [["AAA", 9, 1], ["BBB", 5, 1]]), ("Y", [["AAA", 9, 1]]))]}
        w = replay.copycat_weights(data, replay.sigs.Signals(f13=f), days[306], mode="consensus", n=10, min_count=1,
                                   weighted=True)
        self.assertAlmostEqual(w["AAA"], 2 / 3.0)                                  # two hold it, one holds BBB

    def test_blends_of_the_famous_and_the_rule_based_list(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        famous = {"managers": {}, "rows": [[days[300], m, days[260], days[300], 0, [["AAA", 9, 1]]] for m in "AB"]}
        broad = {"rows": [[days[300], m, days[260], days[300], 0, [["BBB", 9, 1], ["AAA", 1, 1]]] for m in "XY"],
                 "lists": [{"year": 1, "usable_from": days[305], "ciks": ["X", "Y", "A"]}]}
        s = replay.sigs.Signals(f13=famous, f13_broad=broad)
        cw = lambda day, **o: replay.copycat_weights(data, s, day, **dict(replay.COPY_DEFAULT, **o))  # noqa: E731
        self.assertEqual(cw(days[306], mode="consensus", n=1, min_count=2, broad="both"), {"AAA": 0.5, "BBB": 0.5})
        self.assertEqual(cw(days[302], mode="consensus", n=1, min_count=2, broad="both"), {"AAA": 1.0})  # no list yet
        half = cw(days[306], mode="consensus", n=1, min_count=2,
                  half_with={"mode": "consensus", "n": 1, "min_count": 2, "broad": True})
        self.assertEqual(half, {"AAA": 0.5, "BBB": 0.5})
        self.assertEqual(cw(days[306], mode="consensus", n=1, min_count=2, confirm=[2, 2]), {"AAA": 1.0})
        self.assertEqual(cw(days[306], mode="consensus", n=1, min_count=2, confirm=[1, 2]), {"SPY": 1.0})

    def test_early_stakes_versions(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        sig.stakes = sorted([[days[305], "A", "13D", days[305], "x", "Bee", "BBB"],
                             [days[305], "B", "13G", days[305], "x", "Bee", "BBB"],
                             [days[305], "C", "13G", days[305], "x", "Zed", "ZZZ"]])   # ZZZ has no prices
        sig._sd = [r[0] for r in sig.stakes]
        cw = lambda day, **o: replay.copycat_weights(data, sig, day, **dict(replay.COPY_DEFAULT, **o))  # noqa: E731
        self.assertEqual(cw(days[304], mode="stakes", stake_days=365), {"SPY": 1.0})  # nothing filed yet
        self.assertEqual(cw(days[306], mode="stakes", stake_days=365), {"BBB": 1.0})
        self.assertEqual(cw(days[306], mode="stakes", stake_days=365, stake_forms=("13G",)), {"BBB": 1.0})
        c7 = cw(days[306], mode="consensus", n=1)
        self.assertEqual(c7, {"AAA": 1.0})
        self.assertEqual(set(cw(days[306], mode="consensus", n=1, stake_days=182)), {"AAA", "BBB"})
        voted = cw(days[306], mode="consensus", n=1, min_count=2, stake_days=365, stake_vote=True)
        self.assertEqual(set(voted), {"AAA", "BBB"})                        # two stakes = two votes for BBB

    def test_caps_and_crash_brake(self):
        class Stub:
            charts = {"IEF": 1, "SPY": 1}
            up = True

            def close(self, t, d):
                return 100.0

            def quick(self, t, d, n):
                return {"above200": self.up}
        data, w = Stub(), {"AAPL": 0.5, "MSFT": 0.25, "JPM": 0.25}
        g = replay.guard(data, w, "d", cap=0.2)
        self.assertEqual((g["AAPL"], g["MSFT"], g["JPM"]), (0.2, 0.2, 0.2))
        self.assertAlmostEqual(g["SPY"], 0.4)                           # the excess goes to the S&P 500
        g = replay.guard(data, w, "d", sector_cap=0.4)
        self.assertAlmostEqual(g["AAPL"] + g["MSFT"], 0.4)              # tech cut to 40%, in proportion
        self.assertAlmostEqual(g["AAPL"] / g["MSFT"], 2.0)
        self.assertAlmostEqual(g["SPY"], 0.35)
        self.assertEqual(replay.guard(data, w, "d", brake=True), w)     # S&P 500 above its 200-day: no brake
        data.up = False
        g = replay.guard(data, w, "d", brake=True)
        self.assertAlmostEqual(g["IEF"], 0.5)
        self.assertAlmostEqual(sum(g.values()), 1.0)
        self.assertEqual(replay.guard(data, w, "d"), w)                 # no limits: unchanged

    def test_screener_and_pelosi(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        day = data.trading_day_on_or_before("2026-06-01")
        w = replay.screen_weights(data, uni, sig, day, pe=1e9)
        self.assertEqual(set(w), {"AAA"})            # MMM grows too slowly, BBB's margin is too thin
        loose = replay.screen_weights(data, uni, sig, day, growth=0.0, margin=0.0, pe=1e9)
        self.assertEqual(set(loose), {"AAA", "MMM", "BBB"} & set(uni.members_on(day)))
        self.assertEqual(replay.screen_weights(data, uni, sig, day), {"SPY": 1.0})  # P/E 35 cap: none pass
        self.assertEqual(replay.pelosi_weights(data, sig, days[320]), {"AAA": 0.5, "BBB": 0.5})
        self.assertEqual(set(replay.pelosi_weights(data, sig, days[360])), {"BBB"})              # she sold AAA
        self.assertEqual(set(replay.pelosi_weights(data, sig, days[360], mode="hold")), {"AAA", "BBB"})
        self.assertEqual(set(replay.pelosi_weights(data, sig, days[320], min_low=1000001)), {"AAA"})
        plan = replay.run_plan(data, uni, sig, days[300], days[330], 100, sleeves={"pelosi": 1.0})
        self.assertIn("QQQ", plan["picks"][-1][1])
        doc = replay.upstream_picks("p2", data, uni, sig, days[360])
        self.assertEqual(sum(x["weight"] for x in doc["weights"]), 100.0)
        self.assertIn("P2", doc["source"])
        with self.assertRaises(replay.ReplayError):
            replay.upstream_version("Z9")

    def test_congress_leaders_are_ranked_on_known_outcomes_only(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
        finally:
            shutil.rmtree(d)
        days = data.days
        lw = lambda day, **o: replay.leader_weights(data, sig, day, **dict(replay.LEADERS_DEFAULT, **o))  # noqa: E731
        self.assertEqual(lw(days[320], k=1, min_trades=1), {"SPY": 1.0})          # no outcome known yet
        self.assertEqual(set(lw(days[400], k=1, min_trades=1)), {"AAA", "BBB"})    # her buys did better
        self.assertEqual(set(lw(days[400], everyone=True)), {"AAA", "BBB", "MMM"})
        self.assertEqual(lw(days[400], k=1, min_trades=1, min_edge=1000.0), {"SPY": 1.0})
        r = replay.run_leaders(data, sig, days[300], days[420], 100, k=1, min_trades=1)
        self.assertTrue(all(f["day"] > days[363] for f in r["fills"] if f["ticker"] in ("AAA", "BBB")))

    def test_live_record_can_copy_pelosi(self):
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = self.world(d)
            days = data.days
            plan = {"start": days[290], "cash": 100.0, "strategies": {
                "P2": {"kind": "pelosi", "opts": {"mode": "hold"}}, "SPY": {"kind": "hold", "weights": {"SPY": 1.0}},
                "C4": {"kind": "copycat", "opts": {"mode": "consensus", "n": 10, "min_count": 2}},
                "L6": {"kind": "leaders", "opts": {"k": 1, "min_trades": 1}}}}
            rec = replay.forward(plan, None, offline=off, today=days[330], log=lambda m: None, signals=sig)
        finally:
            shutil.rmtree(d)
        self.assertEqual(set(rec["targets"]["P2"]), {"AAA", "BBB"})
        self.assertEqual(set(rec["targets"]["C4"]), {"AAA", "MMM"})   # in the top 10 of 2+ investors
        self.assertIsNotNone(rec["days"][days[330]]["C4"])
        self.assertIsNotNone(rec["days"][days[330]]["L6"])
        self.assertIsNotNone(rec["days"][days[330]]["P2"])
        with open(replay.FORWARD_PLAN) as fh:
            kinds = {st["kind"] for st in json.load(fh)["strategies"].values()}
        self.assertLessEqual(kinds, {"dual", "hold", "pelosi", "copycat", "leaders"})
        merged = replay.sigs.merge_rows({"rows": [["2026-01-02", "x"], ["2026-01-01", "y"]]},
                                        {"rows": [["2026-01-02", "x"], ["2026-01-03", "z"]], "source": "s"})
        self.assertEqual(merged["rows"], [["2026-01-01", "y"], ["2026-01-02", "x"], ["2026-01-03", "z"]])
        self.assertEqual(merged["source"], "s")


class NoLookaheadUpstream(unittest.TestCase):
    def test_upstream_agents_never_see_the_future(self):
        """Same past, different future (prices cut off at the as-of date vs the real later prices AND
        filings made after it): copycat, screener, Pelosi, the mixes and the league tables give
        identical results."""
        d = tempfile.mkdtemp()
        try:
            base, off, data, uni, sig = UpstreamAgents.world(UpstreamAgents(), d)
        finally:
            shutil.rmtree(d)
        days = data.days

        def cut(asof):
            out = {}
            for s, ch in data.charts.items():
                bars = [b for b in ch["bars"] if b["d"] <= asof]
                if bars:
                    out[s] = dict(ch, bars=bars, dividends=[x for x in ch["dividends"] if x[0] <= asof])
            return replay.Data(out, {})

        def with_future(asof):
            later = [x for x in days if x > asof][:5]
            return replay.sigs.Signals(
                congress={"rows": sig.congress + [[later[0], "Hon. Nancy Pelosi", "MMM", "buy", 1000001, 5000000, asof,
                                                   "SP"]]},
                f13={"managers": sig.managers, "rows": [[eff, cik, period, eff, 0, [[t, v, sh] for t, (v, sh) in h.items()]]
                                                        for cik, rows in sig.f13.items() for eff, period, h in rows]
                     + [[later[1], "A", asof, later[1], 0, [["INTC", 10 ** 9, 1]]],
                        [later[1], "B", asof, later[1], 0, [["INTC", 10 ** 9, 1]]]]},
                fundamentals={"rows": [[f, t, e, k, v] for t, by in sig.fund.items() for k, rows in by.items()
                                       for f, e, v in rows] + [[later[2], "MMM", "2026-06-30", "revenue", 10 ** 6]]})
        copy_day = days[370]                                     # 13F reports are live here
        screen_day = data.trading_day_on_or_before("2026-06-15")  # company results are live here
        self.assertNotEqual(replay.copycat_weights(data, sig, copy_day, mode="consensus", n=10, min_count=2),
                            {"SPY": 1.0})
        self.assertNotEqual(replay.screen_weights(data, uni, sig, screen_day, pe=1e9), {"SPY": 1.0})
        runs = [
            (copy_day, lambda dt, s, a, st: replay.run_copycat(dt, s, st, a, 100, mode="consensus", n=10, min_count=2)),
            (copy_day, lambda dt, s, a, st: replay.run_copycat(dt, s, st, a, 100, mode="new")),
            (copy_day, lambda dt, s, a, st: replay.run_pelosi_signals(dt, s, st, a, 100, mode="hold")),
            (copy_day, lambda dt, s, a, st: replay.leagues(dt, s, st, a, 100, min_buys=1)),
            (copy_day, lambda dt, s, a, st: replay.run_leaders(dt, s, st, a, 100, k=1, min_trades=1)),
            (screen_day, lambda dt, s, a, st: replay.run_screen(dt, uni, s, st, a, 100, pe=1e9)),
            (screen_day, lambda dt, s, a, st: replay.run_plan(dt, uni, s, st, a, 100,
                                                              sleeves={"C4": 0.5, "S1": 0.25, "P2": 0.25})),
        ]
        for i, (asof, run) in enumerate(runs):
            start = days[days.index(asof) - 120]
            self.assertEqual(run(cut(asof), sig, asof, start), run(data, with_future(asof), asof, start),
                             "run %d saw the future" % i)


class Tracking(unittest.TestCase):
    def test_live_gap_against_the_backtest_range(self):
        days = {"2026-10-%02d" % d: {"C7": 100.0 + d, "S&P 500 (SPY)": 100.0} for d in range(1, 22)}
        rec = {"days": days, "plan": {"cash": 100.0, "strategies": {"C7": {}, "S&P 500 (SPY)": {}}},
               "expect": {"C7": {"gap_mean": 7.25, "gap_sd": 14.26}}}
        t = replay.tracking(rec)[0]
        self.assertEqual((t["days"], t["gap"]), (21, 21.0))          # 21 pts ahead after 21 days
        self.assertEqual(t["status"], "above its range")              # far more than a month's 90% range
        rec["days"]["2026-10-21"]["C7"] = 100.5
        self.assertEqual(replay.tracking(rec)[0]["status"], "on track")
        rec["days"]["2026-10-21"]["C7"] = 90.0
        self.assertEqual(replay.tracking(rec)[0]["status"], "below its range")
        self.assertEqual(replay.tracking({"days": {}}), [])
