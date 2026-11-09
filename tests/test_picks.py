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

    def test_dip_rule_overrides_the_trend_test_only_when_it_earned_a_buy(self):
        fallen = dict(m(150, above=False, r12=-20), off_high_pct=-45.0)
        buy = {"stock_off": 40, "market_off": 20, "trend": "any", "verdict": "buy", "source": "rule v19 (tuned)"}
        r = pk.assess("GOOGL", ["x"], fallen, buy, spy_off=-25.0)
        self.assertTrue(r["ok"] and r["dip"])
        self.assertTrue(any("on sale by the dip rule" in n for n in r["notes"]))
        self.assertFalse(pk.assess("GOOGL", ["x"], fallen, buy, spy_off=-5.0)["ok"])          # market not down enough
        info = dict(buy, verdict="info", source="rule v18")
        r = pk.assess("GOOGL", ["x"], fallen, info, spy_off=-25.0)
        self.assertFalse(r["ok"])                                                            # not earned: still wait
        self.assertTrue(any("information only" in n for n in r["notes"]))
        prices = {"GOOGL": fallen, "MSFT": m(400, above=False)}
        self.assertEqual(pk.from_dip(prices.get, buy, -25.0, giants=("GOOGL", "MSFT")), {"GOOGL": ["a giant on sale by the dip rule"]})
        self.assertEqual(pk.from_dip(lambda t: 1 / 0, buy, -5.0), {})                           # nothing fetched
        rows = pk.build({}, None, None, set(), prices.get, "2026-11-04", rule=buy, spy_off=-25.0)
        self.assertEqual([x["ticker"] for x in rows if x["ok"]], ["GOOGL"])  # build adds giants on sale (market.GIANTS)
        self.assertIn("Dip rule in force", pk.render(rows, [], buy))

    def test_wide_scan_keeps_only_large_companies(self):
        ideas = {"ideas": [{"symbol": "TINYBIO"}, {"symbol": "BIG"}, {"symbol": "BIG2"}]}
        got = pk.from_ideas(ideas, large={"BIG", "BIG2"}, top=1)
        self.assertEqual(list(got), ["BIG"])                 # the 500 % small cap never reaches the list
        full = {"ideas": [{"symbol": "TINYBIO"}], "large": [{"symbol": "RY.TO"}, {"symbol": "BIG"}]}
        self.assertEqual(list(pk.from_ideas(full, top=5)), ["RY.TO", "BIG"])   # the scan's full large-company ranking

    def test_account_currency(self):
        ideas = {"large": [{"symbol": "RY.TO"}, {"symbol": "JPM"}]}
        get = {"RY.TO": m(150), "JPM": m(300)}.get
        usd = pk.build({}, None, ideas, set(), get, "2026-11-05", currency="USD")
        cad = pk.build({}, None, ideas, set(), get, "2026-11-05", currency="CAD")
        self.assertEqual([r["ticker"] for r in usd], ["JPM"])        # a USD account never gets a TSX stock
        self.assertEqual([r["ticker"] for r in cad], ["RY.TO"])

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
