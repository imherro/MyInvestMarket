# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-07T09:27:49+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0072 | -0.0134 | 0.0063 |
| cagr | -0.1178 | -0.2100 | 0.0922 |
| sharpe_ratio | -2.5714 | -3.5336 | 0.9622 |
| max_drawdown | 0.0108 | 0.0167 | -0.0060 |
| calmar_ratio | -10.9257 | -12.5452 | 1.6195 |
| turnover | 1.7446 | 3.1506 | -1.4060 |
| win_rate | 0.5714 | 0.5714 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 2.0000 | -0.0020 | 0.5000 |
| distribution | 5.0000 | 0.0016 | 1.0000 |
| expansion | 6.0000 | -0.0015 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0010 |
| strong_trend | 2.0000 | -0.0059 | -0.0054 |
| unknown | 1.0000 | -0.0020 | -0.0015 |
| weakening_trend | 4.0000 | 0.0009 | 0.0014 |

## Risk Engine Effect

- High risk sample count: 13
- Actual max drawdown: 0.0108
- Baseline max drawdown: 0.0167
- Drawdown reduction: 0.3557

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
