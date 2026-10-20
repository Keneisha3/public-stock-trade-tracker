# How sure can we be? 68 rolling 365-day windows (a new one every 91 days) to 2017-10-18

Gap to the S&P 500 per window. The range is a 90% block-bootstrap confidence range of the average (blocks of 4 neighbouring windows, 5000 resamples). A range above zero is evidence of a real edge.

| strategy | windows | average gap | 90% range | gap above zero |
| --- | ---: | ---: | --- | ---: |
| Dual momentum alone (single strongest fund) | 68 | +8.0 pts | +0.8 to +18.1 | 40 of 68 |
| 70% Nasdaq 100 + 30% dual momentum, every 2 weeks (chosen) | 68 | +3.1 pts | -0.0 to +7.6 | 44 of 68 |
| 70/30, rebalanced monthly (previous plan) | 68 | +2.9 pts | -0.1 to +7.3 | 40 of 68 |
| 70/30, 4 slices re-chosen on different weeks | 68 | +2.9 pts | -0.2 to +7.4 | 42 of 68 |
| Nasdaq 100 (QQQ) | 68 | +0.5 pts | -3.3 to +5.0 | 42 of 68 |

**Reality check:** with 5 strategies compared, the best one (Dual momentum alone (single strongest fund), +8.0 pts) would look at least this good by luck alone in 11% of bootstrap runs (10% or more: it could easily be luck).

_Windows overlap and come from one stretch of market history; not financial advice._
