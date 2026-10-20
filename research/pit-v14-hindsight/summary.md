# Walk-forward with a held-out test

Chosen only from what was in the S&P 500 each day (plus index funds and a Canadian list). **Training:** 24 months windows ending none. **Test (never used to choose anything):** the last 12 months, 6 months, 1 month before 2026-10-16, all after 2025-10-16.

## Training periods (gap to the S&P 500 in brackets)

| strategy |  | beat S&P 500 | average gap |
| --- | ---: | ---: |

## Held-out test: the last 12 months, 6 months, 1 month to 2026-10-16 (gap to the S&P 500 in brackets)

| strategy | 12 months | 6 months | 1 month |
| --- | ---: | ---: | ---: |
| Growth (Questrade) | +66.0% (+48.1) | +22.9% (+10.9) | +6.9% (+5.3) |
| Medium term | +59.0% (+41.2) | +11.3% (-0.6) | +2.8% (+1.2) |
| Dividend (Wealthsimple) | +29.2% (+11.3) | +9.1% (-2.9) | +2.0% (+0.3) |
| Stock bot | +19.6% (+1.7) | +0.3% (-11.7) | +1.7% (+0.0) |
| Momentum (top 20 S&P 500) | +46.3% (+28.5) | +8.2% (-3.8) | -5.9% (-7.6) |
| Dual momentum (funds) | +35.8% (+17.9) | +3.7% (-8.3) | -12.3% (-13.9) |
| Insider buying | +1.3% (-16.6) | +1.1% (-10.9) | +2.2% (+0.6) |
| Congress buying | +32.6% (+14.8) | +23.4% (+11.4) | +2.2% (+0.5) |
| Blend (dual + momentum + Congress) | +38.2% (+20.4) | +11.8% (-0.2) | -5.3% (-7.0) |
| 70% Nasdaq 100, 30% dual momentum (2 weeks) | +17.3% (-0.6) | +10.6% (-1.3) | -3.2% (-4.9) |
| Learned score (top 20) | +19.2% (+1.3) | +20.9% (+8.9) | -4.8% (-6.5) |
| Earnings drift (8-K news) | +26.2% (+8.4) | +19.7% (+7.7) | +4.7% (+3.1) |
| Copycat: investors' top 3 (13F) | +20.3% (+2.4) | +12.2% (+0.3) | +0.7% (-0.9) |
| Screener: example rules | +31.6% (+13.8) | +21.8% (+9.8) | -4.2% (-5.8) |
| Pelosi: her buys, mirrored | +1.6% (-16.3) | -12.7% (-24.7) | -2.0% (-3.7) |
| Copycat consensus (C4) | +15.0% (-2.9) | +9.8% (-2.2) | +0.9% (-0.7) |
| Mix M2: 70% Nasdaq 100 + C4 + screener | +18.9% (+1.0) | +13.6% (+1.6) | -0.0% (-1.7) |
| VIX agent | +17.3% (-0.5) | +13.6% (+1.6) | +0.6% (-1.0) |
| S&P 500 (SPY) | +17.9% | +12.0% | +1.6% |
| Nasdaq 100 (QQQ) | +20.3% (+2.5) | +13.6% (+1.7) | +0.6% (-1.0) |
| S&P 500 equal weight (RSP) | +17.1% (-0.8) | +10.1% (-1.9) | +1.7% (+0.1) |
| TSX 60 (XIU.TO) | +23.0% (+5.2) | +8.7% (-3.3) | +1.5% (-0.2) |

The 24 months window ending 2026-10-16 is half training, half test, so it is used for neither (see report-2026-10-16.md).

## Rolling 3-month windows inside each period (beat the S&P 500 / windows)

| strategy | 2026-10-16 |
| --- | ---: |
| Growth (Questrade) | 11 of 12 |
| Medium term | 8 of 12 |
| Dividend (Wealthsimple) | 7 of 12 |
| Stock bot | 7 of 12 |
| Momentum (top 20 S&P 500) | 9 of 12 |
| Dual momentum (funds) | 8 of 12 |
| Insider buying | 4 of 12 |
| Congress buying | 8 of 12 |
| Blend (dual + momentum + Congress) | 8 of 12 |
| 70% Nasdaq 100, 30% dual momentum (2 weeks) | 7 of 12 |
| Learned score (top 20) | 7 of 12 |
| Earnings drift (8-K news) | 6 of 12 |
| Copycat: investors' top 3 (13F) | 7 of 12 |
| Screener: example rules | 7 of 12 |
| Pelosi: her buys, mirrored | 3 of 12 |
| Copycat consensus (C4) | 3 of 12 |
| Mix M2: 70% Nasdaq 100 + C4 + screener | 5 of 12 |
| VIX agent | 5 of 12 |

