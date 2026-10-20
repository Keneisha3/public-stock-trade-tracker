# How sure can we be? 68 rolling 365-day windows (a new one every 91 days) to 2017-10-18

Gap to the S&P 500 per window. The range is a 90% block-bootstrap confidence range of the average (blocks of 4 neighbouring windows, 5000 resamples). A range above zero is evidence of a real edge.

| strategy | windows | average gap | 90% range | gap above zero |
| --- | ---: | ---: | --- | ---: |
| 70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen) | 68 | +1.4 pts | -1.1 to +4.8 | 36 of 68 |
| 70/30, rebalanced monthly (previous plan) | 68 | +1.4 pts | -1.1 to +4.8 | 36 of 68 |
| Nasdaq 100 (QQQ) | 68 | +1.4 pts | -2.4 to +5.9 | 44 of 68 |
| 70/30, 4 slices re-chosen on different weeks | 68 | +1.4 pts | -1.2 to +4.7 | 36 of 68 |
| Dual momentum alone (single strongest fund) | 68 | +1.2 pts | -5.4 to +7.8 | 29 of 68 |

**Reality check:** with 5 strategies compared, the best one (70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen), +1.4 pts) would look at least this good by luck alone in 65% of bootstrap runs (10% or more: it could easily be luck).

_Windows overlap and come from one stretch of market history; not financial advice._
