# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-08-07T09:24:45+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0197 | -0.0254 | 0.0057 |
| cagr | -0.1260 | -0.1598 | 0.0338 |
| sharpe_ratio | -2.8847 | -3.1703 | 0.2856 |
| max_drawdown | 0.0324 | 0.0386 | -0.0062 |
| calmar_ratio | -3.8898 | -4.1444 | 0.2546 |
| turnover | 4.8712 | 6.5488 | -1.6776 |
| win_rate | 0.5278 | 0.5278 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 7.0000 | 0.0005 | 0.7143 |
| distribution | 10.0000 | 0.0003 | 0.8000 |
| expansion | 18.0000 | -0.0014 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 8.0000 | 0.0007 | 0.0013 |
| strong_trend | 2.0000 | -0.0059 | -0.0054 |
| unknown | 1.0000 | -0.0020 | -0.0015 |
| weakening_trend | 25.0000 | -0.0005 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 35
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
