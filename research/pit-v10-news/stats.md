# How sure can we be? 28 rolling 365-day windows (a new one every 91 days) to 2025-10-17

Gap to the S&P 500 per window. The range is a 90% block-bootstrap confidence range of the average (blocks of 4 neighbouring windows, 5000 resamples). A range above zero is evidence of a real edge.

| strategy | windows | average gap | 90% range | gap above zero |
| --- | ---: | ---: | --- | ---: |
| core + dual | 28 | +6.3 pts | +2.6 to +11.9 | 21 of 28 |
| Nasdaq 100 (QQQ) | 28 | +6.0 pts | +0.3 to +12.5 | 18 of 28 |
| dual momentum | 28 | +5.1 pts | -4.2 to +16.6 | 15 of 28 |
| growth | 28 | +1.8 pts | -1.3 to +5.4 | 14 of 28 |
| congress buys | 28 | +0.3 pts | -1.7 to +1.5 | 15 of 28 |
| blend | 28 | +0.3 pts | -3.9 to +4.9 | 16 of 28 |
| insider buys | 28 | -1.2 pts | -3.8 to +2.6 | 10 of 28 |
| medium | 28 | -1.7 pts | -5.7 to +2.5 | 12 of 28 |
| VIX agent | 28 | -2.4 pts | -8.1 to +3.5 | 9 of 28 |
| model | 28 | -3.2 pts | -14.0 to +6.5 | 13 of 28 |
| TSX 60 (XIU.TO) | 28 | -3.5 pts | -8.3 to +0.2 | 10 of 28 |
| momentum | 28 | -4.5 pts | -10.1 to +2.0 | 12 of 28 |
| stock bot | 28 | -5.2 pts | -10.1 to +3.1 | 11 of 28 |
| dividend | 28 | -5.2 pts | -12.3 to -0.2 | 12 of 28 |

**Reality check:** with 14 strategies compared, the best one (core + dual, +6.3 pts) would look at least this good by luck alone in 49% of bootstrap runs (10% or more: it could easily be luck).

_Windows overlap and come from one stretch of market history; not financial advice._
