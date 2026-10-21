# Walk-forward with a held-out test

Chosen only from what was in the S&P 500 each day (plus index funds and a Canadian list). **Training:** 24 months windows ending 2019-10-18, 2020-10-16, 2022-10-14, 2024-10-18. **Test (never used to choose anything):** the last 12 months, 6 months, 1 month before 2026-10-16, all after 2025-10-16.

## Training periods (gap to the S&P 500 in brackets)

| strategy | 2019-10-18 | 2020-10-16 | 2022-10-14 | 2024-10-18 | beat S&P 500 | average gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Growth (Questrade) | +17.9% (-8.9) | +22.9% (-6.6) | +9.3% (-2.5) | +5.7% (-56.4) | 0 of 4 | -18.6 pts |
| Medium term | +20.4% (-6.4) | +23.2% (-6.2) | +11.4% (-0.4) | +33.1% (-29.0) | 0 of 4 | -10.5 pts |
| Dividend (Wealthsimple) | +17.7% (-9.1) | +12.4% (-17.1) | +20.3% (+8.4) | +31.8% (-30.2) | 1 of 4 | -12.0 pts |
| Stock bot | -5.6% (-32.4) | -1.6% (-31.1) | +21.6% (+9.7) | +72.9% (+10.9) | 2 of 4 | -10.7 pts |
| Momentum (top 20 S&P 500) | +4.9% (-21.9) | +5.5% (-23.9) | +14.1% (+2.2) | +63.3% (+1.2) | 2 of 4 | -10.6 pts |
| Dual momentum (funds) | +11.5% (-15.3) | +35.4% (+5.9) | +58.3% (+46.5) | +72.2% (+10.1) | 3 of 4 | +11.8 pts |
| Insider buying | +8.7% (-18.1) | +12.2% (-17.2) | +15.6% (+3.8) | +61.6% (-0.5) | 1 of 4 | -8.0 pts |
| Congress buying | +25.1% (-1.7) | +25.5% (-3.9) | +25.3% (+13.4) | +47.5% (-14.5) | 1 of 4 | -1.7 pts |
| Blend (dual + momentum + Congress) | +13.8% (-12.9) | +22.1% (-7.3) | +32.5% (+20.7) | +61.0% (-1.1) | 1 of 4 | -0.2 pts |
| 70% Nasdaq 100, 30% dual momentum (2 weeks) | +34.6% (+7.8) | +61.6% (+32.2) | +19.8% (+8.0) | +81.9% (+19.8) | 4 of 4 | +16.9 pts |
| Learned score (top 20) | +27.1% (+0.3) | -3.8% (-33.2) | +10.3% (-1.5) | +12.7% (-49.4) | 1 of 4 | -21.0 pts |
| Earnings drift (8-K news) | +20.9% (-5.9) | +10.9% (-18.5) | +10.7% (-1.1) | +38.8% (-23.3) | 0 of 4 | -12.2 pts |
| Copycat: investors' top 3 (13F) | +32.2% (+5.4) | +56.9% (+27.4) | +9.1% (-2.7) | +80.1% (+18.0) | 3 of 4 | +12.0 pts |
| Screener: example rules | +36.1% (+9.3) | +48.2% (+18.7) | +12.3% (+0.5) | +80.1% (+18.0) | 4 of 4 | +11.6 pts |
| Pelosi: her buys, mirrored | +25.6% (-1.2) | +108.2% (+78.8) | -0.2% (-12.0) | +146.1% (+84.0) | 2 of 4 | +37.4 pts |
| Copycat consensus (C4) | +37.6% (+10.8) | +68.6% (+39.1) | -7.5% (-19.3) | +113.4% (+51.3) | 3 of 4 | +20.5 pts |
| 70% Nasdaq 100 + 30% C4 (K4) | +36.2% (+9.4) | +64.3% (+34.8) | -6.1% (-18.0) | +90.3% (+28.2) | 3 of 4 | +13.6 pts |
| Congress leaders: 5 best past records (L1) | +31.9% (+5.1) | +63.9% (+34.5) | +6.4% (-5.5) | +45.4% (-16.6) | 2 of 4 | +4.4 pts |
| Rule-based list consensus (B1) | +42.7% (+15.9) | +60.1% (+30.7) | -12.4% (-24.2) | +96.6% (+34.6) | 3 of 4 | +14.2 pts |
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
| 70% Nasdaq 100 + 30% C4 (K4) | +15.3% (-2.5) | +11.4% (-0.6) | +0.7% (-0.9) |
| Congress leaders: 5 best past records (L1) | +26.9% (+9.1) | +24.1% (+12.2) | -1.8% (-3.5) |
| Rule-based list consensus (B1) | +3.8% (-14.0) | +11.6% (-0.4) | +3.5% (+1.9) |
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
| Medium term | 5 of 12 | 0 of 12 | 4 of 12 | 3 of 12 | 8 of 12 |
| Dividend (Wealthsimple) | 8 of 12 | 1 of 12 | 5 of 12 | 3 of 12 | 7 of 12 |
| Stock bot | 3 of 12 | 3 of 12 | 6 of 12 | 6 of 12 | 7 of 12 |
| Momentum (top 20 S&P 500) | 3 of 12 | 3 of 12 | 7 of 12 | 8 of 12 | 9 of 12 |
| Dual momentum (funds) | 5 of 12 | 4 of 12 | 7 of 12 | 9 of 12 | 8 of 12 |
| Insider buying | 1 of 12 | 10 of 12 | 8 of 12 | 5 of 12 | 4 of 12 |
| Congress buying | 8 of 12 | 8 of 12 | 6 of 12 | 5 of 12 | 8 of 12 |
| Blend (dual + momentum + Congress) | 3 of 12 | 4 of 12 | 7 of 12 | 8 of 12 | 8 of 12 |
| 70% Nasdaq 100, 30% dual momentum (2 weeks) | 6 of 12 | 9 of 12 | 6 of 12 | 9 of 12 | 7 of 12 |
| Learned score (top 20) | 8 of 12 | 6 of 12 | 7 of 12 | 1 of 12 | 7 of 12 |
| Earnings drift (8-K news) | 3 of 12 | 2 of 12 | 1 of 12 | 2 of 12 | 6 of 12 |
| Copycat: investors' top 3 (13F) | 8 of 12 | 9 of 12 | 4 of 12 | 8 of 12 | 7 of 12 |
| Screener: example rules | 5 of 12 | 8 of 12 | 6 of 12 | 9 of 12 | 7 of 12 |
| Pelosi: her buys, mirrored | 6 of 12 | 11 of 12 | 3 of 12 | 11 of 12 | 3 of 12 |
| Copycat consensus (C4) | 7 of 12 | 11 of 12 | 3 of 12 | 10 of 12 | 3 of 12 |
| 70% Nasdaq 100 + 30% C4 (K4) | 5 of 12 | 11 of 12 | 3 of 12 | 8 of 12 | 5 of 12 |
| Congress leaders: 5 best past records (L1) | 8 of 12 | 11 of 12 | 4 of 12 | 4 of 12 | 7 of 12 |
| Rule-based list consensus (B1) | 9 of 12 | 12 of 12 | 2 of 12 | 10 of 12 | 2 of 12 |
| VIX agent | 3 of 12 | 7 of 12 | 2 of 12 | 5 of 12 | 5 of 12 |

