# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-22T18:11:43+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0209 | -0.0274 | 0.0065 |
| cagr | -0.1799 | -0.2297 | 0.0498 |
| sharpe_ratio | -4.2104 | -4.5545 | 0.3441 |
| max_drawdown | 0.0288 | 0.0350 | -0.0062 |
| calmar_ratio | -6.2534 | -6.5713 | 0.3179 |
| turnover | 3.2580 | 4.7834 | -1.5254 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 6.0000 | 0.0004 | 0.6667 |
| distribution | 8.0000 | 0.0003 | 0.7500 |
| expansion | 11.0000 | -0.0022 | 0.2727 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0013 |
| strong_trend | 2.0000 | -0.0059 | -0.0051 |
| unknown | 1.0000 | -0.0020 | -0.0012 |
| weakening_trend | 16.0000 | -0.0006 | 0.0002 |

## Risk Engine Effect

- High risk sample count: 25
- Actual max drawdown: 0.0288
- Baseline max drawdown: 0.0350
- Drawdown reduction: 0.1771

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
