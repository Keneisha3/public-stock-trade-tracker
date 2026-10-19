# How sure can we be? 28 rolling 365-day windows (a new one every 91 days) to 2025-10-16

Gap to the S&P 500 per window. The range is a 90% block-bootstrap confidence range of the average (blocks of 4 neighbouring windows, 5000 resamples). A range above zero is evidence of a real edge.

| strategy | windows | average gap | 90% range | gap above zero |
| --- | ---: | ---: | --- | ---: |
| dual momentum | 28 | +13.4 pts | +2.0 to +26.9 | 16 of 28 |
| core + dual | 28 | +8.5 pts | +3.9 to +15.2 | 23 of 28 |
| Nasdaq 100 (QQQ) | 28 | +5.8 pts | +0.1 to +12.3 | 18 of 28 |
| blend | 28 | +3.1 pts | -1.7 to +8.1 | 16 of 28 |
| growth | 28 | +2.1 pts | -1.3 to +6.0 | 12 of 28 |
| congress buys | 28 | +0.1 pts | -2.3 to +1.9 | 13 of 28 |
| insider buys | 28 | -1.1 pts | -4.4 to +3.6 | 11 of 28 |
| medium | 28 | -1.2 pts | -5.6 to +2.8 | 14 of 28 |
| VIX agent | 28 | -2.5 pts | -8.2 to +3.5 | 10 of 28 |
| TSX 60 (XIU.TO) | 28 | -3.5 pts | -8.6 to +0.2 | 10 of 28 |
| stock bot | 28 | -4.0 pts | -9.3 to +5.0 | 13 of 28 |
| momentum | 28 | -4.1 pts | -10.4 to +2.2 | 10 of 28 |
| dividend | 28 | -5.1 pts | -12.5 to +0.1 | 11 of 28 |

**Reality check:** with 13 strategies compared, the best one (dual momentum, +13.4 pts) would look at least this good by luck alone in 6% of bootstrap runs (under 10%: probably a real edge).

_Windows overlap and come from one stretch of market history; not financial advice._
