#!/bin/bash
# Run everything on its own schedule (macOS / Linux, using cron):
#   - the daily run (sync, prices, review, history, stock paper bot, news, Congress, alerts)
#     at 5:30 p.m. your computer's time on weekdays, after the market closes
#   - one crypto bot team cycle every 15 minutes, all day, every day (paper money)
#
#   python3 trade.py schedule            show what it would add
#   python3 trade.py schedule --install  add it (replaces anything this script added before)
#   python3 trade.py schedule --remove   take it all out again
#
# Your computer has to be on (and awake) for a run to happen. Missed crypto
# cycles are logged as downtime. Windows: see docs/daily-use.md.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
PY=$(command -v python3 || true)
TAG="# public-stock-trade-tracker"
if [ -z "$PY" ]; then
  echo "python3 not found: install Python 3.9+ first" >&2
  exit 1
fi
LINES="30 17 * * 1-5 cd \"$REPO\" && \"$PY\" trade.py daily > trader/daily.log 2>&1 $TAG
*/15 * * * * cd \"$REPO\" && \"$PY\" trade.py crypto run --once >> trader/team/cron.log 2>&1 $TAG"

current() { crontab -l 2>/dev/null | grep -v "$TAG" || true; }

case "${1:-}" in
  --install)
    [ -f "$REPO/trader/accounts.json" ] || "$PY" "$REPO/trade.py" init --dir "$REPO/trader"
    keep=$(current)  # read first: never pipe crontab -l straight into crontab -
    printf '%s\n%s\n' "$keep" "$LINES" | sed '/^$/d' | crontab -
    echo "Scheduled. Check with: crontab -l"
    echo "Logs: trader/daily.log and trader/team/cron.log. Stop the crypto bot any time: python3 trade.py crypto kill"
    ;;
  --remove)
    keep=$(current)
    printf '%s\n' "$keep" | sed '/^$/d' | crontab -
    echo "Removed the schedule."
    ;;
  *)
    echo "This would add to your crontab:"
    echo
    echo "$LINES"
    echo
    echo "Run again with --install to add it."
    ;;
esac
