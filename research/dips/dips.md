# Buying the dip: do beaten-down stocks catch up?

Every S&P 500 member on its member days since 2014, checked every 5 trading days; entry at the next open; the gap to the S&P 500 bought the same morning. 626 stocks with prices, 158 without (survivorship).

## training 2014-2022

| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |
| --- | ---: | ---: | ---: | ---: | ---: |
| every member-day (baseline) | 185515 | +0.05 pts | +0.04 pts | -0.18 pts | 49% |
| D1 20%+ below its 52-week high, still above its 200-day average | 1274 | +2.08 pts | +4.62 pts | +4.71 pts | 63% |
| D2 down 10%+ in a month, still above its 200-day average | 992 | +0.21 pts | +0.59 pts | -0.11 pts | 49% |
| D3 30%+ below its 52-week high and below its 200-day average | 4855 | +0.74 pts | +1.25 pts | +0.58 pts | 52% |
| D4 40%+ below its 52-week high | 2315 | +1.49 pts | +2.99 pts | +1.83 pts | 54% |

## held out 2023 on

| signal | events | next month vs S&P 500 | next 3 months | median 3 months | beat it |
| --- | ---: | ---: | ---: | ---: | ---: |
| every member-day (baseline) | 86656 | -0.61 pts | -1.89 pts | -2.76 pts | 42% |
| D1 20%+ below its 52-week high, still above its 200-day average | 977 | -0.23 pts | -1.74 pts | -4.44 pts | 39% |
| D2 down 10%+ in a month, still above its 200-day average | 702 | -0.56 pts | -0.22 pts | -2.95 pts | 42% |
| D3 30%+ below its 52-week high and below its 200-day average | 2504 | -0.53 pts | -1.78 pts | -3.05 pts | 43% |
| D4 40%+ below its 52-week high | 1067 | -0.08 pts | -0.83 pts | -2.37 pts | 45% |

**Rule v16 verdicts:** D1 info, D2 info, D3 info, D4 info (buy: flagged stocks beat the S&P 500 by 2+ points over 3 months in training, beat the baseline, and beat it in the held-out years too; info: no edge shown).

## The S&P 500 itself (SPY since 1993): buying on a dip vs any day

| bought when | next 3 months | next 12 months |
| --- | ---: | ---: |
| any day | +2.4% (n=8436) | +10.2% (n=8247) |
| 5%+ below its high | +2.4% (n=4247) | +9.3% (n=4233) |
| 10%+ below its high | +1.9% (n=3188) | +8.8% (n=3188) |
| 20%+ below its high | +2.3% (n=1848) | +9.6% (n=1848) |

_Not financial advice._
