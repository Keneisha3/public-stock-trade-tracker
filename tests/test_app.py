import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer

from _load import REPO, ROOT
import _synth

sys.path.insert(0, os.path.join(REPO, "app"))
import server  # noqa: E402
import daily  # noqa: E402  (server put trader-daily on the path)


class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        server.Handler.base = os.path.join(cls.dir, "trader")
        server.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = server.Handler.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.dir)

    def setUp(self):  # every test starts from an empty trader/ folder
        self.dir = tempfile.mkdtemp(dir=self.__class__.dir)
        server.Handler.base = os.path.join(self.dir, "trader")

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        if body is not None:
            h.update({"Content-Type": "application/json", "X-Trader": "1"})
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if r.getheader("Content-Type", "").startswith("application/json") else data)

    def test_flow(self):
        code, page = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Portfolio Tracker", page)
        self.assertEqual(self.req("GET", "/api/state")[1], {"setup": False})
        self.assertEqual(self.req("POST", "/api/init", {"demo": True})[0], 200)
        code, st = self.req("GET", "/api/state")
        self.assertTrue(st["setup"])
        self.assertEqual([a["id"] for a in st["accounts"]], ["questrade", "wealthsimple"])
        csv = "Symbol,Exchange,Quantity,Average Cost,Currency\nENB,TSX,10,50,CAD\nRY,TSX,2,150,CAD\n"
        code, out = self.req("POST", "/api/import", {"account": "wealthsimple", "csv": csv})
        self.assertEqual((code, out["imported"]), (200, 2))
        self.assertEqual(self.req("POST", "/api/cash", {"account": "wealthsimple", "amount": 99.5})[0], 200)
        code, st = self.req("GET", "/api/state?contribute=500")
        ws = [a for a in st["review"]["accounts"] if a["id"] == "wealthsimple"][0]
        self.assertEqual(sorted(p["ticker"] for p in ws["positions"]), ["ENB.TO", "RY.TO"])
        self.assertEqual(ws["cash_by"], {"CAD": 99.5})
        self.assertEqual(st["review"]["contribute"], 500)
        code, err = self.req("POST", "/api/import", {"account": "nope", "csv": csv})
        self.assertEqual(code, 400)
        self.assertIn("no account", err["error"])

    def test_crypto_team_kill_switch_buttons(self):
        self.req("POST", "/api/init", {})
        tdir = os.path.join(self.dir, "trader", "team")
        with open(os.path.join(tdir, "state.json"), "w") as fh:
            json.dump({"mode": "sim", "last_cycle": 1790000000, "positions": {}}, fh)
        self.assertEqual(self.req("GET", "/api/state")[1]["crypto"]["mode"], "SIMULATED")
        self.assertEqual(self.req("POST", "/api/team/kill", {})[0], 200)
        st = self.req("GET", "/api/state")[1]
        self.assertIn("dashboard", st["crypto"]["kill"]["reason"])
        self.assertTrue(st["crypto"]["kill"]["flatten"])
        self.req("POST", "/api/team/resume", {})
        self.assertIsNone(self.req("GET", "/api/state")[1]["crypto"]["kill"])

    def test_other_hosts_and_cross_site_writes_are_refused(self):
        self.assertEqual(self.req("GET", "/api/state", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/cash", body="{}", headers={"Host": "127.0.0.1:%d" % self.port,
                                                            "Content-Type": "text/plain"})
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_page_loads_nothing_from_the_internet(self):
        with open(os.path.join(REPO, "app", "index.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotRegex(page, r"<script[^>]+src=")
        self.assertNotRegex(page, r"<link[^>]+href=\"https?:")
        self.assertIn("esc(n.title)", page)  # headlines come from outside: always escaped


class DailyOffline(unittest.TestCase):
    def test_daily_run_writes_the_briefing(self):
        d = tempfile.mkdtemp()
        try:
            base, off = os.path.join(d, "trader"), os.path.join(d, "off")
            init = sys.modules["init"]
            with redirect_stdout(io.StringIO()):
                init.main(["--dir", base, "--demo"])
            for s, cur in (("NVDA", "USD"), ("MSFT", "USD"), ("ENB.TO", "CAD")):
                _synth.write(off, s, _synth.chart(s, growth=0.3, currency=cur,
                                                  divs=_synth.quarterly("2022-01-15", "2026-07-15", 0.9) if cur == "CAD" else None))
            _synth.write(off, "USDCAD=X", _synth.chart("USDCAD=X", p0=1.4, n=22, wiggle=0, currency="CAD"))
            with open(os.path.join(base, "paper", "config.json"), "w") as fh:
                json.dump({"universe": ["NVDA", "MSFT"]}, fh)
            b = daily.run(base, offline=off, today="2026-10-16")
            self.assertTrue(os.path.exists(os.path.join(base, "briefing.md")))
            self.assertGreater(b["portfolio"]["total"], 0)
            self.assertTrue(b["steps"]["market"]["ok"])
            self.assertTrue(b["steps"]["paper"]["ok"], b["steps"]["paper"])
            self.assertNotIn("news", b["steps"])  # offline skips network steps
            with open(os.path.join(base, "history.json")) as fh:
                self.assertEqual(json.load(fh)["points"][-1]["date"], "2026-10-16")
            self.assertIn("Not financial advice", daily.render(b))
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
