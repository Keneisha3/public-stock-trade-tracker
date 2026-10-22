import os
import shutil
import tempfile
import unittest

from _load import load
import _synth

gov = load("trader-replay", "govstakes")


class GovStakes(unittest.TestCase):
    def test_bought_at_the_next_open_after_the_news(self):
        d = tempfile.mkdtemp()
        try:
            _synth.write(d, "SPY", _synth.chart("SPY", p0=500, growth=0.1, n=300))
            _synth.write(d, "MP", _synth.chart("MP", p0=20, growth=1.0, n=300))
            get = lambda t: gov.mk.get_chart(t, offline=d)  # noqa: E731
            spy, mp = get("SPY"), get("MP")
            news = mp["bars"][100]["d"]
            r = gov.event(mp, spy, news)
            self.assertEqual(r["entry"], mp["bars"][101]["d"])          # never the news day itself
            self.assertEqual(r["entry_price"], round(mp["bars"][101]["o"], 2))
            self.assertIn("6 months", r)
            self.assertEqual(gov.event(mp, spy, news, wait=5)["entry"], mp["bars"][106]["d"])
            self.assertIsNone(gov.event(mp, spy, mp["bars"][-1]["d"]))  # news after the last bar: nothing yet
            rows = gov.study({"stakes": [{"ticker": "MP", "company": "MP", "agency": "Defense", "stake": "15%",
                                          "theme": "magnets", "first_public": news},
                                         {"ticker": "ZZZ", "company": "Z", "agency": "x", "stake": "x", "theme": "x",
                                          "first_public": news}]}, get)
            text = gov.render(rows)
            self.assertIn("1 of 1 beat the S&P 500", text)
            self.assertIn("ZZZ", text)                                   # missing prices are said, not hidden
        finally:
            shutil.rmtree(d)

    def test_briefing_rows_and_section(self):
        d = tempfile.mkdtemp()
        try:
            _synth.write(d, "SPY", _synth.chart("SPY", p0=500, growth=0.1, n=300))
            _synth.write(d, "MP", _synth.chart("MP", p0=20, growth=1.0, n=300))
            get = lambda t: gov.mk.get_chart(t, offline=d)  # noqa: E731
            last = get("MP")["bars"][-1]["d"]
            news = get("MP")["bars"][-10]["d"]
            rows = gov.briefing({"stakes": [{"ticker": "MP", "company": "MP Materials", "agency": "Defense",
                                             "stake": "15%", "theme": "magnets", "first_public": news}]}, get, last)
        finally:
            shutil.rmtree(d)
        self.assertTrue(rows[0]["new"])                    # news under two weeks old
        self.assertTrue(rows[0]["above_sma200"])
        daily = load("trader-daily", "daily")
        text = daily.render({"date": last, "steps": {}, "gov": rows})
        self.assertIn("NEW MP MP Materials", text)
        self.assertIn("do not chase", text)

    def test_the_list_is_dated_and_public_companies_only(self):
        doc = gov.load()
        for s in doc["stakes"]:
            self.assertRegex(s["first_public"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(s["ticker"] and s["agency"])


if __name__ == "__main__":
    unittest.main()
