import os
import shutil
import tempfile
import unittest

from _load import load
import _synth

st = load("trader-replay", "stretch")
mk = st.mk


class Stretch(unittest.TestCase):
    def test_measures(self):
        flat = [100.0] * 260
        s = mk.stretch(flat)
        self.assertEqual(s["above_sma200_pct"], 0.0)
        self.assertEqual(mk.stretch_signals(s), [])
        run = [100.0] * 200 + [100.0 * 1.012 ** k for k in range(1, 61)]   # +100% in 60 days, steady
        s = mk.stretch(run)
        self.assertGreater(s["above_sma200_pct"], 50)
        self.assertIn("X1", mk.stretch_signals(s))
        self.assertIn("X4", mk.stretch_signals(s))
        self.assertIsNone(mk.stretch([100.0] * 50)["above_sma200_pct"])     # too short: no answer

    def test_events_are_point_in_time_and_rule_v15(self):
        d = tempfile.mkdtemp()
        try:
            _synth.write(d, "SPY", _synth.chart("SPY", p0=500, growth=0.1, n=520))
            _synth.write(d, "HOT", _synth.chart("HOT", p0=20, growth=3.0, wiggle=0.03, n=520))
            spy, hot = (mk.get_chart(t, offline=d) for t in ("SPY", "HOT"))
        finally:
            shutil.rmtree(d)
        rows = st.events(hot, spy, lambda day: True, first="2000-01-01")
        self.assertTrue(rows and any(r[1] for r in rows))
        # wreck the future: the signals on a day must not change
        cut = rows[len(rows) // 2][0]
        wrecked = dict(hot, bars=[b if b["d"] <= cut else dict(b, c=b["c"] * 0.1, o=b["o"] * 0.1) for b in hot["bars"]])
        again = {r[0]: r[1] for r in st.events(wrecked, spy, lambda day: True, first="2000-01-01")}
        for day, fired, _, _ in rows:
            if day <= cut:
                self.assertEqual(again[day], fired)
        rows = [("2019-01-%02d" % (i % 28 + 1), ["X1"], -3.0, -4.0) for i in range(40)] + \
               [("2024-01-%02d" % (i % 28 + 1), ["X1"], -1.0, -1.0) for i in range(12)] + \
               [("2019-02-%02d" % (i % 28 + 1), [], 1.0, 1.0) for i in range(100)]
        v = st.verdicts(st.summarize(rows))
        self.assertEqual(v["X1"], "trim")
        self.assertEqual(v["X2"], "info")                                     # never fired: info only
        self.assertIn("Rule v15", st.render(st.summarize(rows), v, {"with_prices": 1, "missing": 0}))


class Dips(unittest.TestCase):
    def test_dip_signals(self):
        up = [100.0 * 1.004 ** k for k in range(260)]                    # a steady uptrend
        pull = up[:-21] + [up[-22] * (1 - 0.012 * k) for k in range(1, 22)]   # then about -23% in a month
        s = mk.stretch(pull)
        self.assertLessEqual(s["off_high_pct"], -20)
        fired = mk.dip_signals(s)
        self.assertIn("D2", fired)                                       # down 10%+ in a month
        crash = up[:-60] + [up[-61] * 0.55] * 60                        # 45% below the high, flat since
        self.assertIn("D4", mk.dip_signals(mk.stretch(crash)))
        self.assertEqual(mk.dip_signals(mk.stretch(up)), [])

    def test_dip_rule_and_index_study(self):
        rows = [("2019-01-%02d" % (i % 28 + 1), ["D1"], 3.0, 4.0) for i in range(40)] + \
               [("2024-01-%02d" % (i % 28 + 1), ["D1"], 1.0, 1.0) for i in range(12)] + \
               [("2019-02-%02d" % (i % 28 + 1), [], 0.0, 0.5) for i in range(100)]
        v = st.verdicts(st.summarize(rows, mk.DIP_SIGNALS), "dip")
        self.assertEqual(v["D1"], "buy")
        self.assertEqual(v["D3"], "info")
        bars = [{"d": "2000-01-%02d" % (i % 28 + 1), "o": 100.0, "c": 100.0 if i % 50 else 85.0} for i in range(400)]
        idx = st.index_dips({"bars": bars}, levels=(10,), horizons=((5, "3 months"), (10, "12 months")))
        self.assertGreater(idx["any day"]["3 months"][0], idx["10%+ below its high"]["3 months"][0])
        text = st.render(st.summarize(rows, mk.DIP_SIGNALS), v, {"with_prices": 1, "missing": 0}, "dip",
                         dict(idx, first="2000"))
        self.assertIn("Rule v16", text)
        self.assertIn("The S&P 500 itself", text)


if __name__ == "__main__":
    unittest.main()
