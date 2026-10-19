# Walk-forward with a held-out test

Chosen only from what was in the S&P 500 each day (plus index funds and a Canadian list). **Training:** 24 months windows ending 2019-10-18, 2020-10-16, 2022-10-14, 2024-10-18. **Test (never used to choose anything):** the last 12 months, 6 months, 1 month before 2026-10-16, all after 2025-10-16.

## Training periods (gap to the S&P 500 in brackets)

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | beat S&P 500 | average gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | +17.9% (-8.9) | +22.9% (-6.6) | +9.3% (-2.5) | +5.7% (-56.4) | 0 of 4 | -18.6 pts |
| Medium term | +20.4% (-6.4) | +23.2% (-6.2) | +11.4% (-0.4) | +33.1% (-29.0) | 0 of 4 | -10.5 pts |
| Dividend (Wealthsimple) | +17.8% (-9.0) | +13.9% (-15.6) | +21.3% (+9.5) | +31.5% (-30.5) | 1 of 4 | -11.4 pts |
| Stock bot | -5.6% (-32.4) | -1.6% (-31.1) | +21.6% (+9.7) | +72.9% (+10.9) | 2 of 4 | -10.7 pts |
| Momentum (top 20 S&P 500) | +4.9% (-21.9) | +5.5% (-23.9) | +14.1% (+2.2) | +63.3% (+1.2) | 2 of 4 | -10.6 pts |
| Dual momentum (funds) | +11.5% (-15.3) | +35.4% (+5.9) | +58.3% (+46.5) | +72.2% (+10.1) | 3 of 4 | +11.8 pts |
| Insider buying | +8.7% (-18.1) | +12.2% (-17.2) | +15.6% (+3.8) | +61.6% (-0.5) | 1 of 4 | -8.0 pts |
| Congress buying | +25.1% (-1.7) | +25.5% (-3.9) | +25.3% (+13.4) | +47.5% (-14.5) | 1 of 4 | -1.7 pts |
| Blend (dual + momentum + Congress) | +13.8% (-12.9) | +22.1% (-7.3) | +32.5% (+20.7) | +61.0% (-1.1) | 1 of 4 | -0.2 pts |
| Half Nasdaq 100, half dual momentum | +24.8% (-2.0) | +51.1% (+21.6) | +27.3% (+15.4) | +78.7% (+16.6) | 3 of 4 | +12.9 pts |
| VIX agent | +24.1% (-2.6) | +27.3% (-2.1) | -17.9% (-29.7) | +82.1% (+20.1) | 1 of 4 | -3.6 pts |
| S&P 500 (SPY) | +26.8% | +29.4% | +11.8% | +62.1% | – | – |
| Nasdaq 100 (QQQ) | +38.1% (+11.3) | +66.8% (+37.3) | -3.8% (-15.7) | +85.2% (+23.1) | 3 of 4 | +14.0 pts |
| S&P 500 equal weight (RSP) | +21.5% (-5.3) | +16.2% (-13.2) | +23.5% (+11.6) | +41.7% (-20.3) | 1 of 4 | -6.8 pts |
| TSX 60 (XIU.TO) | +11.5% (-15.3) | +13.9% (-15.5) | +20.7% (+8.8) | +38.3% (-23.7) | 1 of 4 | -11.4 pts |

## Held-out test: the last 12 months, 6 months, 1 month to 2026-10-16 (gap to the S&P 500 in brackets)

