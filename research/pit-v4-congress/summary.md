# Walk-forward: 24 months windows ending on 5 different dates

Each period: $100 for the 24 months before the as-of close, chosen only from what was in the S&P 500 that day (plus index funds and a Canadian list). Cell: return (gap to the S&P 500).

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | 2026-10-16 | beat S&P 500 | average gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | +17.9% (-8.9) | +22.9% (-6.6) | +9.3% (-2.5) | +5.7% (-56.4) | +24.2% (-12.2) | 0 of 5 | -17.3 pts |
| Medium term | +20.4% (-6.4) | +23.2% (-6.2) | +11.4% (-0.4) | +33.1% (-29.0) | +27.7% (-8.8) | 0 of 5 | -10.2 pts |
| Dividend (Wealthsimple) | +17.8% (-9.0) | +13.9% (-15.6) | +21.3% (+9.5) | +31.5% (-30.5) | +52.1% (+15.7) | 2 of 5 | -6.0 pts |
| Stock bot | -5.6% (-32.4) | -1.6% (-31.1) | +21.6% (+9.7) | +72.9% (+10.9) | +0.7% (-35.7) | 2 of 5 | -15.7 pts |
| Momentum (top 20 S&P 500) | +4.9% (-21.9) | +5.5% (-23.9) | +14.1% (+2.2) | +63.3% (+1.2) | +74.7% (+38.3) | 3 of 5 | -0.8 pts |
| Dual momentum (funds) | +11.5% (-15.3) | +35.4% (+5.9) | +58.3% (+46.5) | +72.2% (+10.1) | +131.5% (+95.1) | 4 of 5 | +28.5 pts |
| Insider buying | n/a | n/a | n/a | n/a | n/a | 0 of 0 | – |
| Congress buying | +25.1% (-1.7) | +25.5% (-3.9) | +25.3% (+13.4) | +47.5% (-14.5) | +55.6% (+19.2) | 2 of 5 | +2.5 pts |
| VIX agent | +24.1% (-2.6) | +27.3% (-2.1) | -17.9% (-29.7) | +82.1% (+20.1) | +39.1% (+2.7) | 2 of 5 | -2.4 pts |
| S&P 500 (SPY) | +26.8% | +29.4% | +11.8% | +62.1% | +36.4% | – | – |
| Nasdaq 100 (QQQ) | +38.1% (+11.3) | +66.8% (+37.3) | -3.8% (-15.7) | +85.2% (+23.1) | +48.3% (+11.9) | 4 of 5 | +13.6 pts |
| S&P 500 equal weight (RSP) | +21.5% (-5.3) | +16.2% (-13.2) | +23.5% (+11.6) | +41.7% (-20.3) | +24.1% (-12.3) | 1 of 5 | -7.9 pts |
| TSX 60 (XIU.TO) | +11.5% (-15.3) | +13.9% (-15.5) | +20.7% (+8.8) | +38.3% (-23.7) | +50.8% (+14.4) | 2 of 5 | -6.3 pts |

## Rolling 3-month windows inside each period (beat the S&P 500 / windows)

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | 2026-10-16 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | 3 of 12 | 5 of 12 | 8 of 12 | 3 of 12 | 11 of 12 |
| Medium term | 5 of 12 | 1 of 12 | 4 of 12 | 3 of 12 | 8 of 12 |
| Dividend (Wealthsimple) | 8 of 12 | 1 of 12 | 5 of 12 | 3 of 12 | 7 of 12 |
| Stock bot | 3 of 12 | 3 of 12 | 6 of 12 | 6 of 12 | 7 of 12 |
| Momentum (top 20 S&P 500) | 3 of 12 | 3 of 12 | 7 of 12 | 8 of 12 | 9 of 12 |
| Dual momentum (funds) | 5 of 12 | 4 of 12 | 7 of 12 | 9 of 12 | 8 of 12 |
| Congress buying | 8 of 12 | 8 of 12 | 6 of 12 | 5 of 12 | 8 of 12 |
| VIX agent | 3 of 12 | 7 of 12 | 2 of 12 | 5 of 12 | 5 of 12 |

## Settings: chosen on 2019-10-18, 2020-10-16, 2022-10-14, confirmed on 2024-10-18, 2026-10-16

Average gap to the S&P 500 over 24 months. Pick on the left column only; the right column is the test.

