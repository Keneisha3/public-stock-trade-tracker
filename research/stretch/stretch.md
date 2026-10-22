# Sell signals: do stretched stocks fall behind?

Every S&P 500 member on its member days since 2014, checked every 5 trading days; entry at the next open; the gap to the S&P 500 bought the same morning. 626 stocks with prices, 158 without (survivorship).

## training 2014-2022

| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |
| --- | ---: | ---: | ---: | ---: | ---: |
| every member-day (baseline) | 185515 | +0.05 pts | +0.04 pts | -0.18 pts | 49% |
| X1 50%+ above its 200-day average | 262 | -0.98 pts | +0.14 pts | -2.31 pts | 47% |
| X2 up 25%+ in a month with volatility 1.5x its usual | 245 | +1.85 pts | +1.40 pts | -0.02 pts | 50% |
| X3 30%+ above its 200-day, volatility 1.5x its usual, and rising | 90 | -0.59 pts | -0.33 pts | -0.34 pts | 48% |
| X4 up 60%+ in 3 months | 229 | -1.04 pts | -0.22 pts | +1.25 pts | 52% |

## held out 2023 on

| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |
| --- | ---: | ---: | ---: | ---: | ---: |
| every member-day (baseline) | 85779 | -0.61 pts | -1.91 pts | -2.77 pts | 42% |
| X1 50%+ above its 200-day average | 246 | +3.66 pts | +9.48 pts | -0.15 pts | 50% |
| X2 up 25%+ in a month with volatility 1.5x its usual | 102 | +0.43 pts | +2.69 pts | -2.94 pts | 44% |
| X3 30%+ above its 200-day, volatility 1.5x its usual, and rising | 128 | -0.89 pts | -1.10 pts | -4.29 pts | 37% |
| X4 up 60%+ in 3 months | 204 | +2.10 pts | +9.78 pts | +0.36 pts | 52% |

**Rule v15 verdicts:** X1 info, X2 info, X3 info, X4 info (trim: flagged stocks trailed by 2+ points in training and the held-out years agree; info: shown as risk only, never as a sell).

_Not financial advice._
