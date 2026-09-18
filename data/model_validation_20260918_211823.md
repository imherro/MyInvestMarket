# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-09-18T21:18:23+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0212 | -0.0268 | 0.0057 |
| cagr | -0.0739 | -0.0930 | 0.0191 |
| sharpe_ratio | -1.7944 | -2.0114 | 0.2170 |
| max_drawdown | 0.0353 | 0.0414 | -0.0061 |
| calmar_ratio | -2.0944 | -2.2456 | 0.1512 |
| turnover | 9.7592 | 13.2108 | -3.4516 |
| win_rate | 0.5588 | 0.5588 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 16.0000 | 0.0001 | 0.6250 |
| distribution | 17.0000 | 0.0000 | 0.7059 |
| expansion | 34.0000 | -0.0007 | 0.4706 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 14.0000 | 0.0002 | 0.0005 |
| strong_trend | 6.0000 | -0.0026 | -0.0023 |
| unknown | 1.0000 | -0.0020 | -0.0017 |
| weakening_trend | 47.0000 | -0.0001 | 0.0002 |

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