| agent | setting | selection periods | confirmation periods |
| --- | --- | ---: | ---: |
| congress buys | Congress: 2+ members, 180 days | +10.6 pts | -8.6 pts |
| congress buys | Congress: any member buying in 90 days | +8.2 pts | -6.6 pts |
| congress buys | Congress: 2+ members buying in 90 days (default) | +2.6 pts | +2.3 pts |
| dividend | Today's hand-picked watchlist (hindsight) | -4.5 pts | -14.4 pts |
| dividend | Rebalance monthly | -5.0 pts | -7.6 pts |
| dividend | Default (2% yield floor, 12% cap) | -5.0 pts | -7.4 pts |
| dividend | Higher yield floor: 3.5% | -5.0 pts | -7.4 pts |
| dividend | Rebalance quarterly | -5.4 pts | -7.6 pts |
| dual momentum | Dual momentum: best 1 fund (default) | +12.4 pts | +52.6 pts |
| dual momentum | Dual momentum: best 3 funds | +5.6 pts | +14.0 pts |
| dual momentum | Dual momentum: best 5 funds | +3.8 pts | +3.1 pts |
| dual momentum | Dual momentum: 6-month lookback | -28.7 pts | -24.8 pts |
| growth | Today's hand-picked watchlist (hindsight) | +31.0 pts | +115.5 pts |
| growth | 6-month momentum | -5.7 pts | -18.9 pts |
| growth | 6-month momentum, monthly | -5.7 pts | -18.9 pts |
| growth | Default: aggressive (3-month momentum, 30% cap, no cash) | -6.0 pts | -34.3 pts |
| growth | Concentrated: 40% cap, 3+ names | -6.0 pts | -34.3 pts |
| growth | Diversified: 10% cap, 10+ names | -6.0 pts | -34.9 pts |
| growth | Tight stop: 15% | -6.0 pts | -34.3 pts |
| growth | Rebalance monthly | -6.0 pts | -34.3 pts |
| growth | Monthly, 10% cap, 10+ names | -6.0 pts | -35.0 pts |
| growth | Rebalance quarterly | -6.0 pts | -34.3 pts |
| growth | 12-month momentum | -11.8 pts | -29.6 pts |
| growth | Previous default (12-month momentum, 20% cap, 3% cash) | -11.8 pts | -30.0 pts |
| medium | Today's hand-picked watchlist (hindsight) | +39.0 pts | +47.7 pts |
| medium | Default (6-month trend, 15% cap) | -4.4 pts | -18.9 pts |
| medium | Rebalance monthly | -4.4 pts | -18.9 pts |
| medium | Rebalance quarterly | -4.4 pts | -18.9 pts |
| medium | Monthly, 10% cap, 10+ names | -4.4 pts | -18.9 pts |
| medium | Long trend: 12 months | -9.8 pts | -21.3 pts |
| momentum | Momentum: 6-1 months | -5.4 pts | +15.7 pts |
| momentum | Momentum: no trend filter | -5.7 pts | +8.0 pts |
| momentum | Momentum: only names insiders or Congress bought (180 days) | -9.1 pts | -7.5 pts |
| momentum | Momentum: top 40 | -11.0 pts | +3.6 pts |
| momentum | Momentum: top 20, 12-1 months, above trend (default) | -14.5 pts | +19.8 pts |
| momentum | Momentum: top 10 | -16.5 pts | +39.9 pts |
| momentum | Momentum: bonds while the S&P 500 is under its 200-day | -17.7 pts | -8.1 pts |
| stock bot | Stock bot: today's 30 hand-picked large caps (hindsight) | -1.9 pts | +28.2 pts |
| stock bot | Stock bot: idle in QQQ, hold 5 days | -15.4 pts | -10.6 pts |
| stock bot | Stock bot: trades + idle cash in QQQ (default) | -17.9 pts | -12.4 pts |
| stock bot | Stock bot: trades + idle cash in SPY | -21.4 pts | -21.0 pts |
| stock bot | Stock bot: trades only, idle cash stays cash | -26.1 pts | -39.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 3-month VIX | +0.1 pts | +2.7 pts |
| vix | VIX agent: S&P 500 unless VIX > 3-month VIX (stress) | -2.3 pts | -9.0 pts |
| vix | VIX agent: S&P 500 unless VIX > 25 | -5.3 pts | -13.1 pts |
| vix | VIX agent: S&P 500 while VIX is under its 50-day average | -8.5 pts | -26.5 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 30 (default) | -11.5 pts | +11.4 pts |
| vix | VIX agent: S&P 500 unless VIX > 30 | -13.5 pts | -3.9 pts |
| vix | VIX agent: S&P 500 unless VIX > 20 | -16.4 pts | -31.8 pts |

## Coverage and self-checks

- 2019-10-18: 405 of 506 index members priced; self-checks all passed
- 2020-10-16: 413 of 505 index members priced; self-checks all passed
- 2022-10-14: 441 of 505 index members priced; self-checks all passed
- 2024-10-18: 465 of 503 index members priced; self-checks all passed
- 2026-10-16: 480 of 503 index members priced; self-checks all passed

_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._
