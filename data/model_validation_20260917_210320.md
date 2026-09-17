# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-17T21:03:20+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0240 | -0.0296 | 0.0057 |
| cagr | -0.0846 | -0.1038 | 0.0192 |
| sharpe_ratio | -2.0766 | -2.2635 | 0.1869 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -2.3985 | -2.5060 | 0.1074 |
| turnover | 9.5718 | 13.0234 | -3.4516 |
| win_rate | 0.5522 | 0.5522 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 16.0000 | 0.0001 | 0.6250 |
| distribution | 17.0000 | 0.0000 | 0.7059 |
| expansion | 33.0000 | -0.0008 | 0.4545 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 14.0000 | 0.0002 | 0.0005 |
| strong_trend | 6.0000 | -0.0026 | -0.0022 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 46.0000 | -0.0002 | 0.0002 |

## Risk Engine Effect

- High risk sample count: 64
- Actual max drawdown: 0.0353
- Baseline max drawdown: 0.0414
- Drawdown reduction: 0.1484

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
