#!/usr/bin/env python3
"""The dashboard: a local web page over the trader/ folder. Standard library only.

    python3 app/server.py                 # http://127.0.0.1:8765
    python3 app/server.py --port 9000 --open

It listens on 127.0.0.1 only (never your network), rejects requests whose
Host is not localhost (DNS rebinding), and every write needs a custom header
that a web page from another site cannot send without permission (CSRF).
Nothing here can place a trade.
"""

import argparse
import io
import json
import os
import sys
import threading
import traceback
import webbrowser
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(APP)
SKILLS = os.path.join(REPO, ".claude", "skills")
for folder in ("trader-accounts", "trader-paper", "trader-daily", "trader-init"):
    sys.path.insert(0, os.path.join(SKILLS, folder))
import accounts as acc  # noqa: E402
import daily  # noqa: E402
import init  # noqa: E402
import paper  # noqa: E402

LOCK = threading.Lock()  # one refresh / write at a time
MAX_BODY = 5 * 1024 * 1024


def state(base, contribute=0.0):
    paths = acc.Paths(base)
    if not os.path.exists(paths.config):
        return {"setup": False}
    cfg = acc.load_config(paths.config)
    market = acc.read_json(paths.market, {"symbols": {}, "fx": {}})
    review = acc.review_all(cfg, paths, market, contribute=contribute)
    for r in review["accounts"]:  # the page does not need the full metric dicts twice
        for p in r["positions"]:
            m = p.pop("metrics") or {}
            p["m"] = {k: m.get(k) for k in ("day_pct", "ret_1m", "ret_3m", "ret_12m", "yield_pct", "vol_pct",
                                            "off_high_pct", "div_growth_3y_pct", "above_sma200", "spark")}
    led = acc.read_json(os.path.join(base, "paper", "ledger.json"))
    bt = acc.read_json(os.path.join(base, "paper", "backtest.json"))
    return {
        "setup": True, "review": review,
        "history": (acc.read_json(paths.history, {"points": []}) or {}).get("points", []),
        "briefing": acc.read_json(os.path.join(base, "briefing.json")),
        "paper": paper.summary(led) if led else None,
        "backtest": {k: bt[k] for k in ("from", "to", "bot", "buy_hold", "per_year", "equity", "benchmark")}
        if bt else None,
        "accounts": [{"id": a["id"], "name": a["name"], "broker": a.get("broker"), "strategy": a["strategy"]}
                     for a in cfg["accounts"]],
    }


class Handler(BaseHTTPRequestHandler):
    base = "trader"
    port = 8765
    server_version = "trader-dashboard"

    def log_message(self, fmt, *args):  # quiet: one line per write only
        if self.command == "POST":
            sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                with open(os.path.join(APP, "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html")
            if url.path == "/api/state":
                q = parse_qs(url.query)
                c = float((q.get("contribute") or ["0"])[0] or 0)
                return self._send(200, state(self.base, max(0.0, c)))
            return self._send(404, {"error": "not found"})
        except Exception as e:  # show the reason on the page, keep serving
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Trader") != "1":
            return self._send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "send JSON"})
        url = urlparse(self.path)
        try:
            with LOCK:
                out = self.route(url.path, body)
            return self._send(200, out)
        except (acc.AccountsError, paper.PaperError, acc.mk.MarketError, ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def route(self, path, body):
        b, paths = self.base, acc.Paths(self.base)
        if path == "/api/init":
            args = ["--dir", b] + (["--demo"] if body.get("demo") else []) + \
                   (["--with-medium"] if body.get("medium") else [])
            with redirect_stdout(io.StringIO()) as out:
                init.main(args)
            return {"ok": True, "log": out.getvalue()}
        if path == "/api/refresh":
            skip = [s for s in body.get("skip", []) if s in daily.STEPS]
            brief = daily.run(b, skip=skip)
            return {"ok": True, "steps": brief["steps"]}
        cfg = acc.load_config(paths.config)
        if path == "/api/import":
            a = acc.account(cfg, body["account"])
            doc = acc.parse_holdings_csv(str(body["csv"]), a["id"], body.get("filter") or None)
            old = acc.read_json(paths.holdings(a["id"]), acc.empty_holdings(a["id"]))
            doc["cash"] = old.get("cash", {})
            acc.write_json(paths.holdings(a["id"]), doc)
            return {"ok": True, "imported": len(doc["positions"]), "skipped": doc.get("skipped_rows", 0)}
        if path == "/api/cash":
            a = acc.account(cfg, body["account"])
            doc = acc.read_json(paths.holdings(a["id"]), acc.empty_holdings(a["id"]))
            doc.setdefault("cash", {})[str(body.get("currency", "CAD")).upper()[:3]] = float(body["amount"])
            acc.write_json(paths.holdings(a["id"]), doc)
            return {"ok": True}
        if path == "/api/backtest":
            charts, errors = paper.load_charts(paper.universe(os.path.join(b, "paper", "config.json")))
            res = paper.backtest(charts)
            res["errors"] = errors
            paper.write(os.path.join(b, "paper", "backtest.json"), res)
            return {"ok": True}
        raise KeyError("unknown action %s" % path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local dashboard for your accounts, the paper bot and the daily briefing.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dir", default=os.path.join(REPO, "trader"))
    ap.add_argument("--open", action="store_true", help="open it in your browser")
    a = ap.parse_args(argv)
    Handler.base, Handler.port = a.dir, a.port
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://127.0.0.1:%d" % a.port
    print("dashboard on %s (data: %s). Ctrl+C to stop." % (url, a.dir))
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
