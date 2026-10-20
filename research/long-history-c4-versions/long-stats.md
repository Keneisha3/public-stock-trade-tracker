# How sure can we be? 68 rolling 365-day windows (a new one every 91 days) to 2017-10-18

Gap to the S&P 500 per window. The range is a 90% block-bootstrap confidence range of the average (blocks of 4 neighbouring windows, 5000 resamples). A range above zero is evidence of a real edge.

| strategy | windows | average gap | 90% range | gap above zero |
| --- | ---: | ---: | --- | ---: |
| C8. Copycat: consensus, in the top 10 of 4+ investors | 68 | +10.0 pts | +5.1 to +15.3 | 45 of 68 |
| C9. Copycat: consensus, in the top 10 of 2+ investors | 68 | +9.1 pts | +5.3 to +11.9 | 57 of 68 |
| Dual momentum alone (single strongest fund) | 68 | +8.0 pts | +0.8 to +18.1 | 40 of 68 |
| C7. Copycat: consensus, in the top 5 of 3+ investors | 68 | +7.3 pts | +2.7 to +12.0 | 45 of 68 |
| C10. Copycat: consensus top 10 of 3+, more money where more investors agree | 68 | +6.1 pts | +2.5 to +9.5 | 45 of 68 |
| Copycat consensus (C4) | 68 | +5.2 pts | +1.5 to +8.6 | 44 of 68 |
| 70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen) | 68 | +3.1 pts | -0.0 to +7.6 | 44 of 68 |
| 70/30, rebalanced monthly (previous plan) | 68 | +2.9 pts | -0.1 to +7.3 | 40 of 68 |
| 70/30, 4 slices re-chosen on different weeks | 68 | +2.9 pts | -0.2 to +7.4 | 42 of 68 |
| 70% Nasdaq 100 + 30% C4 | 68 | +1.9 pts | -1.2 to +5.4 | 47 of 68 |
| Nasdaq 100 (QQQ) | 68 | +0.5 pts | -3.3 to +5.0 | 42 of 68 |

**Reality check:** with 11 strategies compared, the best one (C8. Copycat: consensus, in the top 10 of 4+ investors, +10.0 pts) would look at least this good by luck alone in 6% of bootstrap runs (under 10%: probably a real edge).

_Windows overlap and come from one stretch of market history; not financial advice._
