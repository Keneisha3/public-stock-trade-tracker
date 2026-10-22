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


if __name__ == "__main__":
    unittest.main()
