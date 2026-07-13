# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-13T10:04:08+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0108 | -0.0173 | 0.0065 |
| cagr | -0.1369 | -0.2108 | 0.0740 |
| sharpe_ratio | -3.2209 | -3.8997 | 0.6788 |
| max_drawdown | 0.0141 | 0.0203 | -0.0062 |
| calmar_ratio | -9.7109 | -10.3807 | 0.6698 |
| turnover | 2.2436 | 3.6933 | -1.4497 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 4.0000 | -0.0005 | 0.5000 |
| distribution | 6.0000 | 0.0010 | 0.8333 |
| expansion | 7.0000 | -0.0018 | 0.2857 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0011 |
| strong_trend | 2.0000 | -0.0059 | -0.0053 |
| unknown | 1.0000 | -0.0020 | -0.0014 |
| weakening_trend | 8.0000 | -0.0000 | 0.0006 |

## Risk Engine Effect

- High risk sample count: 17
- Actual max drawdown: 0.0141
- Baseline max drawdown: 0.0203
- Drawdown reduction: 0.3060

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
