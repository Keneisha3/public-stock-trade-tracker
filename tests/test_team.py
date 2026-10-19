import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import ROOT, load

team = load("trader-team", "team")
analyst, candles, executor, risk_manager, scanner, trade_log = (
    team.analyst, team.candles, team.executor, team.risk_manager, team.scanner, team.trade_log)

T0 = 1_790_000_000 // 900 * 900
UP_DIP_UP = [0.003] * 120 + [-0.004] * 12 + [0.004] * 7   # the Analyst says BUY on the last bar (index 138)


def bars(steps, p0=100.0, t0=T0, wick=0.002):
    out, c = [], p0
    for i, r in enumerate(steps):
        o = c
        c = c * (1 + r)
        out.append({"t": t0 + i * 900, "o": o, "h": max(o, c) * (1 + wick), "l": min(o, c) * (1 - wick),
                    "c": c, "v": 10.0})
    return out


def after(b):
    """'now' just after the last bar closed."""
    return b[-1]["t"] + 900 + 20


def cfg(**over):
    c = dict(team.DEFAULTS, interval_min=15)  # these tests drive the team on 15-minute bars
    c.update(over)
    return c


class Indicators(unittest.TestCase):
    def test_ema_rsi_atr(self):
        self.assertEqual(analyst.ema([1, 2, 3], 3)[-1], 2)
        e = analyst.ema([1, 2, 3, 4], 3)
        self.assertAlmostEqual(e[-1], 3.0)
        self.assertEqual(analyst.rsi([float(i) for i in range(30)], 14)[-1], 100.0)
        down = analyst.rsi([float(30 - i) for i in range(30)], 14)[-1]
        self.assertEqual(down, 0.0)
        steady = [{"t": i, "o": 10, "h": 11, "l": 9, "c": 10} for i in range(20)]
        self.assertAlmostEqual(analyst.atr(steady, 14)[-1], 2.0)

    def test_analyst_buy_and_exit(self):
        b = bars(UP_DIP_UP)
        sig = analyst.analyze("BTC", b, cfg())
        self.assertEqual(sig["action"], "BUY", sig["reasons"])
        self.assertTrue(50 <= sig["rsi"] <= 70)
        self.assertEqual(analyst.analyze("BTC", b[:-1], cfg())["action"], "NONE")
        self.assertEqual(analyst.analyze("BTC", bars([0.003] * 120 + [-0.004] * 10), cfg())["action"], "EXIT")

    def test_overheated_rsi_is_refused(self):
        sig = analyst.analyze("BTC", bars(UP_DIP_UP), cfg(rsi_max=55))
        self.assertEqual(sig["action"], "NONE")
        self.assertIn("RSI", " ".join(sig["reasons"]))


class Scanner(unittest.TestCase):
    def test_setups_and_data_checks(self):
        good = bars(UP_DIP_UP)
        flat = [dict(b, o=5, h=5, l=5, c=5) for b in good]
        stale = good[:-12]
        c = cfg(coins=["BTC", "ETH", "SOL", "XRP"])
        setups, skipped = scanner.scan({"BTC": good, "ETH": flat, "SOL": stale}, c, after(good))
        self.assertEqual([s["coin"] for s in setups], ["BTC"])
        why = {s["coin"]: s["reason"] for s in skipped}
        self.assertIn("not moved", why["ETH"])
        self.assertIn("stale", why["SOL"])
        self.assertIn("history", why["XRP"])
        setups, _ = scanner.scan({"BTC": good[:-3]}, c, after(good[:-3]), held={"BTC"})
        self.assertEqual(setups[0]["why"], "held: check for an exit")


