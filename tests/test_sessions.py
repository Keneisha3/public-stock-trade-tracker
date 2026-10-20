import datetime
import json
import os
import shutil
import tempfile
import unittest

from _load import load

sessions = load("trader-replay", "sessions")


def weekdays(n, end=datetime.date(2026, 10, 16)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


def ts(day, hour, minute=0):
    d = datetime.date.fromisoformat(day)
    return int(datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=datetime.timezone.utc).timestamp())


def world(days, up_days):
    """Overseas markets rise 1% on `up_days` and fall 1% otherwise; SPY then gains 0.5% from open to
    close on up days and loses 0.5% on the others (so the overseas read is genuinely useful)."""
    hourly, daily = {}, {}
    hours = {"Tokyo": range(0, 6), "Hong Kong": range(2, 8), "London": range(8, 16), "Frankfurt": range(7, 16)}
    for name, sym in sessions.MARKETS.items():
        px, bars, dbars = 100.0, [], []
        for d in days:
            step = 1.01 if d in up_days else 0.99
            hs = list(hours[name])
            for k, h in enumerate(hs):
                bars.append((ts(d, h), round(px * (1 + (step - 1) * (k + 1) / len(hs)), 4)))
            px *= step
            dbars.append({"d": d, "o": px, "h": px, "l": px, "c": round(px, 4)})
        hourly[name] = bars
        daily[sym] = {"bars": dbars, "dividends": []}
    for fund in sessions.FUNDS:
        px, dbars = 50.0, []
        for d in days:
            o = px
            c = o * (1.005 if d in up_days else 0.995)
            dbars.append({"d": d, "o": round(o, 4), "h": c, "l": c, "c": round(c, 4)})
            px = c
        daily[fund] = {"bars": dbars, "dividends": []}
    return hourly, daily


class Sessions(unittest.TestCase):
    def test_new_york_open_follows_daylight_saving(self):
        self.assertEqual(sessions.ny_open_utc("2026-07-15"), ts("2026-07-15", 13, 30))
        self.assertEqual(sessions.ny_open_utc("2026-01-15"), ts("2026-01-15", 14, 30))
        self.assertEqual(sessions.ny_open_utc("2026-03-09"), ts("2026-03-09", 13, 30))  # the day after the switch
        self.assertEqual(sessions.ny_open_utc("2026-11-02"), ts("2026-11-02", 14, 30))
        self.assertEqual(sessions.decision_time("2026-07-15"), ts("2026-07-15", 13, 15))

    def test_only_bars_closed_before_the_decision_are_read(self):
        days = weekdays(5)
        hourly, daily = world(days, set(days))
        d = days[-1]  # summer time: decision at 13:15 UTC; London's 12:00 bar closed at 13:00, its 13:00 bar not
        london = hourly["London"]
        before = sessions.move(london, daily["^FTSE"], d)
        wrecked = [(t, c * (0.5 if t >= ts(d, 13) else 1.0)) for t, c in london]  # a crash after the decision
        self.assertEqual(sessions.move(wrecked, daily["^FTSE"], d), before)
        self.assertAlmostEqual(before, 1.0 * 5 / 8, places=3)  # 1% day, 5 of London's 8 hourly steps had closed
        self.assertAlmostEqual(sessions.move(hourly["Tokyo"], daily["^N225"], d), 1.0, places=3)  # Asia is done
        holiday = [(t, c) for t, c in hourly["Tokyo"] if sessions._utc_date(t) != d]
        self.assertIsNone(sessions.move(holiday, daily["^N225"], d))

    def test_a_useful_read_is_found_and_kept_apart_from_the_test_year(self):
        days = weekdays(560)
        up = set(days[::2])
        hourly, daily = world(days, up)
        res = sessions.run(hourly, daily)
        self.assertLess(res["first"], res["cut"])
        tr = res["training"]
        self.assertGreater(tr["D1. Asia closed up: day-trade SPY"]["return_pct"], tr["Hold SPY"]["return_pct"])
        self.assertEqual(tr["D4. Buy the dip: all four down 0.5%+ on average, day-trade SPY"]["win_rate"], 0.0)
        self.assertIn(sessions.verdict(res)[:2], ("D1", "D2", "D3", "D5", "D6"))
        self.assertTrue(all(c[0] <= res["cut"] for c in tr["Hold SPY"]["curve"]))
        self.assertTrue(all(c[0] >= res["cut"] for c in res["test"]["Hold SPY"]["curve"]))
        self.assertIn("(pick)", sessions.render(res))
        t = sessions.today(hourly, daily, days[-1])
        self.assertEqual(len(t), len(sessions.VERSIONS))

    def test_offline_files_and_no_signal_means_cash(self):
        d = tempfile.mkdtemp()
        try:
            days = weekdays(40)
            hourly, daily = world(days, set())
            for name, sym in sessions.MARKETS.items():
                doc = {"chart": {"result": [{"timestamp": [t for t, _ in hourly[name]],
                                             "indicators": {"quote": [{"close": [c for _, c in hourly[name]]}]}}]}}
                with open(os.path.join(d, "hourly-%s.json" % sym), "w") as fh:
                    json.dump(doc, fh)
            h, _ = sessions.load(d, log=lambda m: None)
        finally:
            shutil.rmtree(d)
        self.assertEqual(h["Tokyo"], hourly["Tokyo"])
        r = sessions.backtest(hourly, daily)
        self.assertEqual(r["D1. Asia closed up: day-trade SPY"]["trades"], 0)  # never up: never trades
        self.assertEqual(r["D1. Asia closed up: day-trade SPY"]["return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
