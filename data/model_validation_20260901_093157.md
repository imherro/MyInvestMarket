# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-01T09:31:57+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0153 | -0.0210 | 0.0057 |
| cagr | -0.0673 | -0.0913 | 0.0240 |
| sharpe_ratio | -1.5042 | -1.8066 | 0.3023 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -1.9081 | -2.2054 | 0.2973 |
| turnover | 7.7768 | 11.1798 | -3.4030 |
| win_rate | 0.5926 | 0.5926 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 10.0000 | 0.0005 | 0.8000 |
| distribution | 16.0000 | 0.0001 | 0.7500 |
| expansion | 27.0000 | -0.0007 | 0.4444 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 12.0000 | 0.0006 | 0.0009 |
| strong_trend | 6.0000 | -0.0026 | -0.0023 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 35.0000 | -0.0001 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 53
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