class Risk(unittest.TestCase):
    def acct(self, **kw):
        a = {"equity": 10000.0, "cash": 10000.0, "positions": {}, "cooldown": {}}
        a.update(kw)
        return a

    def test_two_percent_risk_with_costs(self):
        sig = {"coin": "BTC", "price": 100.0, "atr": 2.0}
        p = risk_manager.plan_entry(sig, self.acct(), cfg(max_position_pct=100), 0)
        self.assertTrue(p["approved"])
        self.assertAlmostEqual(p["stop"], 97.0)
        self.assertAlmostEqual(p["tp"], 106.0)
        self.assertAlmostEqual(p["risk_usd"], 200.0, places=1)  # 2% of 10,000, fees included
        loss_at_stop = p["qty"] * (100 - 97) + p["qty"] * (100 + 97) * 0.003
        self.assertLessEqual(loss_at_stop, 200.01)
        self.assertIn("fees and slippage are 16% of what this trade risks", p["reasons"][-1])
        tight = risk_manager.plan_entry({"coin": "BTC", "price": 100.0, "atr": 0.3}, self.acct(), cfg(), 0)
        self.assertIn("high", tight["reasons"][-1])

    def test_caps(self):
        sig = {"coin": "BTC", "price": 100.0, "atr": 0.2}  # tight stop: the 25% position cap binds
        p = risk_manager.plan_entry(sig, self.acct(), cfg(), 0)
        self.assertLessEqual(p["notional"], 2500.01)
        self.assertIn("max 25%", " ".join(p["reasons"]))
        full = {c: {"risk_usd": 200} for c in ("A", "B", "C")}
        self.assertFalse(risk_manager.plan_entry(sig, self.acct(positions=full), cfg(), 0)["approved"])
        self.assertFalse(risk_manager.plan_entry(sig, self.acct(positions={"BTC": {}}), cfg(), 0)["approved"])
        self.assertFalse(risk_manager.plan_entry(sig, self.acct(cooldown={"BTC": 99}), cfg(), 50)["approved"])
        self.assertFalse(risk_manager.plan_entry(sig, self.acct(cash=5), cfg(), 0)["approved"])

    def test_daily_loss(self):
        self.assertTrue(risk_manager.daily_loss_hit(10000, 9500, cfg()))
        self.assertFalse(risk_manager.daily_loss_hit(10000, 9501, cfg()))

    def test_config_cannot_raise_risk_above_two_percent(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "config.json"), "w") as fh:
                json.dump({"risk_pct": 5}, fh)
            with self.assertRaises(team.TeamError):
                team.load_cfg(team.Paths(d))
        finally:
            shutil.rmtree(d)


