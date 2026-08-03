# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-08-03T09:54:24+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0269 | -0.0334 | 0.0065 |
| cagr | -0.1877 | -0.2280 | 0.0403 |
| sharpe_ratio | -4.7090 | -4.8863 | 0.1773 |
| max_drawdown | 0.0312 | 0.0374 | -0.0062 |
| calmar_ratio | -6.0168 | -6.1019 | 0.0851 |
| turnover | 4.4356 | 5.9610 | -1.5254 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 7.0000 | 0.0005 | 0.7143 |
| distribution | 10.0000 | 0.0003 | 0.8000 |
| expansion | 14.0000 | -0.0023 | 0.2143 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0013 |
| strong_trend | 2.0000 | -0.0059 | -0.0051 |
| unknown | 1.0000 | -0.0020 | -0.0012 |
| weakening_trend | 22.0000 | -0.0007 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 31
- Actual max drawdown: 0.0312
- Baseline max drawdown: 0.0374
- Drawdown reduction: 0.1653

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
