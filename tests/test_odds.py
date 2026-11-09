import shutil
import tempfile
import unittest

from _load import load
import _synth

od = load("trader-replay", "odds")


def bars(closes):
    return [{"d": "2000-01-%03d" % i, "c": c} for i, c in enumerate(closes)]


class Odds(unittest.TestCase):
    def test_drawdowns_and_bear_starts(self):
        dd = od.drawdowns(bars([100, 120, 90, 96, 125, 100, 80]))
        self.assertAlmostEqual(dd[2][1], -0.25)
        self.assertEqual(dd[4][1], 0.0)
        self.assertAlmostEqual(dd[6][1], -0.36)
        self.assertEqual(od.bear_starts(dd), [dd[2][0], dd[6][0]])

    def test_odds_counts_only_the_future_and_the_gate(self):
        # 30% below the high, then 45% below two days later
        dd = od.drawdowns(bars([100, 70, 65, 55, 60, 60]))
        n, k = od.odds(dd, 25, 33, -0.40, horizon=2)
        self.assertEqual((n, k), (1, 1))            # only day 1 is 25-33% off; day 3 is 45% off
        n, k = od.odds(dd, 25, 33, -0.40, horizon=2, gate=lambda d: False)
        self.assertEqual(k, 0)
        n, k = od.odds(dd, 25, 33, -0.50, horizon=2)
        self.assertEqual(k, 0)

    def test_main_offline(self):
        d = tempfile.mkdtemp()
        try:
            for t, g in (("SPY", 0.1), ("AAA", 0.3)):
                _synth.write(d, t, _synth.chart(t, p0=100, growth=g, wiggle=0.03, n=800))
            out = tempfile.mkdtemp(dir=d)
            self.assertEqual(od.main(["--offline", d, "--out", out, "--tickers", "AAA", "NOPE"]), 0)
            with open(out + "/odds.md", encoding="utf-8") as fh:
                md = fh.read()
        finally:
            shutil.rmtree(d)
        self.assertIn("| AAA |", md)
        self.assertNotIn("NOPE |", md)
        self.assertIn("Not financial advice", md)


if __name__ == "__main__":
    unittest.main()
