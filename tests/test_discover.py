import gzip
import json
import os
import shutil
import tempfile
import unittest

from _load import load
import _synth

discover = load("trader-discover", "discover")

NASDAQ = ("Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
          "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
          "QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N\n"
          "ZZZT|Test Co - Common Stock|Q|Y|N|100|N|N\n"
          "ACMEW|Acme Corp - Warrants|Q|N|N|100|N|N\n"
          "File Creation Time: 1019202617:00|||||||\n")
OTHER = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
         "BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK=B\n"
         "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
         "JPM$C|JPMorgan Chase Depositary Shares|N|JPMpC|N|100|N|JPM-C\n"
         "File Creation Time: 1019202617:00|||||||\n")


class Parsers(unittest.TestCase):
    def test_symbol_directory_keeps_common_stocks(self):
        self.assertEqual(discover.parse_symdir(NASDAQ, "nasdaq"), [("AAPL", "Apple Inc. - Common Stock")])
        self.assertEqual(discover.parse_symdir(OTHER, "other"), [("BRK-B", "Berkshire Hathaway Inc. Class B")])

    def test_articles_name_tickers(self):
        t = discover.tickers_in("Nvidia (NASDAQ: NVDA) and Royal Bank (TSX: RY) beat; $TSLA fell, (NYSE:BRK.B) held; $5 off")
        self.assertEqual(t, ["NVDA", "RY.TO", "BRK-B", "TSLA"])
        html = '<a href="/quote/nasdaq/aapl/">Apple</a> <a href="/quote/nyse/ko/">KO</a> (NASDAQ: MSFT)'
        self.assertEqual(discover.fool_tickers(html), ["AAPL", "KO", "MSFT"])

    def test_feeds_and_json(self):
        rss = (b"<rss><channel><item><title>Apple (NASDAQ: AAPL) jumps</title><description>&lt;b&gt;$AMD&lt;/b&gt; too"
               b"</description></item></channel></rss>")
        texts = discover.rss_text(rss)
        self.assertEqual(sum((discover.tickers_in(x) for x in texts), []), ["AAPL", "AMD"])
        self.assertEqual(discover.rss_text(b"not xml"), [])
        y = {"finance": {"result": [{"quotes": [{"symbol": "NVDA"}, {"symbol": "BTC-USD"}, {"symbol": "^VIX"}]}]}}
        self.assertEqual(discover.parse_yahoo_quotes(y), ["NVDA"])
        self.assertEqual(discover.parse_apewisdom({"results": [{"ticker": "gme", "mentions": "120", "rank": 1}]}),
                         [{"symbol": "GME", "mentions": 120, "rank": 1}])
        self.assertEqual(discover.parse_sec_tickers({"0": {"ticker": "BRK.B"}, "1": {"ticker": "aapl"}}), ["AAPL", "BRK-B"])
        tmx = {"results": [{"symbol": "RY", "instruments": [{"symbol": "RY"}, {"symbol": "RY.PR.J"}]},
                           {"symbol": "CTC.A", "name": "Canadian Tire"}]}
        self.assertEqual(discover.parse_tmx(tmx, ".TO"), ["CTC-A.TO", "RY.TO"])
        csv = ("iShares Russell 2000 ETF\nFund Holdings as of,\"Oct 17, 2026\"\n\n"
               "Ticker,Name,Sector,Asset Class,Market Value\nSMCI,SUPER MICRO,IT,Equity,1\nXTSLA,BLK CSH,Cash,Money Market,1\n"
               "-,USD CASH,Cash,Cash,1\n")
        self.assertEqual(discover.parse_ishares(csv), ["SMCI"])


class SnapshotAndFunnel(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def fake_http(self, url, ua=None):
        if "nasdaqlisted" in url:
            return NASDAQ.encode()
        if "otherlisted" in url:
            return OTHER.encode()
        if "trending" in url:
            return json.dumps({"finance": {"result": [{"quotes": [{"symbol": "AAA"}]}]}}).encode()
        if "apewisdom" in url:
            return json.dumps({"results": [{"ticker": "BBB", "mentions": 50, "rank": 1}]}).encode()
        if "rssindex" in url or "news.google" in url:
            return b"<rss><channel><item><title>AAA (NASDAQ: AAA) rallies</title></item></channel></rss>"
        raise discover.DiscoverError("HTTP 403")

    def test_snapshot_survives_failing_sources_and_funnel_ranks(self):
        src = discover.gather(http=self.fake_http, log=lambda m: None)
        self.assertEqual(src["listed_us"]["symbols"], ["AAPL", "BRK-B"])
        self.assertIn("error", src["screens"])  # one source failing never stops the others
        self.assertEqual(src["news"]["detail"]["mentions"], {"AAA": 5})
        base = os.path.join(self.dir, "trader")
        path = discover.save_snapshot(base, src, "2026-10-16")
        with gzip.open(path, "rt") as fh:
            self.assertEqual(json.load(fh)["date"], "2026-10-16")
        snap = discover.load_snapshot(base)
        pool = discover.candidates(snap)
        self.assertEqual(pool, {"AAA": ["trending", "news"]})  # BBB is not a listed stock: dropped
        snap["sources"]["listed_us"]["symbols"] += ["BBB"]
        pool = discover.candidates(snap)
        self.assertEqual(pool, {"AAA": ["trending", "news"], "BBB": ["reddit"]})
        self.assertIn("AAPL", discover.candidates(snap, deep=True))
        off = os.path.join(self.dir, "off")
        _synth.write(off, "AAA", _synth.chart("AAA", p0=40, growth=0.6, n=300))
        _synth.write(off, "BBB", _synth.chart("BBB", p0=40, growth=-0.5, n=300))
        out = discover.funnel(snap, offline=off, log=lambda m: None)
        self.assertEqual([r["symbol"] for r in out["ideas"]], ["AAA"])  # BBB is falling: under its 200-day average
        self.assertEqual(out["ideas"][0]["sources"], ["trending", "news"])
        self.assertIsNone(discover.score({"price": 3, "above_sma200": True, "dollar_volume": 1e8, "ret_12m": 50, "ret_1m": 1}))


if __name__ == "__main__":
    unittest.main()
