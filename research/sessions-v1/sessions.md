# Overseas sessions -> New York / Toronto day trade (paper)

Read Tokyo and Hong Kong (closed) and London and Frankfurt (half way) at 9:15 a.m. New York time, using only hourly bars that had closed; buy at the open, sell at the close, 0.05% slippage each way, never short. Training 2023-10-20 to 2025-10-20; held-out test 2025-10-20 to 2026-10-20.

| version | training return | trades | win rate | worst drop | held-out year |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hold SPY | +15.0% | 249 | 57% | -19.0% | +14.5% |
| Day-trade SPY every day | -15.5% | 249 | 45% | -19.8% | -21.7% |
| D1. Asia closed up: day-trade SPY | -17.8% | 140 | 44% | -18.5% | -16.7% |
| D2. Europe up so far: day-trade SPY | -19.2% | 134 | 42% | -19.9% | -10.5% |
| D3. All four up on average (0.25%+): day-trade SPY | -18.2% | 105 | 37% | -19.5% | -12.4% |
| D4. Buy the dip: all four down 0.5%+ on average, day-trade SPY | +8.5% | 42 | 52% | -5.8% | -2.0% |
| Hold QQQ | +23.4% | 249 | 57% | -22.9% | +17.5% |
| Day-trade QQQ every day | -15.4% | 249 | 49% | -20.9% | -21.5% |
| D5. All four up on average (0.25%+): day-trade the Nasdaq 100 (QQQ) | -20.5% | 105 | 42% | -22.4% | -14.0% |
| Hold XIU.TO | +20.8% | 241 | 57% | -13.0% | +19.7% |
| Day-trade XIU.TO every day | -10.2% | 250 | 48% | -11.3% | -13.8% |
| D6. All four up on average (0.25%+): day-trade the TSX 60 (XIU.TO) | -14.0% | 105 | 49% | -15.3% | -9.1% |

**Rule (written before the data):** no version beat both holding its fund and day-trading it every day in training, so the overseas read did not add value here.

_Paper only. Frequent trading in a TFSA risks being taxed as business income. Not financial advice._
