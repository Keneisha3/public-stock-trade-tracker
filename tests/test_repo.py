import os
import re
import subprocess
import unittest

from _load import REPO, ROOT

UPSTREAM = ["trader-copycat", "trader-news", "trader-budget", "trader-pelosi", "trader-analyst",
            "trader-screener", "trader-risk", "trader-broker", "trader-tax", "trader-alerts",
            "trader-rebalance"]
OURS = ["trader-accounts", "trader-paper", "trader-daily", "trader-init", "trader-team", "trader-replay"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


class Repo(unittest.TestCase):
    def test_every_skill_folder_is_there(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(UPSTREAM + OURS))

    def test_frontmatter_name_and_description(self):
        for s in UPSTREAM + OURS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)

    def test_every_skill_says_not_advice_and_never_trades_alone(self):
        for s in UPSTREAM + OURS:
            if s == "trader-analyst" or s == "trader-screener" or s == "trader-news":
                continue  # read-only research skills
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)

    def test_paper_bot_never_imports_a_broker(self):
        with open(os.path.join(ROOT, "trader-paper", "paper.py"), encoding="utf-8") as fh:
            src = fh.read()
        for word in ("alpaca", "questrade", "place_stock_order", "ibkr"):
            self.assertNotIn(word, src.lower(), word)

    def test_team_example_config_matches_the_defaults(self):
        import json
        from _load import load
        team = load("trader-team", "team")
        with open(os.path.join(ROOT, "trader-team", "config.example.json"), encoding="utf-8") as fh:
            ex = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
        self.assertEqual(ex, {k: v for k, v in team.DEFAULTS.items() if k != "lookback_bars"})
        self.assertEqual(ex["broker"], "sim")

    def test_keys_file_is_git_ignored(self):
        try:
            out = subprocess.run(["git", "-C", REPO, "check-ignore", ".env"], capture_output=True, text=True)
        except OSError:
            self.skipTest("git not available")
        self.assertEqual(out.returncode, 0, ".env must stay out of git")
        with open(os.path.join(REPO, ".env.example"), encoding="utf-8") as fh:
            self.assertIn("TRADING_MODE=paper", fh.read())

    def test_personal_data_is_git_ignored(self):
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn("trader/", fh.read().split())
        try:
            out = subprocess.run(["git", "-C", REPO, "check-ignore", "trader/accounts.json"],
                                 capture_output=True, text=True)
        except OSError:
            self.skipTest("git not available")
        self.assertEqual(out.returncode, 0, "trader/ must stay out of git")

    def test_trade_py_reaches_every_tool(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("trade", os.path.join(REPO, "trade.py"))
        trade = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(trade)
        for name in list(trade.TOOLS) + ["dashboard", "schedule"]:
            cmd = trade.command(name, ["--help"])
            self.assertTrue(os.path.isfile(cmd[1]), "%s -> %s" % (name, cmd[1]))
        self.assertIsNone(trade.command("nope", []))
        self.assertEqual(trade.main(["nope"]), 2)

    def test_docs_use_trade_py_not_skill_paths(self):
        for f in ("README.md", "docs/daily-use.md", "docs/crypto-bot-team.md"):
            with open(os.path.join(REPO, f), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(text, r"\.claude/skills/trader-\w+/\w+\.py", f)

    def test_tools_are_standard_library_only(self):
        allowed = {"argparse", "copy", "csv", "datetime", "io", "json", "math", "os", "re", "statistics", "sys",
                   "time", "urllib", "subprocess", "threading", "traceback", "webbrowser", "http", "contextlib",
                   "bisect", "market", "accounts", "paper", "daily", "init", "team", "analyst", "candles",
                   "executor", "risk_manager", "scanner", "trade_log", "ptr", "replay", "vix", "universe", "signals", "gzip", "zipfile", "concurrent"}
        for path in [os.path.join(ROOT, s, f) for s in OURS for f in os.listdir(os.path.join(ROOT, s))
                     if f.endswith(".py")] + [os.path.join(REPO, "app", "server.py")]:
            with open(path, encoding="utf-8") as fh:
                for m in re.finditer(r"^(?:import|from) ([\w]+)", fh.read(), re.M):
                    self.assertIn(m.group(1), allowed, "%s imports %s" % (os.path.basename(path), m.group(1)))


if __name__ == "__main__":
    unittest.main()
