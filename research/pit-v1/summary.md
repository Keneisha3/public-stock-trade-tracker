# Walk-forward: 24 months windows ending on 5 different dates

Each period: $100 for the 24 months before the as-of close, chosen only from what was in the S&P 500 that day (plus index funds and a Canadian list). Cell: return (gap to the S&P 500).

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | 2026-10-16 | beat S&P 500 | average gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | +17.9% (-8.9) | +22.9% (-6.6) | +9.3% (-2.5) | +5.7% (-56.4) | +24.2% (-12.2) | 0 of 5 | -17.3 pts |
| Medium term | +20.4% (-6.4) | +23.2% (-6.2) | +11.4% (-0.4) | +33.1% (-29.0) | +27.7% (-8.8) | 0 of 5 | -10.2 pts |
| Dividend (Wealthsimple) | +17.7% (-9.1) | +12.4% (-17.1) | +20.3% (+8.4) | +31.8% (-30.2) | +52.6% (+16.2) | 2 of 5 | -6.4 pts |
| Stock bot | -5.6% (-32.4) | -1.6% (-31.1) | +21.6% (+9.7) | +72.9% (+10.9) | +0.7% (-35.7) | 2 of 5 | -15.7 pts |
| VIX agent | +24.1% (-2.6) | +27.3% (-2.1) | -17.9% (-29.7) | +82.1% (+20.1) | +39.1% (+2.7) | 2 of 5 | -2.4 pts |
| S&P 500 (SPY) | +26.8% | +29.4% | +11.8% | +62.1% | +36.4% | – | – |
| Nasdaq 100 (QQQ) | +38.1% (+11.3) | +66.8% (+37.3) | -3.8% (-15.7) | +85.2% (+23.1) | +48.3% (+11.9) | 4 of 5 | +13.6 pts |
| S&P 500 equal weight (RSP) | +21.5% (-5.3) | +16.2% (-13.2) | +23.5% (+11.6) | +41.7% (-20.3) | +24.1% (-12.3) | 1 of 5 | -7.9 pts |
| TSX 60 (XIU.TO) | +11.5% (-15.3) | +13.9% (-15.5) | +20.7% (+8.8) | +38.3% (-23.7) | +50.8% (+14.4) | 2 of 5 | -6.3 pts |

## Rolling 3-month windows inside each period (beat the S&P 500 / windows)

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | 2026-10-16 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | 3 of 12 | 5 of 12 | 8 of 12 | 3 of 12 | 11 of 12 |
| Medium term | 5 of 12 | 0 of 12 | 4 of 12 | 3 of 12 | 8 of 12 |
| Dividend (Wealthsimple) | 8 of 12 | 1 of 12 | 5 of 12 | 3 of 12 | 7 of 12 |
| Stock bot | 3 of 12 | 3 of 12 | 6 of 12 | 6 of 12 | 7 of 12 |
| VIX agent | 3 of 12 | 7 of 12 | 2 of 12 | 5 of 12 | 5 of 12 |

## Coverage and self-checks

- 2019-10-18: 405 of 506 index members priced; self-checks FAILED: S&P 500 row matches the raw price change in CAD (overnight gap, slippage and dividends allowed)
- 2020-10-16: 413 of 505 index members priced; self-checks FAILED: S&P 500 row matches the raw price change in CAD (overnight gap, slippage and dividends allowed)
- 2022-10-14: 441 of 505 index members priced; self-checks FAILED: S&P 500 row matches the raw price change in CAD (overnight gap, slippage and dividends allowed)
- 2024-10-18: 465 of 503 index members priced; self-checks FAILED: S&P 500 row matches the raw price change in CAD (overnight gap, slippage and dividends allowed)
- 2026-10-16: 480 of 503 index members priced; self-checks all passed

_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._