## Hindsight check: everyone copied the same way (24 months windows)

Pelosi and the 23 investors are famous today, partly because they did well: choosing them is hindsight. So every House member with 10+ disclosed buys is copied like Pelosi (each buy kept a year) and every investor's top 3 like the copycat. If most of them beat the S&P 500, the method works; if only the famous one does, it was hindsight.

| period ending | members who beat the S&P 500 | median member | Pelosi's rank | investors who beat it | median investor |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2019-10-18 | 23 of 40 | +1.9 pts | 24 of 40 | 12 of 23 | +3.5 pts |
| 2020-10-16 | 18 of 47 | -4.6 pts | 2 of 47 | 14 of 23 | +18.7 pts |
| 2022-10-14 | 34 of 57 | +3.6 pts | 51 of 57 | 9 of 23 | -5.7 pts |
| 2024-10-18 | 14 of 46 | -2.2 pts | 1 of 46 | 14 of 23 | +7.4 pts |
| 2026-10-16 | 16 of 51 | -4.7 pts | 8 of 51 | 11 of 23 | -5.7 pts |

Do past winners keep winning? The top quarter of members in one period, in the next period that does not overlap it:

| periods | members in both | top quarter next | everyone else next | top quarter beat the S&P 500 |
| --- | ---: | ---: | ---: | ---: |
| 2019-10-18 -> 2022-10-14 | 25 | +11.4 pts | +2.4 pts | 5 of 6 |
| 2020-10-16 -> 2022-10-14 | 33 | -4.0 pts | +10.6 pts | 5 of 8 |
| 2022-10-14 -> 2024-10-18 | 30 | -7.9 pts | +9.2 pts | 2 of 7 |
| 2024-10-18 -> 2026-10-16 | 26 | -3.1 pts | -12.2 pts | 2 of 6 |

