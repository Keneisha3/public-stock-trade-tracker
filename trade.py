#!/usr/bin/env python3
"""One command for everything in this project. Run it from the project folder.

    python3 trade.py init                     set up the trader/ folder
    python3 trade.py daily                    the daily run (sync, prices, review, bots, news)
    python3 trade.py dashboard --open         the dashboard in your browser
    python3 trade.py schedule --install       run everything on its own (Mac/Linux)

    python3 trade.py accounts review          your accounts against their strategies
    python3 trade.py paper status             the stock paper bot
    python3 trade.py crypto run               the crypto bot team (paper money)
    python3 trade.py replay                   what $100 would have done in each strategy
    python3 trade.py discover snapshot        today's idea lists (news, Yahoo, Motley Fool, Reddit, the whole market)

Research tools: cdr, gov, copycat, news, pelosi, analyst, screener, budget, risk,
broker, tax, alerts, rebalance. Add --help to any command for its options.
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(REPO, ".claude", "skills")

TOOLS = {
    "init": "trader-init/init.py",
    "daily": "trader-daily/daily.py",
    "accounts": "trader-accounts/accounts.py",
    "market": "trader-accounts/market.py",
    "paper": "trader-paper/paper.py",
    "crypto": "trader-team/team.py",
    "replay": "trader-replay/replay.py",
    "cdr": "trader-replay/cdr.py",
    "gov": "trader-replay/govstakes.py",
    "discover": "trader-discover/discover.py",
    "copycat": "trader-copycat/edgar13f.py",
    "news": "trader-news/news.py",
    "pelosi": "trader-pelosi/ptr.py",
    "analyst": "trader-analyst/facts.py",
    "screener": "trader-screener/screen.py",
    "budget": "trader-budget/size.py",
    "risk": "trader-risk/check.py",
    "broker": "trader-broker/ticket.py",
    "tax": "trader-tax/lots.py",
    "alerts": "trader-alerts/alerts.py",
    "rebalance": "trader-rebalance/rebalance.py",
}


def command(name, args):
    if name in TOOLS:
        return [sys.executable, os.path.join(SKILLS, TOOLS[name])] + args
    if name == "dashboard":
        return [sys.executable, os.path.join(REPO, "app", "server.py")] + args
    if name == "schedule":
        return ["bash", os.path.join(REPO, "scripts", "schedule.sh")] + args
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd = command(argv[0], argv[1:])
    if cmd is None:
        print("unknown command %r. Try: python3 trade.py help" % argv[0], file=sys.stderr)
        return 2
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
