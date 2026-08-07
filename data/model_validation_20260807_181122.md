# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-08-07T18:11:22+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0170 | -0.0227 | 0.0057 |
| cagr | -0.1067 | -0.1404 | 0.0336 |
| sharpe_ratio | -2.4068 | -2.7518 | 0.3450 |
| max_drawdown | 0.0324 | 0.0386 | -0.0062 |
| calmar_ratio | -3.2948 | -3.6402 | 0.3453 |
| turnover | 5.0500 | 6.8798 | -1.8298 |
| win_rate | 0.5405 | 0.5405 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 7.0000 | 0.0005 | 0.7143 |
| distribution | 11.0000 | 0.0005 | 0.8182 |
| expansion | 18.0000 | -0.0014 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 9.0000 | 0.0009 | 0.0014 |
| strong_trend | 2.0000 | -0.0059 | -0.0055 |
| unknown | 1.0000 | -0.0020 | -0.0016 |
| weakening_trend | 25.0000 | -0.0005 | -0.0000 |

## Risk Engine Effect

- High risk sample count: 36
- Actual max drawdown: 0.0324
- Baseline max drawdown: 0.0386
- Drawdown reduction: 0.1599

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
