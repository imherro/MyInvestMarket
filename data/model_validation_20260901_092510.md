# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-01T09:25:10+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0094 | -0.0145 | 0.0051 |
| cagr | -0.0511 | -0.0777 | 0.0266 |
| sharpe_ratio | -1.1103 | -1.4713 | 0.3611 |
| max_drawdown | 0.0324 | 0.0386 | -0.0062 |
| calmar_ratio | -1.5762 | -2.0149 | 0.4388 |
| turnover | 5.9466 | 8.4904 | -2.5438 |
| win_rate | 0.5455 | 0.5455 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 8.0000 | 0.0003 | 0.6250 |
| distribution | 11.0000 | 0.0005 | 0.8182 |
| expansion | 24.0000 | -0.0006 | 0.4167 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 11.0000 | 0.0008 | 0.0010 |
| strong_trend | 4.0000 | -0.0025 | -0.0023 |
| unknown | 1.0000 | -0.0020 | -0.0018 |
| weakening_trend | 28.0000 | -0.0002 | -0.0000 |

## Risk Engine Effect

- High risk sample count: 43
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
