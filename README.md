# public-stock-trade-tracker
## Skills

This repo ships the [Trader skill pack](https://github.com/Jakeschincariol/trader-skill)
(MIT, commit 5189e79) as project skills in `.claude/skills/`: `/trader-copycat`,
`/trader-news`, `/trader-budget`, `/trader-pelosi`, `/trader-analyst`,
`/trader-screener`, `/trader-risk`, `/trader-broker`, `/trader-tax`,
`/trader-alerts`, `/trader-rebalance`.

The tools need Python 3.8+ and nothing else. Set `SEC_USER_AGENT="Your Name you@example.com"`
(or `sec_user_agent` in `trader/config.json`) before using the SEC-backed skills.
Output lands in `trader/`, which is git-ignored so your portfolio stays local.

Not financial advice. No order is placed without your explicit yes.
