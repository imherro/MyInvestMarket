# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-14T21:03:26+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0214 | -0.0271 | 0.0057 |
| cagr | -0.0793 | -0.0995 | 0.0202 |
| sharpe_ratio | -1.9053 | -2.1222 | 0.2169 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -2.2492 | -2.4031 | 0.1539 |
| turnover | 8.9519 | 12.4035 | -3.4516 |
| win_rate | 0.5625 | 0.5625 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 15.0000 | 0.0001 | 0.6000 |
| distribution | 16.0000 | 0.0001 | 0.7500 |
| expansion | 32.0000 | -0.0007 | 0.4688 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 14.0000 | 0.0002 | 0.0005 |
| strong_trend | 6.0000 | -0.0026 | -0.0022 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 43.0000 | -0.0001 | 0.0002 |

## Risk Engine Effect

- High risk sample count: 63
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
