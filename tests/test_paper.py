import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load
import _synth

paper = load("trader-paper", "paper")
mk = paper.mk

N = 300


def charts(gaps=None, crash=None, names=("AAA", "BBB", "CCC", "DDD"), growth=0.3):
    out = {}
    for i, s in enumerate(names):
        g = dict((gaps or {}).get(s, {}))
        g.update((crash or {}).get(s, {}))
        doc = _synth.chart(s, p0=50 + 10 * i, growth=growth, wiggle=0.004, n=N, gaps=g or None)
        out[s] = mk.parse_chart(json.dumps(doc), s)
    return out


class Atr(unittest.TestCase):
    def test_wilder_atr_of_a_steady_range(self):
        bars = [{"d": str(i), "o": 10, "h": 11, "l": 9, "c": 10} for i in range(30)]
        atr = paper.wilder_atr(bars, 14)
        self.assertIsNone(atr[13])
        self.assertAlmostEqual(atr[14], 2.0)
        self.assertAlmostEqual(atr[-1], 2.0)

    def test_regime_follows_the_index(self):
        days, bars_by, regime = paper.prepare(charts(growth=0.4))
        self.assertEqual(regime[days[10]], "unknown")
        self.assertEqual(regime[days[-1]], "bull")
        days, bars_by, regime = paper.prepare(charts(growth=-0.6))
        self.assertEqual(regime[days[-1]], "bear")


class Engine(unittest.TestCase):
    def run_days(self, ch):
        days, bars_by, regime = paper.prepare(ch)
        led = paper.new_ledger(10000)
        for d in days[paper.WARMUP:]:
            paper.step(led, d, bars_by, regime)
        return days, led

    def test_up_breach_buys_next_open_and_exits_after_three_days(self):
        days, led = self.run_days(charts(gaps={"BBB": {N - 10: 6}}))
        t = [x for x in led["trades"] if x["ticker"] == "BBB" and x["entry_day"] == days[N - 9]]
        self.assertEqual(len(t), 1, led["trades"])
        self.assertEqual(t[0]["exit_day"], days[N - 7])
        self.assertEqual(t[0]["why"], "time")

    def test_a_crash_hits_the_stop(self):
        # breach at N-10, then a 10% collapse on the second day held
        days, led = self.run_days(charts(gaps={"BBB": {N - 10: 6}}, crash={"BBB": {N - 8: -10}}))
        t = [x for x in led["trades"] if x["ticker"] == "BBB" and x["entry_day"] == days[N - 9]][0]
        self.assertEqual(t["why"], "stop")
        self.assertLess(t["pnl"], 0)
        self.assertGreater(t["ret_pct"], -12)  # the stop capped the damage near 2 ATR

    def test_no_entries_in_a_bear_regime(self):
        days, led = self.run_days(charts(gaps={"BBB": {N - 10: 6}}, growth=-0.6))
        self.assertFalse([x for x in led["trades"] if x["entry_day"] == days[N - 9]])

    def test_size_caps_and_costs(self):
        names = ["S%d" % i for i in range(12)]
        gaps = {s: {N - 10: 6} for s in names}
        days, bars_by, regime = paper.prepare(charts(gaps=gaps, names=names))
        led = paper.new_ledger(10000)
        for d in days[paper.WARMUP:N - 8]:
            paper.step(led, d, bars_by, regime)
        # 12 signals, but 15% per name means the cash runs out at 6 (and never more than 8)
        self.assertEqual(len(led["positions"]), 6)
        self.assertGreaterEqual(led["cash"], 0)
        eq = led["equity"][-1][1]
        for s, pos in led["positions"].items():
            self.assertLessEqual(pos["shares"] * pos["entry"], eq * 0.15 + 1, s)
        self.assertLess(eq, 10000 * 1.2)

    def test_backtest_reports_bot_and_benchmark(self):
        res = paper.backtest(charts(gaps={"AAA": {150: 6, 220: 5}, "CCC": {180: 6}}))
        for k in ("total_pct", "sharpe", "max_dd_pct", "trades", "win_rate_pct"):
            self.assertIn(k, res["bot"])
        self.assertIn("total_pct", res["buy_hold"])
        self.assertGreaterEqual(res["bot"]["trades"], 3)
        self.assertTrue(res["per_year"])


class Live(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.off = os.path.join(self.dir, "offline")
        for s in ("AAA", "BBB", "CCC"):
            _synth.write(self.off, s, _synth.chart(s, p0=40, growth=0.3, wiggle=0.004, n=N,
                                                    gaps={N - 1: 6} if s == "BBB" else None))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_run_is_idempotent_and_queues_todays_signal(self):
        args = ["--dir", self.dir, "run", "--offline", self.off, "--symbols", "AAA", "BBB", "CCC", "--json"]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(paper.main(args), 0)
        s = json.loads(out.getvalue())
        self.assertEqual([o["ticker"] for o in s["pending"]], ["BBB"])
        self.assertEqual(s["regime"], "bull")
        with redirect_stdout(io.StringIO()) as out:
            paper.main(args)
        s2 = json.loads(out.getvalue())
        self.assertEqual(len(s2["equity_curve"]), len(s["equity_curve"]))
        self.assertEqual(len(s2["pending"]), 1)
        self.assertTrue(any(not c["ok"] for c in s2["readiness"]))  # one day is never "ready"


if __name__ == "__main__":
    unittest.main()
