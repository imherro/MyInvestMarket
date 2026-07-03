# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-03T11:27:44+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0075 | -0.0137 | 0.0063 |
| cagr | -0.1416 | -0.2451 | 0.1035 |
| sharpe_ratio | -2.8963 | -3.9048 | 1.0085 |
| max_drawdown | 0.0108 | 0.0167 | -0.0060 |
| calmar_ratio | -13.1267 | -14.6432 | 1.5165 |
| turnover | 1.3298 | 2.5175 | -1.1877 |
| win_rate | 0.5833 | 0.5833 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 2.0000 | -0.0020 | 0.5000 |
| distribution | 4.0000 | 0.0019 | 1.0000 |
| expansion | 5.0000 | -0.0018 | 0.4000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0011 |
| strong_trend | 2.0000 | -0.0059 | -0.0053 |
| unknown | 1.0000 | -0.0020 | -0.0014 |
| weakening_trend | 2.0000 | 0.0016 | 0.0023 |

## Risk Engine Effect

- High risk sample count: 11
- Actual max drawdown: 0.0108
- Baseline max drawdown: 0.0167
- Drawdown reduction: 0.3557

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
