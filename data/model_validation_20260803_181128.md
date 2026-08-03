# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-08-03T18:11:28+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0292 | -0.0356 | 0.0065 |
| cagr | -0.1966 | -0.2353 | 0.0387 |
| sharpe_ratio | -5.0175 | -5.1362 | 0.1187 |
| max_drawdown | 0.0324 | 0.0386 | -0.0062 |
| calmar_ratio | -6.0669 | -6.1005 | 0.0336 |
| turnover | 4.6815 | 6.2069 | -1.5254 |
| win_rate | 0.4848 | 0.4848 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 7.0000 | 0.0005 | 0.7143 |
| distribution | 10.0000 | 0.0003 | 0.8000 |
| expansion | 15.0000 | -0.0023 | 0.2000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0013 |
| strong_trend | 2.0000 | -0.0059 | -0.0051 |
| unknown | 1.0000 | -0.0020 | -0.0011 |
| weakening_trend | 23.0000 | -0.0008 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 32
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
