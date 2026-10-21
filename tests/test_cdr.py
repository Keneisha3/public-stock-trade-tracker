import datetime
import unittest

from _load import load

cdr = load("trader-replay", "cdr")


def chart(sym, ccy, start, step, n=300, end=datetime.date(2026, 10, 16)):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    days.reverse()
    return {"symbol": sym, "currency": ccy, "name": sym + " CDR", "dividends": [],
            "bars": [{"d": x, "o": start * step ** i, "h": 0, "l": 0, "c": start * step ** i} for i, x in enumerate(days)]}


class Cdr(unittest.TestCase):
    def test_hedged_cdr_against_the_us_share(self):
        us = chart("AAPL", "USD", 100, 1.001)
        fx = chart("USDCAD=X", "CAD", 1.30, 1.0002)          # the US dollar rises against the CAD
        c = chart("AAPL.NE", "CAD", 25, 1.00098)              # follows the USD return, a little less
        fx["bars"] = [dict(x, d=(datetime.date.fromisoformat(x["d"]) - datetime.timedelta(days=1)).isoformat())
                      for x in fx["bars"]]                  # Yahoo dates FX bars the evening before
        r = cdr.compare(c, us, fx)
        self.assertGreater(r["us_cad"], r["us_usd"])         # CAD holders of the US share got the FX gain too
        self.assertLess(r["cdr_pct"], r["us_usd"])               # the hedged CDR did not
        self.assertGreater(r["hedge_cost_per_year"], 0)

    def test_only_cad_listings_with_fresh_prices_are_kept(self):
        charts = {"USDCAD=X": chart("USDCAD=X", "CAD", 1.3, 1.0), "AAPL": chart("AAPL", "USD", 100, 1.001),
                  "AAPL.NE": chart("AAPL.NE", "CAD", 25, 1.001), "MSFT": chart("MSFT", "USD", 100, 1.0),
                  "MSFT.NE": chart("MSFT.NE", "USD", 25, 1.0),        # not in CAD: not a CDR
                  "GOOGL": chart("GOOGL", "USD", 100, 1.0),
                  "GOOGL.NE": chart("GOOGL.NE", "CAD", 25, 1.0, end=datetime.date(2026, 8, 1))}  # stale

        def get(sym, r):
            if sym not in charts:
                raise cdr.mk.MarketError("no %s" % sym)
            return charts[sym]
        found, rows = cdr.verify(get=get, today="2026-10-20", log=lambda m: None)
        self.assertEqual(found, {"AAPL": "AAPL.NE"})
        self.assertIn("AAPL.NE", cdr.render(found, rows))


if __name__ == "__main__":
    unittest.main()
