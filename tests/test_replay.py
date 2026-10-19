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
        conc = sc["Concentrated: 35% cap, 3+ names"]
        div = sc["Diversified: 10% cap, 10+ names"]
        self.assertEqual(conc["settings"]["max_position_pct"], 35)
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
        self.assertEqual(v.decide([14, 26])[0], False)
        self.assertEqual(v.decide([14, 25])[0], True)
        self.assertEqual(v.decide([30] * 49 + [29], {"mode": "trend", "days": 50})[0], True)
        self.assertEqual(v.decide([20] * 49 + [22], {"mode": "trend", "days": 50})[0], False)
        self.assertEqual(v.decide([18, 22], {"mode": "term"}, [20, 23])[0], True)   # calm shape
        self.assertEqual(v.decide([18, 24], {"mode": "term"}, [20, 23])[0], False)  # stress: backwardation
        self.assertEqual(v.decide([18, 24], {"mode": "term"})[0], True)  # no 3-month data: stay in
        st = v.status([{"d": "2026-10-15", "c": 18.0}, {"d": "2026-10-16", "c": 27.0}])
        self.assertEqual((st["regime"], st["risk_on"], st["agent"]), ("nervous", False, "step aside to cash"))
        self.assertEqual(st["day_change_pct"], 50.0)

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
                for i in range(24 * 200):  # 200 days of hourly bars
                    o, px = px, px * (1.0004 if (i // 48) % 3 else 0.9995)
                    bars.append({"t": t1 - (24 * 200 - i) * 3600, "o": o, "h": max(o, px) * 1.002,
                                 "l": min(o, px) * 0.998, "c": px, "v": 5})
                with open(os.path.join(off, "candles-%s-60.json" % c), "w") as fh:
                    json.dump(bars, fh)
            out, text = replay.replay(base, ASOF, 100, offline=off, log=lambda m: None, mc_runs=100,
                                      rolling_spec=None, windows=replay.parse_windows("6m,1m"))
        finally:
            shutil.rmtree(d)
        kinds = {x["strategy"] for x in out["scenarios"]}
        self.assertTrue({"growth", "medium", "dividend", "stock bot", "vix", "pelosi", "crypto"} <= kinds, kinds)
        hourly = [x for x in out["scenarios"] if x["name"] == "Crypto team: 1-hour bars"][0]
        self.assertIsNotNone(hourly["results"]["6 months"])
        bot = {x["name"]: x for x in out["scenarios"] if x["strategy"] == "stock bot"}
        self.assertIn("SPY", bot["Stock bot: trades + idle cash in SPY"]["results"]["6 months"]["holdings"])
        self.assertIn("Nasdaq 100 (QQQ)", out["results"]["6 months"])
        self.assertIn("| crypto | Crypto team: 1-hour bars |", text)


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
            out_a, _ = replay.replay(base_a, ASOF, 100, skip=("crypto",), offline=off_a, log=lambda m: None, mc_runs=200, rolling_spec=None)
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
            out, text = replay.replay(base, ASOF, 100, skip=("pelosi",), offline=off, log=lambda m: None, mc_runs=200, rolling_spec=None)
        finally:
            shutil.rmtree(d)
        one = out["results"]["1 week"]["crypto team"]
        self.assertIn("value", one)
        self.assertIsNotNone(out["results"]["1 week"]["Bitcoin (hold)"])
        self.assertIn("Crypto bot team", text)


if __name__ == "__main__":
    unittest.main()