| strategy | 12 months | 6 months | 1 month |
| --- | ---: | ---: | ---: |
| Growth (Questrade) | +66.0% (+48.1) | +22.9% (+10.9) | +6.9% (+5.3) |
| Medium term | +59.0% (+41.2) | +11.3% (-0.6) | +2.8% (+1.2) |
| Dividend (Wealthsimple) | +29.2% (+11.4) | +7.8% (-4.2) | +2.0% (+0.3) |
| Stock bot | +19.6% (+1.7) | +0.3% (-11.7) | +1.7% (+0.0) |
| Momentum (top 20 S&P 500) | +46.3% (+28.5) | +8.2% (-3.8) | -5.9% (-7.6) |
| Dual momentum (funds) | +35.8% (+17.9) | +3.7% (-8.3) | -12.3% (-13.9) |
| Insider buying | +2.8% (-15.1) | -1.6% (-13.6) | +1.6% (+0.0) |
| Congress buying | +32.6% (+14.8) | +23.4% (+11.4) | +2.2% (+0.5) |
| Blend (dual + momentum + Congress) | +38.2% (+20.4) | +11.8% (-0.2) | -5.3% (-7.0) |
| Half Nasdaq 100, half dual momentum | +28.1% (+10.2) | +8.7% (-3.3) | -5.8% (-7.5) |
| VIX agent | +17.3% (-0.5) | +13.6% (+1.6) | +0.6% (-1.0) |
| S&P 500 (SPY) | +17.9% | +12.0% | +1.6% |
| Nasdaq 100 (QQQ) | +20.3% (+2.5) | +13.6% (+1.7) | +0.6% (-1.0) |
| S&P 500 equal weight (RSP) | +17.1% (-0.8) | +10.1% (-1.9) | +1.7% (+0.1) |
| TSX 60 (XIU.TO) | +23.0% (+5.2) | +8.7% (-3.3) | +1.5% (-0.2) |

The 24 months window ending 2026-10-16 is half training, half test, so it is used for neither (see report-2026-10-16.md).

## Rolling 3-month windows inside each period (beat the S&P 500 / windows)

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | 2026-10-16 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | 3 of 12 | 5 of 12 | 8 of 12 | 3 of 12 | 11 of 12 |
| Medium term | 5 of 12 | 1 of 12 | 4 of 12 | 3 of 12 | 8 of 12 |
| Dividend (Wealthsimple) | 8 of 12 | 1 of 12 | 5 of 12 | 3 of 12 | 7 of 12 |
| Stock bot | 3 of 12 | 3 of 12 | 6 of 12 | 6 of 12 | 7 of 12 |
| Momentum (top 20 S&P 500) | 3 of 12 | 3 of 12 | 7 of 12 | 8 of 12 | 9 of 12 |
| Dual momentum (funds) | 5 of 12 | 4 of 12 | 7 of 12 | 9 of 12 | 8 of 12 |
| Insider buying | 1 of 12 | 10 of 12 | 8 of 12 | 5 of 12 | 2 of 12 |
| Congress buying | 8 of 12 | 8 of 12 | 6 of 12 | 5 of 12 | 8 of 12 |
| Blend (dual + momentum + Congress) | 3 of 12 | 4 of 12 | 7 of 12 | 8 of 12 | 8 of 12 |
| Half Nasdaq 100, half dual momentum | 5 of 12 | 8 of 12 | 7 of 12 | 8 of 12 | 8 of 12 |
| VIX agent | 3 of 12 | 7 of 12 | 2 of 12 | 5 of 12 | 5 of 12 |

## Settings: chosen on the training periods, checked on the held-out last 12 months

Average gap to the S&P 500. Pick on the training column only; the test column is the check.

