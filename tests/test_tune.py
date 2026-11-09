import os
import shutil
import tempfile
import unittest

from _load import load
import _synth

tu = load("trader-replay", "tune")
mk = tu.mk


def row(day, off, below, ex, dv=1e9, spy_off=0.0):
    return (day, off, below, ex, dv, spy_off)


class Tune(unittest.TestCase):
    def test_samples_are_point_in_time(self):
        d = tempfile.mkdtemp()
        try:
            _synth.write(d, "SPY", _synth.chart("SPY", p0=500, growth=0.1, n=900))
            _synth.write(d, "AAA", _synth.chart("AAA", p0=50, growth=-0.5, wiggle=0.05, n=900))
            spy, aaa = (mk.get_chart(t, offline=d) for t in ("SPY", "AAA"))
        finally:
            shutil.rmtree(d)
        dd = tu.spy_drawdown(spy)
        rows = tu.samples(aaa, spy, dd, lambda day: True, first="2000-01-01")
        self.assertTrue(rows)
        cut = rows[len(rows) // 2][0]
        wrecked = dict(aaa, bars=[b if b["d"] <= cut else dict(b, c=b["c"] * 0.1, o=b["o"] * 0.1) for b in aaa["bars"]])
        again = {r[0]: r[1:3] for r in tu.samples(wrecked, spy, dd, lambda day: True, first="2000-01-01")}
        for r in rows:
            if r[0] <= cut:
                self.assertEqual(again[r[0]], r[1:3], r[0])      # what the rule sees on a day ignores the future
        self.assertIsNone(rows[-1][3])                           # no full year after the last day yet

    def test_fires_evaluate_and_gap(self):
        rule = {"stock_off": 30, "market_off": 20, "trend": "below200"}
        self.assertTrue(tu.fires(row("2008-10-01", -35, True, 5, spy_off=-25), rule))
        self.assertFalse(tu.fires(row("2008-10-01", -35, False, 5, spy_off=-25), rule))   # trend
        self.assertFalse(tu.fires(row("2008-10-01", -35, True, 5, spy_off=-10), rule))    # market not down enough
        rows = {"A": [row("2008-10-%02d" % k, -35, True, 10.0, spy_off=-25) for k in range(1, 9)]}
        e = tu.evaluate(rows, rule, ("2006-01-01", "2019-01-01"))
        self.assertEqual(e["n"], 2)                      # 8 samples 5 days apart, one event per 21 days
        self.assertEqual((e["mean"], e["years"], e["beat"]), (10.0, 1, 100))

    def test_choice_uses_training_only_and_needs_three_years(self):
        by = {}
        for k, t in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            rows = []
            for y in (2008, 2011, 2015):
                for m in range(1, 13):
                    rows.append(row("%d-%02d-01" % (y, m), -45, True, 8.0 if y != 2015 else 1.0, spy_off=-22))
            rows.append(row("2020-03-20", -45, True, 30.0, spy_off=-30))     # held out: must not sway the choice
            by[t] = rows
        out = tu.tune(by)
        c = out["chosen"]
        self.assertIsNotNone(c)
        self.assertGreaterEqual(c["train"]["years"], 3)
        self.assertEqual(c["held_out"]["n"], 26)
        self.assertEqual(c["verdict"], "not enough evidence")          # 26 < 30 held-out events
        rf = tu.rule_file(out)
        self.assertEqual((rf["stock_off"], rf["market_off"], rf["verdict"]), (40, 20, "info"))  # v18 fallback
        self.assertIn("rule v19", tu.render(out))
        self.assertIn("Not financial advice", tu.render(out))

    def test_giants_keeps_the_most_traded_each_day(self):
        by = {"BIG": [row("2010-01-04", 0, False, 0, dv=5e9)], "SMALL": [row("2010-01-04", 0, False, 0, dv=1e6)]}
        g = tu.giants(by, n=1)
        self.assertEqual((len(g["BIG"]), len(g["SMALL"])), (1, 0))


if __name__ == "__main__":
    unittest.main()