## Settings: chosen on the training periods, checked on the held-out last 12 months

Average gap to the S&P 500 and average worst drop. Pick on the training columns only; the test column is the check. Nasdaq 100 average worst drop in training: -22.3%.

| agent | setting | training gap (24 months) | training worst drop | test: last 12 months |
| --- | --- | ---: | ---: | ---: |
| congress buys | Congress: 2+ members, 180 days | +2.3 pts | -16.3% | -2.4 pts |
| congress buys | Congress: any member buying in 90 days | -1.5 pts | -16.3% | +14.6 pts |
| congress buys | Congress: 2+ members buying in 90 days (default) | -1.7 pts | -16.5% | +14.8 pts |
| congress buys | Congress: weighted by size and each member's past record | -7.5 pts | -18.7% | +14.5 pts |
| congress buys | Insiders or Congress, 2+ buyers | -8.2 pts | -22.7% | -3.2 pts |
| congress leaders | L6. Congress leaders: the 3 best, judged on 2 years | +17.2 pts | -22.8% | +1.5 pts |
| congress leaders | L1. Congress leaders: the 5 best past records (default) | +4.4 pts | -24.8% | +9.1 pts |
| congress leaders | L4. Congress leaders: the 5 best with 10+ past trades | +4.4 pts | -24.8% | +9.1 pts |
| congress leaders | L2. Congress leaders: the 10 best past records | -0.9 pts | -18.9% | -2.3 pts |
| congress leaders | L5. Congress leaders: everyone whose past buys beat the S&P 500 by 2+ pts | -4.2 pts | -16.4% | -6.7 pts |
| congress leaders | L3. Congress leaders: the 5 best, judged 6 months after each buy | -7.5 pts | -26.8% | +16.8 pts |
| congress leaders | L0. Congress: every member's buys, no ranking (the baseline the leaders must beat) | -29.6 pts | -7.5% | -16.8 pts |
| copycat | C11. Copycat C7, no stock over 20% (the rest in the S&P 500) | +27.4 pts | -23.1% | -6.0 pts |
| copycat | C12. Copycat C7, no stock over 20% or sector over 40% | +26.5 pts | -23.3% | -6.3 pts |
| copycat | C7. Copycat: consensus, in the top 5 of 3+ investors | +24.5 pts | -23.3% | -6.0 pts |
| copycat | C8. Copycat: consensus, in the top 10 of 4+ investors | +23.8 pts | -23.8% | +5.5 pts |
| copycat | C4. Copycat: consensus, in the top 10 of 3+ investors | +20.5 pts | -23.7% | -2.9 pts |
| copycat | C13. Copycat C7, half in Treasuries while the S&P 500 is under its 200-day | +19.4 pts | -20.2% | -8.9 pts |
| copycat | C14. Copycat C7 with both caps and the crash brake | +19.4 pts | -20.2% | -9.0 pts |
| copycat | C10. Copycat: consensus top 10 of 3+, more money where more investors agree | +17.5 pts | -24.5% | -3.3 pts |
| copycat | B1. Rule-based list: consensus, in the top 10 of 5+ of the 50 managers | +14.2 pts | -19.6% | -14.0 pts |
| copycat | B5. Rule-based list: consensus top 10 of 5+, weighted by agreement | +13.1 pts | -19.9% | -9.4 pts |
| copycat | C3. Copycat: each investor's top 3 ideas (default) | +12.0 pts | -20.4% | +2.4 pts |
| copycat | C9. Copycat: consensus, in the top 10 of 2+ investors | +9.6 pts | -22.6% | -3.7 pts |
| copycat | B4. Rule-based list, 25 largest only: consensus, in the top 10 of 3+ | +8.2 pts | -21.8% | -9.3 pts |
| copycat | B2. Rule-based list: consensus, in the top 10 of 3+ managers | +5.8 pts | -19.9% | -10.3 pts |
| copycat | C5. Copycat: new buys and big adds, top 3 per investor | +2.1 pts | -23.2% | -2.3 pts |
| copycat | C6. Copycat: top 3 ideas, only while above the 200-day | +1.8 pts | -20.9% | +1.9 pts |
| copycat | C2. Copycat: all 23 investors' portfolios, an equal share each | -4.5 pts | -13.9% | -6.3 pts |
| copycat | C1. Copycat: Berkshire's whole portfolio (what the upstream skill does) | -4.9 pts | -20.6% | +4.5 pts |
| copycat | B3. Rule-based list: each manager's top 3 ideas | -5.6 pts | -12.6% | -13.7 pts |
| core + dual | Plan B: rebalanced every 2 weeks (default) | +16.9 pts | -22.4% | -0.6 pts |
| core + dual | Plan, money starts in CAD: Norbert's gambit about 0.1% | +16.4 pts | -22.4% | -0.7 pts |
| core + dual | Core: 70% Nasdaq 100, 30% dual momentum, monthly (previous plan) | +14.9 pts | -22.4% | +9.2 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum, rebalanced monthly | +14.9 pts | -26.9% | +10.2 pts |
| core + dual | Plan, money starts in CAD: bank conversion 1.5% | +14.4 pts | -22.4% | -2.2 pts |
| core + dual | Plan G: 2 slices, one re-chosen every 2 weeks (each monthly) | +12.8 pts | -22.6% | +4.2 pts |
| core + dual | Plan C: satellite half dual momentum, half earnings drift | +11.1 pts | -18.5% | +2.8 pts |
| core + dual | Plan H: satellite half dual momentum, half earnings drift with EPS up | +11.0 pts | -19.4% | +1.8 pts |
| core + dual | Plan F: 4 slices, one re-chosen each week (each monthly) | +10.6 pts | -22.4% | +2.0 pts |
| core + dual | Core: 70/30, Nasdaq 100 only above its 200-day (else bonds) | +9.1 pts | -20.8% | -0.5 pts |
| core + dual | Plan E: switch funds only for a 5-point lead | +9.0 pts | -22.1% | +11.7 pts |
| core + dual | Core: 70/30, dual momentum on 1/3/6/12-month average | +8.4 pts | -22.0% | -8.1 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum (best 2, growth funds) | +8.0 pts | -23.1% | -9.7 pts |
| core + dual | Plan D: satellite = top 20 momentum stocks | +7.7 pts | -22.3% | +11.9 pts |
| core + dual | Plan A: dual momentum on 12-1 months | +5.5 pts | -22.8% | -6.3 pts |
| core + dual | Core: Nasdaq 100 only above its 200-day, else bonds | +5.2 pts | -18.2% | -12.7 pts |
| core + dual | Core: half Nasdaq 100, half dual momentum (volatility target 15%) | +3.2 pts | -17.2% | +0.6 pts |
| core + dual | Core: 70/30, both (trend switch + blended lookbacks) | +2.4 pts | -19.5% | -17.9 pts |
| core + dual | Core: 50/50, both (trend switch + blended lookbacks) | -0.8 pts | -23.3% | -21.8 pts |
| core + upstream | K3. 70% Nasdaq 100 + 30% Pelosi's buys | +21.9 pts | -22.8% | -5.7 pts |
| core + upstream | M4. Half copycat consensus, half screener (no index) | +15.0 pts | -19.2% | +1.0 pts |
| core + upstream | M3. 50% Nasdaq 100 + 25% copycat consensus + 25% screener | +14.7 pts | -20.1% | +1.1 pts |
| core + upstream | K6. 70% Nasdaq 100 + 30% C4, rebalanced every 2 weeks | +14.6 pts | -22.3% | -0.6 pts |
| core + upstream | M1. 70% Nasdaq 100 + 10% each: copycat consensus, screener, Pelosi | +14.5 pts | -21.3% | +0.7 pts |
| core + upstream | K2. 70% Nasdaq 100 + 30% screener picks | +13.6 pts | -19.8% | +6.1 pts |
| core + upstream | K4. 70% Nasdaq 100 + 30% copycat consensus (C4) | +13.6 pts | -22.3% | -2.5 pts |
| core + upstream | K5. 50% Nasdaq 100 + 50% copycat consensus (C4) | +13.3 pts | -23.0% | -4.9 pts |
| core + upstream | M2. 70% Nasdaq 100 + 15% copycat consensus + 15% screener (no Pelosi) | +12.6 pts | -20.9% | +1.0 pts |
| core + upstream | K1. 70% Nasdaq 100 + 30% copycat top-3 ideas | +5.7 pts | -19.5% | -1.4 pts |
| dividend | Default (2% yield floor, 12% cap) | -12.0 pts | -20.2% | +11.3 pts |
| dividend | Higher yield floor: 3.5% | -12.0 pts | -20.2% | +11.3 pts |
| dividend | Rebalance monthly | -12.1 pts | -20.2% | +11.2 pts |
| dividend | Rebalance quarterly | -12.4 pts | -20.0% | +11.2 pts |
| dividend | Today's hand-picked watchlist (hindsight) | -14.1 pts | -18.3% | +5.3 pts |
| dual momentum | Dual momentum: growth funds only | +16.3 pts | -34.0% | +2.2 pts |
| dual momentum | Dual momentum: best 1 fund (default) | +11.8 pts | -36.1% | +17.9 pts |
| dual momentum | Dual momentum: fund above its 200-day only | +6.3 pts | -34.9% | +17.9 pts |
| dual momentum | Dual momentum: best 3 funds | -1.1 pts | -29.2% | +18.8 pts |
| dual momentum | Dual momentum: volatility target 20% | -4.3 pts | -24.3% | +6.0 pts |
| dual momentum | Dual momentum: best 5 funds | -4.5 pts | -25.2% | -6.3 pts |
| dual momentum | Dual momentum: volatility target 15% | -8.5 pts | -18.8% | -0.9 pts |
| dual momentum | Dual momentum: best 2 funds | -13.9 pts | -32.5% | +21.6 pts |
| dual momentum | Dual momentum: best 2, growth funds, volatility target 20% | -14.3 pts | -23.1% | -23.6 pts |
| dual momentum | Dual momentum: 6-month lookback | -29.0 pts | -37.3% | -25.7 pts |
| growth | Today's hand-picked watchlist (hindsight) | +77.2 pts | -28.0% | +7.4 pts |
| growth | 6-month momentum | -16.3 pts | -24.5% | +36.9 pts |
| growth | 6-month momentum, monthly | -16.3 pts | -24.5% | +36.9 pts |
| growth | Default: aggressive (3-month momentum, 30% cap, no cash) | -18.6 pts | -23.7% | +48.1 pts |
| growth | Concentrated: 40% cap, 3+ names | -18.6 pts | -23.7% | +48.1 pts |
| growth | Diversified: 10% cap, 10+ names | -18.6 pts | -23.7% | +48.1 pts |
| growth | Tight stop: 15% | -18.6 pts | -23.7% | +48.1 pts |
| growth | Rebalance monthly | -18.6 pts | -23.7% | +48.1 pts |
| growth | Monthly, 10% cap, 10+ names | -18.6 pts | -23.7% | +48.1 pts |
| growth | Rebalance quarterly | -18.6 pts | -23.7% | +48.1 pts |
| growth | 12-month momentum | -22.5 pts | -26.7% | +13.5 pts |
| growth | Previous default (12-month momentum, 20% cap, 3% cash) | -22.6 pts | -26.1% | +12.5 pts |
| insider buys | Insiders: 3+ buying in 60 days | -0.2 pts | -18.4% | -5.2 pts |
| insider buys | Insiders: 2+, above the 200-day average | -3.2 pts | -16.4% | -4.6 pts |
| insider buys | Insiders: 2+ buying in 60 days (default) | -8.0 pts | -21.8% | -16.6 pts |
| insider buys | Insiders: 1+ officer buying, 90 days | -10.0 pts | -21.3% | -17.9 pts |
| insider buys | Insiders: 2+, top 10 | -16.1 pts | -25.5% | -15.4 pts |
| medium | Today's hand-picked watchlist (hindsight) | +53.3 pts | -17.9% | +1.2 pts |
| medium | Default (6-month trend, 15% cap) | -10.5 pts | -19.8% | +41.2 pts |
| medium | Rebalance monthly | -10.5 pts | -19.8% | +41.2 pts |
| medium | Rebalance quarterly | -10.5 pts | -19.8% | +41.2 pts |
| medium | Monthly, 10% cap, 10+ names | -10.5 pts | -19.8% | +43.1 pts |
| medium | Long trend: 12 months | -13.8 pts | -21.0% | +11.1 pts |
| model | Learned score: 70% Nasdaq 100 + 30% top 20 | +2.5 pts | -23.5% | +3.3 pts |
| model | Learned score: top 40 | -14.3 pts | -29.0% | +14.2 pts |
| model | Learned score: top 20 (default) | -21.0 pts | -35.2% | +1.3 pts |
| model | Learned score: price features only | -21.5 pts | -35.7% | +4.9 pts |
| momentum | Momentum: no trend filter | -7.8 pts | -25.1% | +29.8 pts |
| momentum | Momentum: only names insiders or Congress bought (180 days) | -7.9 pts | -19.0% | +16.5 pts |
| momentum | Momentum: 6-1 months | -8.2 pts | -22.5% | +43.8 pts |
| momentum | Momentum: top 40 | -10.5 pts | -21.3% | +25.7 pts |
| momentum | Momentum: top 20, 12-1 months, above trend (default) | -10.6 pts | -24.2% | +28.5 pts |
| momentum | Momentum: bonds while the S&P 500 is under its 200-day | -11.1 pts | -21.1% | +3.8 pts |
| momentum | Momentum: top 10 | -12.7 pts | -28.7% | +34.6 pts |
| news | News shock: stock bot trades only breakouts with an 8-K that week | +0.4 pts | -20.4% | -8.1 pts |
| news | Earnings drift: held about 30 days | -3.3 pts | -20.9% | -7.1 pts |
| news | Earnings drift: ranked by earnings surprise (EPS vs a year ago) | -6.4 pts | -21.3% | -15.0 pts |
| news | Earnings drift: only if EPS beat the same quarter a year ago | -10.9 pts | -22.8% | -1.9 pts |
| news | Earnings drift: top 20 jumps of 3+ pts, held about 60 days (default) | -12.2 pts | -22.6% | +8.4 pts |
| news | Earnings drift: jumps of 5+ pts | -12.4 pts | -23.1% | +8.2 pts |
| pelosi | P3. Pelosi: only trades of $1M or more, mirrored | +67.2 pts | -29.1% | -33.7 pts |
| pelosi | P2. Pelosi: every buy kept a year, her sales ignored | +48.1 pts | -26.7% | -10.1 pts |
| pelosi | P1. Pelosi: what she bought in the last year, sold when she sells (default) | +37.4 pts | -26.7% | -16.3 pts |
| screener | S4. Screener: looser rules (growth 5%+, margin 15%+, P/E up to 50), top 20 | +13.1 pts | -17.2% | +6.2 pts |
| screener | S1. Screener: its own example rules, top 10 (default) | +11.6 pts | -18.6% | +13.8 pts |
| screener | S2. Screener: the example rules, top 20 | +9.6 pts | -19.9% | +7.2 pts |
| screener | S3. Screener: the example rules, then the 20 with the best 12-1 momentum | +8.1 pts | -19.2% | +0.3 pts |
| stock bot | Stock bot: today's 30 hand-picked large caps (hindsight) | +4.3 pts | -21.8% | +14.5 pts |
| stock bot | Stock bot: trades + idle cash in QQQ (default) | -10.7 pts | -20.8% | +1.7 pts |
| stock bot | Stock bot: idle in QQQ, hold 5 days | -12.1 pts | -20.6% | -9.9 pts |
| stock bot | Stock bot: trades + idle cash in SPY | -17.1 pts | -19.7% | +1.4 pts |
| stock bot | Stock bot: trades only, idle cash stays cash | -29.3 pts | -18.7% | -7.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 3-month VIX | +3.1 pts | -21.1% | -9.0 pts |
| vix | VIX agent: S&P 500 unless VIX > 3-month VIX (stress) | -3.3 pts | -14.1% | -9.2 pts |
| vix | VIX agent: Nasdaq 100 unless VIX > 30 (default) | -3.6 pts | -22.1% | -0.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 25 | -8.3 pts | -11.9% | -3.7 pts |
| vix | VIX agent: S&P 500 unless VIX > 30 | -10.5 pts | -16.2% | -2.5 pts |
| vix | VIX agent: S&P 500 while VIX is under its 50-day average | -15.4 pts | -12.2% | -8.5 pts |
| vix | VIX agent: S&P 500 unless VIX > 20 | -20.5 pts | -11.8% | -16.2 pts |

## Coverage and self-checks

- 2019-10-18: 405 of 506 index members priced; self-checks all passed
- 2020-10-16: 413 of 505 index members priced; self-checks all passed
- 2022-10-14: 441 of 505 index members priced; self-checks all passed
- 2024-10-18: 465 of 503 index members priced; self-checks all passed
- 2026-10-16: 480 of 503 index members priced; self-checks all passed

_Point in time; survivorship bias remains for companies Yahoo has no prices for. Not financial advice._