class PaperGuard(unittest.TestCase):
    GOOD = {"TRADING_MODE": "paper", "PAPER_API_KEY": "PKTESTKEY123", "PAPER_API_SECRET": "s3cr3t-value-xyz"}

    def http(self, account_number="PA1234567", status="ACTIVE"):
        calls = []

        def h(url, headers=None, data=None, method="GET"):
            calls.append((method, url, data))
            self.assertTrue(url.startswith("https://paper-api.alpaca.markets/"), url)
            if url.endswith("/v2/account"):
                return {"account_number": account_number, "status": status, "crypto_status": "ACTIVE",
                        "equity": "10000", "cash": "10000"}
            if url.endswith("/v2/positions"):
                return [{"symbol": "BTCUSD", "qty": "0.5", "qty_available": "0.5"}]
            if method == "POST":
                return {"id": "o1", "status": "accepted"}
            if "/v2/orders/o1" in url:
                return {"id": "o1", "status": "filled", "filled_avg_price": "101.5", "filled_qty": "0.5"}
            raise AssertionError(url)
        h.calls = calls
        return h

    def refused(self, env, **kw):
        b = executor.AlpacaPaperBroker(env, cfg(), http=self.http(**kw), sleep=lambda s: None)
        with self.assertRaises(executor.PaperGuardError) as e:
            b.verify()
        return str(e.exception)

    def test_refuses_anything_not_clearly_paper(self):
        self.assertIn("TRADING_MODE", self.refused(dict(self.GOOD, TRADING_MODE="live")))
        self.assertIn("not https://paper-api", self.refused(dict(self.GOOD, PAPER_API_BASE_URL="https://api.alpaca.markets")))
        msg = self.refused(dict(self.GOOD, PAPER_API_KEY="AKLIVEKEY999"))
        self.assertIn("not a paper key", msg)
        self.assertNotIn("AKLIVEKEY999", msg)  # never echo a key
        self.assertIn("did not confirm a paper account", self.refused(self.GOOD, account_number="123456"))
        self.assertIn("not active", self.refused(self.GOOD, status="ACCOUNT_CLOSED"))
        self.assertIn("missing", self.refused({"TRADING_MODE": "paper"}))

    def test_paper_order_flow(self):
        h = self.http()
        b = executor.AlpacaPaperBroker(self.GOOD, cfg(), http=h, sleep=lambda s: None)
        fill = b.buy("BTC", 0.5)
        self.assertEqual((fill["price"], fill["qty"]), (101.5, 0.5))
        post = [c for c in h.calls if c[0] == "POST"][0]
        self.assertEqual(post[2]["symbol"], "BTC/USD")
        self.assertEqual(post[2]["type"], "market")
        self.assertEqual(b.positions(), {"BTC": 0.5})

    def test_no_live_trading_address_anywhere(self):
        for f in os.listdir(os.path.join(ROOT, "trader-team")):
            if f.endswith(".py"):
                with open(os.path.join(ROOT, "trader-team", f), encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotIn("https://api.alpaca.markets", src.replace("data.alpaca.markets", ""), f)
                self.assertNotIn("//api.alpaca", src, f)

    def test_env_file_and_masking(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, ".env")
            with open(p, "w") as fh:
                fh.write("# my keys\nPAPER_API_KEY=PKABCDEFGH\nPAPER_API_SECRET='topsecretvalue'\nTRADING_MODE=paper\n")
            env, used = candles.load_env(os.path.join(d, "missing"), p)
            self.assertEqual(used, p)
            self.assertEqual(env["PAPER_API_SECRET"], "topsecretvalue")
            self.assertEqual(candles.mask("topsecretvalue"), "to...ue")
        finally:
            shutil.rmtree(d)


class Sources(unittest.TestCase):
    def test_coinbase_pages_and_sorts(self):
        seen = []

        def http(url, headers=None):
            seen.append(url)
            return [[T0 + 900, 9, 11, 10, 10.5, 3], [T0, 8, 10, 9, 10, 2]]
        out = candles.fetch_coinbase("BTC", T0, T0 + 600 * 900, 15, http=http, pause=0)
        self.assertEqual(len(seen), 2)  # 300 candles a call
        self.assertEqual([b["t"] for b in out], [T0, T0 + 900])
        self.assertEqual(out[1]["c"], 10.5)

    def test_alpaca_bars_paginate(self):
        pages = [{"bars": {"BTC/USD": [{"t": "2026-10-19T12:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}]},
                  "next_page_token": "abc"},
                 {"bars": {"BTC/USD": [{"t": "2026-10-19T12:15:00Z", "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 4}]},
                  "next_page_token": None}]

        def http(url, headers=None):
            if pages[0].get("next_page_token") is None:
                self.assertIn("page_token=abc", url)
            return pages.pop(0)
        got, errors = candles.fetch(["BTC", "ETH"], "alpaca", T0, T0 + 3600, http=http)
        self.assertEqual([b["c"] for b in got["BTC"]], [1.5, 1.8])
        self.assertIn("ETH", errors[0])


class Cycle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = team.Paths(self.dir)
        self.cfg = cfg(coins=["BTC", "ETH"])
        self.state = {"mode": "sim"}
        self.broker = executor.SimBroker(self.state, self.cfg)
        self.out = io.StringIO()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_to(self, series_by, i):
        window = {c: b[:i + 1] for c, b in series_by.items()}
        with redirect_stdout(self.out):
            return team.cycle(self.state, window, after(window["BTC"]), self.broker, self.cfg, self.paths)

    def trades(self):
        return trade_log.read(self.paths.trades)

    def test_entry_then_take_profit_logged_with_every_field(self):
        btc = bars(UP_DIP_UP + [0.004] * 20)
        eth = bars([0.001] * 160, p0=50)
        rep = self.run_to({"BTC": btc, "ETH": eth}, 138)
        self.assertEqual([e["coin"] for e in rep["entries"]], ["BTC"])
        self.assertIn("BTC", self.state["positions"])
        self.assertIn("[SIMULATED] BUY", self.out.getvalue())
        for i in range(139, 159):
            self.run_to({"BTC": btc, "ETH": eth}, i)
            if not self.state["positions"]:
                break
        t = self.trades()
        self.assertEqual(len(t), 1)
        row = t[0]
        self.assertEqual(row["exit_reason"], "take-profit")
        self.assertEqual(row["mode"], "SIMULATED")
        self.assertEqual(row["approved_by"], "Scanner > Analyst > Risk Manager > Executor (SIMULATED)")
        for f in trade_log.TRADE_FIELDS:
            self.assertIn(f, row)
        self.assertGreater(float(row["pnl"]), 0)
        self.assertGreater(float(row["fees_slippage_est"]), 0)
        self.assertGreaterEqual(len(trade_log.read(self.paths.equity)), 2)  # one equity row per cycle

    def test_stop_loss_and_cooldown(self):
        btc = bars(UP_DIP_UP + [-0.01] * 6)
        eth = bars([0.001] * 150, p0=50)
        self.run_to({"BTC": btc, "ETH": eth}, 138)
        for i in range(139, 145):
            self.run_to({"BTC": btc, "ETH": eth}, i)
        row = self.trades()[0]
        self.assertEqual(row["exit_reason"], "stop-loss")
        self.assertLess(float(row["pnl"]), 0)
        self.assertGreater(float(row["pnl"]), -10000 * 0.02 * 1.6)  # a stop-out costs about the planned 2%
        self.assertIn("BTC", self.state["cooldown"])

    def test_kill_switch_sells_everything_and_stops(self):
        btc = bars(UP_DIP_UP + [0.0005] * 5)
        eth = bars([0.001] * 150, p0=50)
        self.run_to({"BTC": btc, "ETH": eth}, 138)
        team.set_kill(self.paths, "test", flatten=True, now=after(btc[:139]))
        rep = self.run_to({"BTC": btc, "ETH": eth}, 139)
        self.assertEqual(rep["killed"], "test")
        self.assertEqual(self.state["positions"], {})
        self.assertEqual(self.trades()[0]["exit_reason"], "kill switch")
        rep = self.run_to({"BTC": btc, "ETH": eth}, 140)
        self.assertEqual(rep["entries"], [])

    def test_daily_loss_limit_trips_the_kill_switch(self):
        btc = bars(UP_DIP_UP + [0.0005] * 5)
        eth = bars([0.001] * 150, p0=50)
        self.run_to({"BTC": btc, "ETH": eth}, 137)
        day = team._day(after(btc[:138]))
        self.state["day_start_equity"][day] = 11000  # pretend we started the day 10% higher
        rep = self.run_to({"BTC": btc, "ETH": eth}, 138)
        self.assertEqual(rep["killed"], "daily loss limit")
        self.assertIn("daily loss", team.read_kill(self.paths)["reason"])

    def test_summary_numbers(self):
        os.makedirs(self.dir, exist_ok=True)
        for pnl, reason in ((120, "take-profit"), (-60, "stop-loss"), (-40, "stop-loss")):
            trade_log.trade(self.paths.trades, {"closed_at": "2026-10-19 10:00 UTC", "pnl": pnl,
                                                "fees_slippage_est": 3, "exit_reason": reason})
        for ts, eq, hold in ((0, 10000, 10000), (900, 10200, 10100), (1800, 9945, 10300), (2700, 10020, 10250)):
            trade_log.equity(self.paths.equity, ts, eq, hold, 0)
        s = trade_log.summary(self.dir)
        self.assertEqual((s["trades"], s["wins"], s["losses"]), (3, 1, 2))
        self.assertEqual(s["win_rate_pct"], 33.3)
        self.assertEqual((s["avg_win"], s["avg_loss"], s["pnl"]), (120, -50, 20))
        self.assertEqual(s["max_drawdown_pct"], -2.5)
        self.assertEqual((s["bot_return_pct"], s["hold_return_pct"]), (0.2, 2.5))
        text = trade_log.render(s, "SIMULATED")
        self.assertIn("[SIMULATED]", text)
        self.assertIn("holding the same coins", text)


class Live(unittest.TestCase):
    """run_once end to end from saved candles: downtime, errors, auto kill switch."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.team_dir = os.path.join(self.dir, "team")
        self.off = os.path.join(self.dir, "candles")
        os.makedirs(self.off)
        os.makedirs(self.team_dir)
        with open(os.path.join(self.team_dir, "config.json"), "w") as fh:
            json.dump({"coins": ["BTC"], "interval_min": 15}, fh)
        self.b = bars(UP_DIP_UP)
        with open(os.path.join(self.off, "candles-BTC.json"), "w") as fh:
            json.dump(self.b, fh)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_run_once_offline_and_downtime(self):
        quiet = lambda *a: None  # noqa: E731
        now = after(self.b)
        rep = team.run_once(self.team_dir, now=now, offline=self.off, log=quiet)
        self.assertEqual(rep["mode"], "SIMULATED")
        self.assertEqual([e["coin"] for e in rep["entries"]], ["BTC"])
        team.run_once(self.team_dir, now=now + 4 * 3600, offline=self.off, log=quiet)
        kinds = [e["kind"] for e in trade_log.read(os.path.join(self.team_dir, "events.csv"))]
        self.assertIn("downtime", kinds)

    def test_repeated_failures_set_the_kill_switch(self):
        os.remove(os.path.join(self.off, "candles-BTC.json"))
        for i in range(5):
            with self.assertRaises(team.TeamError):
                team.run_once(self.team_dir, now=after(self.b) + i * 900, offline=self.off, log=lambda *a: None)
        self.assertIn("5 cycles in a row failed", team.read_kill(team.Paths(self.team_dir))["reason"])

    def test_cli_check_and_kill_resume(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(team.main(["--dir", self.team_dir, "check"]), 0)
            self.assertEqual(team.main(["--dir", self.team_dir, "kill"]), 0)
            self.assertTrue(os.path.exists(os.path.join(self.team_dir, "KILL")))
            self.assertEqual(team.main(["--dir", self.team_dir, "resume"]), 0)
        self.assertIn("SIMULATED mode", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.team_dir, "KILL")))

    def test_backtest_offline(self):
        long = bars(([0.003] * 120 + [-0.004] * 12 + [0.004] * 30) * 3)
        with open(os.path.join(self.off, "candles-BTC.json"), "w") as fh:
            json.dump(long, fh)
        with redirect_stdout(io.StringIO()) as out:
            s = team.backtest(self.team_dir, days=5, offline=self.off)
        self.assertGreaterEqual(s["trades"], 1)
        self.assertIn("SIMULATED", out.getvalue())
        self.assertTrue(os.path.exists(os.path.join(self.team_dir, "backtest", "trades.csv")))


if __name__ == "__main__":
    unittest.main()