## Hindsight check: everyone copied the same way (24 months windows)

Pelosi and the 23 investors are famous today, partly because they did well: choosing them is hindsight. So every House member with 10+ disclosed buys is copied like Pelosi (each buy kept a year) and every investor's top 3 like the copycat. If most of them beat the S&P 500, the method works; if only the famous one does, it was hindsight.

| period ending | members who beat the S&P 500 | median member | Pelosi's rank | investors who beat it | median investor |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-10-16 | 16 of 51 | -4.7 pts | 8 of 51 | 11 of 23 | -5.7 pts |

## Settings: chosen on the training periods, checked on the held-out last 12 months

Average gap to the S&P 500 and average worst drop. Pick on the training columns only; the test column is the check.

| agent | setting | training gap (24 months) | training worst drop | test: last 12 months |
| --- | --- | ---: | ---: | ---: |
| congress buys | Congress: 2+ members buying in 90 days (default) | n/a | n/a | +14.8 pts |
| congress buys | Congress: any member buying in 90 days | n/a | n/a | +14.6 pts |
| congress buys | Congress: 2+ members, 180 days | n/a | n/a | -2.4 pts |
| congress buys | Insiders or Congress, 2+ buyers | n/a | n/a | -3.2 pts |
| congress buys | Congress: weighted by size and each member's past record | n/a | n/a | +14.5 pts |
| copycat | C1. Copycat: Berkshire's whole portfolio (what the upstream skill does) | n/a | n/a | +4.5 pts |
| copycat | C2. Copycat: all 23 investors' portfolios, an equal share each | n/a | n/a | -6.3 pts |
| copycat | C3. Copycat: each investor's top 3 ideas (default) | n/a | n/a | +2.4 pts |
| copycat | C4. Copycat: consensus, in the top 10 of 3+ investors | n/a | n/a | -2.9 pts |
| copycat | C5. Copycat: new buys and big adds, top 3 per investor | n/a | n/a | -2.3 pts |
| copycat | C6. Copycat: top 3 ideas, only while above the 200-day | n/a | n/a | +1.9 pts |
| core + dual | Core: 70% Nasdaq 100, 30% dual momentum, monthly (previous plan) | n/a | n/a | +9.2 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum, rebalanced monthly | n/a | n/a | +10.2 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum (volatility target 15%) | n/a | n/a | +0.6 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum (best 2, growth funds) | n/a | n/a | -9.7 pts |
| core + dual | Core: 70/30, Nasdaq 100 only above its 200-day (else bonds) | n/a | n/a | -0.5 pts |
| core + dual | Core: 70/30, dual momentum on 1/3/6/12-month average | n/a | n/a | -8.1 pts |
| core + dual | Core: 70/30, both (trend switch + blended lookbacks) | n/a | n/a | -17.9 pts |
| core + dual | Core: 50/50, both (trend switch + blended lookbacks) | n/a | n/a | -21.8 pts |
| core + dual | Core: Nasdaq 100 only above its 200-day, else bonds | n/a | n/a | -12.7 pts |
| core + dual | Plan A: dual momentum on 12-1 months | n/a | n/a | -6.3 pts |
| core + dual | Plan B: rebalanced every 2 weeks (default) | n/a | n/a | -0.6 pts |
| core + dual | Plan C: satellite half dual momentum, half earnings drift | n/a | n/a | +2.8 pts |
| core + dual | Plan D: satellite = top 20 momentum stocks | n/a | n/a | +11.9 pts |
| core + dual | Plan E: switch funds only for a 5-point lead | n/a | n/a | +11.7 pts |
| core + dual | Plan F: 4 slices, one re-chosen each week (each monthly) | n/a | n/a | +2.0 pts |
| core + dual | Plan G: 2 slices, one re-chosen every 2 weeks (each monthly) | n/a | n/a | +4.2 pts |
| core + dual | Plan H: satellite half dual momentum, half earnings drift with EPS up | n/a | n/a | +1.8 pts |
| core + dual | Plan, money starts in CAD: bank conversion 1.5% | n/a | n/a | -2.2 pts |
| core + dual | Plan, money starts in CAD: Norbert's gambit about 0.1% | n/a | n/a | -0.7 pts |
| core + upstream | K1. 70% Nasdaq 100 + 30% copycat top-3 ideas | n/a | n/a | -1.4 pts |
| core + upstream | K2. 70% Nasdaq 100 + 30% screener picks | n/a | n/a | +6.1 pts |
| core + upstream | K3. 70% Nasdaq 100 + 30% Pelosi's buys | n/a | n/a | -5.7 pts |
| core + upstream | M1. 70% Nasdaq 100 + 10% each: copycat consensus, screener, Pelosi | n/a | n/a | +0.7 pts |
| core + upstream | M2. 70% Nasdaq 100 + 15% copycat consensus + 15% screener (no Pelosi) | n/a | n/a | +1.0 pts |
| core + upstream | M3. 50% Nasdaq 100 + 25% copycat consensus + 25% screener | n/a | n/a | +1.1 pts |
| core + upstream | M4. Half copycat consensus, half screener (no index) | n/a | n/a | +1.0 pts |
| dividend | Default (2% yield floor, 12% cap) | n/a | n/a | +11.3 pts |
| dividend | Higher yield floor: 3.5% | n/a | n/a | +11.3 pts |
| dividend | Rebalance monthly | n/a | n/a | +11.2 pts |
| dividend | Rebalance quarterly | n/a | n/a | +11.2 pts |
| dividend | Today's hand-picked watchlist (hindsight) | n/a | n/a | +5.3 pts |
| dual momentum | Dual momentum: best 1 fund (default) | n/a | n/a | +17.9 pts |
| dual momentum | Dual momentum: best 2 funds | n/a | n/a | +21.6 pts |
| dual momentum | Dual momentum: growth funds only | n/a | n/a | +2.2 pts |
| dual momentum | Dual momentum: volatility target 15% | n/a | n/a | -0.9 pts |
| dual momentum | Dual momentum: volatility target 20% | n/a | n/a | +6.0 pts |
| dual momentum | Dual momentum: fund above its 200-day only | n/a | n/a | +17.9 pts |
| dual momentum | Dual momentum: best 2, growth funds, volatility target 20% | n/a | n/a | -23.6 pts |
| dual momentum | Dual momentum: best 3 funds | n/a | n/a | +18.8 pts |
| dual momentum | Dual momentum: best 5 funds | n/a | n/a | -6.3 pts |
| dual momentum | Dual momentum: 6-month lookback | n/a | n/a | -25.7 pts |
| growth | Default: aggressive (3-month momentum, 30% cap, no cash) | n/a | n/a | +48.1 pts |
| growth | Previous default (12-month momentum, 20% cap, 3% cash) | n/a | n/a | +12.5 pts |
| growth | 12-month momentum | n/a | n/a | +13.5 pts |
| growth | 6-month momentum | n/a | n/a | +36.9 pts |
| growth | Concentrated: 40% cap, 3+ names | n/a | n/a | +48.1 pts |
| growth | Diversified: 10% cap, 10+ names | n/a | n/a | +48.1 pts |
| growth | Tight stop: 15% | n/a | n/a | +48.1 pts |
| growth | Rebalance monthly | n/a | n/a | +48.1 pts |
| growth | Monthly, 10% cap, 10+ names | n/a | n/a | +48.1 pts |
| growth | 6-month momentum, monthly | n/a | n/a | +36.9 pts |
| growth | Rebalance quarterly | n/a | n/a | +48.1 pts |
| growth | Today's hand-picked watchlist (hindsight) | n/a | n/a | +7.4 pts |
| insider buys | Insiders: 2+ buying in 60 days (default) | n/a | n/a | -16.6 pts |
| insider buys | Insiders: 3+ buying in 60 days | n/a | n/a | -5.2 pts |
| insider buys | Insiders: 1+ officer buying, 90 days | n/a | n/a | -17.9 pts |
| insider buys | Insiders: 2+, above the 200-day average | n/a | n/a | -4.6 pts |
| insider buys | Insiders: 2+, top 10 | n/a | n/a | -15.4 pts |
| medium | Default (6-month trend, 15% cap) | n/a | n/a | +41.2 pts |
| medium | Long trend: 12 months | n/a | n/a | +11.1 pts |
| medium | Rebalance monthly | n/a | n/a | +41.2 pts |
| medium | Rebalance quarterly | n/a | n/a | +41.2 pts |
| medium | Monthly, 10% cap, 10+ names | n/a | n/a | +43.1 pts |
| medium | Today's hand-picked watchlist (hindsight) | n/a | n/a | +1.2 pts |
| model | Learned score: top 20 (default) | n/a | n/a | +1.3 pts |
| model | Learned score: top 40 | n/a | n/a | +14.2 pts |
| model | Learned score: price features only | n/a | n/a | +4.9 pts |
| model | Learned score: 70% Nasdaq 100 + 30% top 20 | n/a | n/a | +3.3 pts |
| momentum | Momentum: top 20, 12-1 months, above trend (default) | n/a | n/a | +28.5 pts |
| momentum | Momentum: top 10 | n/a | n/a | +34.6 pts |
| momentum | Momentum: top 40 | n/a | n/a | +25.7 pts |
| momentum | Momentum: 6-1 months | n/a | n/a | +43.8 pts |
| momentum | Momentum: bonds while the S&P 500 is under its 200-day | n/a | n/a | +3.8 pts |
| momentum | Momentum: no trend filter | n/a | n/a | +29.8 pts |
| momentum | Momentum: only names insiders or Congress bought (180 days) | n/a | n/a | +16.5 pts |
| news | Earnings drift: top 20 jumps of 3+ pts, held about 60 days (default) | n/a | n/a | +8.4 pts |
| news | Earnings drift: jumps of 5+ pts | n/a | n/a | +8.2 pts |
| news | Earnings drift: held about 30 days | n/a | n/a | -7.1 pts |
| news | Earnings drift: only if EPS beat the same quarter a year ago | n/a | n/a | -1.9 pts |
| news | Earnings drift: ranked by earnings surprise (EPS vs a year ago) | n/a | n/a | -15.0 pts |
| news | News shock: stock bot trades only breakouts with an 8-K that week | n/a | n/a | -8.1 pts |
| pelosi | P1. Pelosi: what she bought in the last year, sold when she sells (default) | n/a | n/a | -16.3 pts |
| pelosi | P2. Pelosi: every buy kept a year, her sales ignored | n/a | n/a | -10.1 pts |
| pelosi | P3. Pelosi: only trades of $1M or more, mirrored | n/a | n/a | -33.7 pts |
| screener | S1. Screener: its own example rules, top 10 (default) | n/a | n/a | +13.8 pts |
| screener | S2. Screener: the example rules, top 20 | n/a | n/a | +7.2 pts |
| screener | S3. Screener: the example rules, then the 20 with the best 12-1 momentum | n/a | n/a | +0.3 pts |
| screener | S4. Screener: looser rules (growth 5%+, margin 15%+, P/E up to 50), top 20 | n/a | n/a | +6.2 pts |
| stock bot | Stock bot: trades + idle cash in QQQ (default) | n/a | n/a | +1.7 pts |
| stock bot | Stock bot: trades only, idle cash stays cash | n/a | n/a | -7.2 pts |
| stock bot | Stock bot: trades + idle cash in SPY | n/a | n/a | +1.4 pts |
| stock bot | Stock bot: idle in QQQ, hold 5 days | n/a | n/a | -9.9 pts |
| stock bot | Stock bot: today's 30 hand-picked large caps (hindsight) | n/a | n/a | +14.5 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 30 (default) | n/a | n/a | -0.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 25 | n/a | n/a | -3.7 pts |
| vix | VIX agent: S&P 500 unless VIX > 20 | n/a | n/a | -16.2 pts |
| vix | VIX agent: S&P 500 unless VIX > 30 | n/a | n/a | -2.5 pts |
| vix | VIX agent: S&P 500 while VIX is under its 50-day average | n/a | n/a | -8.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 3-month VIX (stress) | n/a | n/a | -9.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 3-month VIX | n/a | n/a | -9.0 pts |

## Coverage and self-checks

- 2026-10-16: 480 of 503 index members priced; self-checks all passed

_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._
