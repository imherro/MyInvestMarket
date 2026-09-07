# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-07T21:02:57+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0207 | -0.0264 | 0.0057 |
| cagr | -0.0830 | -0.1048 | 0.0218 |
| sharpe_ratio | -1.9286 | -2.1612 | 0.2326 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -2.3533 | -2.5304 | 0.1772 |
| turnover | 8.4355 | 11.8871 | -3.4516 |
| win_rate | 0.5763 | 0.5763 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 12.0000 | 0.0004 | 0.7500 |
| distribution | 16.0000 | 0.0001 | 0.7500 |
| expansion | 30.0000 | -0.0008 | 0.4333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 14.0000 | 0.0002 | 0.0005 |
| strong_trend | 6.0000 | -0.0026 | -0.0022 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 38.0000 | -0.0001 | 0.0002 |

## Risk Engine Effect

- High risk sample count: 58
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
