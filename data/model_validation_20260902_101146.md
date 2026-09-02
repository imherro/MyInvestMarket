# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-02T10:11:46+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0162 | -0.0219 | 0.0057 |
| cagr | -0.0698 | -0.0935 | 0.0237 |
| sharpe_ratio | -1.5769 | -1.8691 | 0.2921 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -1.9783 | -2.2570 | 0.2788 |
| turnover | 7.9248 | 11.3521 | -3.4273 |
| win_rate | 0.5818 | 0.5818 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 10.0000 | 0.0005 | 0.8000 |
| distribution | 16.0000 | 0.0001 | 0.7500 |
| expansion | 28.0000 | -0.0007 | 0.4286 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 13.0000 | 0.0005 | 0.0008 |
| strong_trend | 6.0000 | -0.0026 | -0.0023 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 35.0000 | -0.0001 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 54
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