| agent | setting | training (24 months) | test: last 12 months |
| --- | --- | ---: | ---: |
| congress buys | Congress: 2+ members, 180 days | +2.3 pts | -2.4 pts |
| congress buys | Congress: any member buying in 90 days | -1.5 pts | +14.6 pts |
| congress buys | Congress: 2+ members buying in 90 days (default) | -1.7 pts | +14.8 pts |
| congress buys | Insiders or Congress, 2+ buyers | -8.2 pts | -2.5 pts |
| dividend | Rebalance monthly | -11.4 pts | +11.2 pts |
| dividend | Default (2% yield floor, 12% cap) | -11.4 pts | +11.4 pts |
| dividend | Higher yield floor: 3.5% | -11.4 pts | +11.4 pts |
| dividend | Rebalance quarterly | -11.8 pts | +11.2 pts |
| dividend | Today's hand-picked watchlist (hindsight) | -14.1 pts | +5.3 pts |
| dual momentum | Dual momentum: best 1 fund (default) | +11.8 pts | +17.9 pts |
| dual momentum | Dual momentum: best 3 funds | -1.1 pts | +18.8 pts |
| dual momentum | Dual momentum: best 5 funds | -4.5 pts | -6.3 pts |
| dual momentum | Dual momentum: 6-month lookback | -29.0 pts | -25.7 pts |
| growth | Today's hand-picked watchlist (hindsight) | +77.2 pts | +7.4 pts |
| growth | 6-month momentum | -16.3 pts | +36.9 pts |
| growth | 6-month momentum, monthly | -16.3 pts | +36.9 pts |
| growth | Default: aggressive (3-month momentum, 30% cap, no cash) | -18.6 pts | +48.1 pts |
| growth | Concentrated: 40% cap, 3+ names | -18.6 pts | +48.1 pts |
| growth | Diversified: 10% cap, 10+ names | -18.6 pts | +48.1 pts |
| growth | Tight stop: 15% | -18.6 pts | +48.1 pts |
| growth | Rebalance monthly | -18.6 pts | +48.1 pts |
| growth | Monthly, 10% cap, 10+ names | -18.6 pts | +48.1 pts |
| growth | Rebalance quarterly | -18.6 pts | +48.1 pts |
| growth | 12-month momentum | -22.5 pts | +13.5 pts |
| growth | Previous default (12-month momentum, 20% cap, 3% cash) | -22.6 pts | +12.5 pts |
| insider buys | Insiders: 3+ buying in 60 days | -0.2 pts | -3.6 pts |
| insider buys | Insiders: 2+, above the 200-day average | -3.2 pts | -4.3 pts |
| insider buys | Insiders: 2+ buying in 60 days (default) | -8.0 pts | -15.1 pts |
| insider buys | Insiders: 1+ officer buying, 90 days | -10.0 pts | -11.5 pts |
| insider buys | Insiders: 2+, top 10 | -16.1 pts | -8.7 pts |
| medium | Today's hand-picked watchlist (hindsight) | +53.3 pts | +1.2 pts |
| medium | Default (6-month trend, 15% cap) | -10.5 pts | +41.2 pts |
| medium | Rebalance monthly | -10.5 pts | +41.2 pts |
| medium | Rebalance quarterly | -10.5 pts | +41.2 pts |
| medium | Monthly, 10% cap, 10+ names | -10.5 pts | +43.1 pts |
| medium | Long trend: 12 months | -13.8 pts | +11.1 pts |
| momentum | Momentum: no trend filter | -7.8 pts | +29.8 pts |
| momentum | Momentum: only names insiders or Congress bought (180 days) | -7.9 pts | +17.3 pts |
| momentum | Momentum: 6-1 months | -8.2 pts | +43.8 pts |
| momentum | Momentum: top 40 | -10.5 pts | +25.7 pts |
| momentum | Momentum: top 20, 12-1 months, above trend (default) | -10.6 pts | +28.5 pts |
| momentum | Momentum: bonds while the S&P 500 is under its 200-day | -11.1 pts | +3.8 pts |
| momentum | Momentum: top 10 | -12.7 pts | +34.6 pts |
| stock bot | Stock bot: today's 30 hand-picked large caps (hindsight) | +4.3 pts | +14.5 pts |
| stock bot | Stock bot: trades + idle cash in QQQ (default) | -10.7 pts | +1.7 pts |
| stock bot | Stock bot: idle in QQQ, hold 5 days | -12.1 pts | -9.9 pts |
| stock bot | Stock bot: trades + idle cash in SPY | -17.1 pts | +1.4 pts |
| stock bot | Stock bot: trades only, idle cash stays cash | -29.3 pts | -7.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 3-month VIX | +3.1 pts | -9.0 pts |
| vix | VIX agent: S&P 500 unless VIX > 3-month VIX (stress) | -3.3 pts | -9.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 30 (default) | -3.6 pts | -0.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 25 | -8.3 pts | -3.7 pts |
| vix | VIX agent: S&P 500 unless VIX > 30 | -10.5 pts | -2.5 pts |
| vix | VIX agent: S&P 500 while VIX is under its 50-day average | -15.4 pts | -8.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 20 | -20.5 pts | -16.2 pts |

## Coverage and self-checks

- 2019-10-18: 405 of 506 index members priced; self-checks all passed
- 2020-10-16: 413 of 505 index members priced; self-checks all passed
- 2022-10-14: 441 of 505 index members priced; self-checks all passed
- 2024-10-18: 465 of 503 index members priced; self-checks all passed
- 2026-10-16: 480 of 503 index members priced; self-checks all passed

_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._
