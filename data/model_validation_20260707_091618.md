# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-07T09:16:18+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0070 | -0.0133 | 0.0063 |
| cagr | -0.1243 | -0.2223 | 0.0980 |
| sharpe_ratio | -2.6176 | -3.6266 | 1.0090 |
| max_drawdown | 0.0108 | 0.0167 | -0.0060 |
| calmar_ratio | -11.5238 | -13.2779 | 1.7541 |
| turnover | 1.5372 | 2.9270 | -1.3898 |
| win_rate | 0.6154 | 0.6154 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 2.0000 | -0.0020 | 0.5000 |
| distribution | 5.0000 | 0.0016 | 1.0000 |
| expansion | 5.0000 | -0.0018 | 0.4000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0010 |
| strong_trend | 2.0000 | -0.0059 | -0.0054 |
| unknown | 1.0000 | -0.0020 | -0.0015 |
| weakening_trend | 3.0000 | 0.0012 | 0.0018 |

## Risk Engine Effect

- High risk sample count: 12
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
