import unittest

from _load import load

pk = load("trader-replay", "picks")


def m(price, above=True, r12=10.0, stretch=None):
    return {"price": price, "above_sma200": above, "ret_12m": r12, "off_high_pct": -5.0, "vol_pct": 30.0,
            "stretch": stretch or {}}


class Picks(unittest.TestCase):
    def test_rank_filter_and_size(self):
        record = {"targets": {"Copycat ... F4 (chosen)": {"AAA": 0.5, "BBB": 0.5},
                              "Copycat top 10 (C4, upstream agent)": {"AAA": 0.5, "CCC": 0.5},
                              "S&P 500 (SPY)": {"SPY": 1.0}}}
        ideas = {"ideas": [{"symbol": "DDD"}, {"symbol": "HELD"}]}
        prices = {"AAA": m(100, r12=5), "BBB": m(50, above=False), "CCC": m(20, r12=80),
                  "DDD": m(10, r12=40, stretch={"above_sma200_pct": 70}), "HELD": m(5)}
        rows = pk.build(record, None, ideas, {"HELD"}, prices.get, "2026-11-04")
        self.assertEqual([r["ticker"] for r in rows], ["AAA", "CCC", "DDD", "BBB"])   # evidence, then momentum
        self.assertEqual(rows[0]["evidence"], 2)                                      # main plan and C4
        self.assertFalse(rows[-1]["ok"])                                              # below its 200-day: wait
        self.assertTrue(any("stretched" in n for n in rows[2]["notes"]))
        self.assertNotIn("HELD", [r["ticker"] for r in rows])                         # already owned
        plan = pk.size(rows, 300, 3000)
        self.assertEqual([p["ticker"] for p in plan], ["AAA", "CCC", "DDD"])          # never BBB
        self.assertEqual(plan[0]["amount"], 100.0)
        capped = pk.size(rows, 3000, 1000)                                            # 10% of 4000 = 400 cap
        self.assertEqual(capped[0]["amount"], 400.0)
        self.assertIn("Not financial advice", pk.render(rows, plan))

    def test_near_consensus(self):
        f13 = {"managers": {"A": "Ann (X)", "B": "Bob", "C": "Cy"}, "rows": [
            ["2026-08-15", "A", "2026-06-30", "2026-08-15", 0, [["MU", 9, 1], ["Z", 1, 1]]],
            ["2026-08-15", "B", "2026-06-30", "2026-08-15", 0, [["MU", 9, 1], ["Y", 1, 1]]],
            ["2026-08-15", "C", "2026-06-30", "2026-08-15", 0, [["Y", 9, 1]]]]}
        got = pk.near_consensus(pk.sigs.Signals(f13=f13), "2026-11-04")
        self.assertIn("MU", got)
        self.assertIn("Y", got)          # B and C
        self.assertNotIn("Z", got)       # only one investor
        self.assertIn("Ann", got["MU"][0])


if __name__ == "__main__":
    unittest.main()
