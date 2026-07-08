# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-08T20:12:17+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0096 | -0.0159 | 0.0063 |
| cagr | -0.1371 | -0.2165 | 0.0794 |
| sharpe_ratio | -3.2290 | -3.9237 | 0.6947 |
| max_drawdown | 0.0129 | 0.0189 | -0.0060 |
| calmar_ratio | -10.6105 | -11.4730 | 0.8625 |
| turnover | 1.9941 | 3.4163 | -1.4222 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 3.0000 | -0.0015 | 0.3333 |
| distribution | 6.0000 | 0.0010 | 0.8333 |
| expansion | 6.0000 | -0.0015 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0011 |
| strong_trend | 2.0000 | -0.0059 | -0.0053 |
| unknown | 1.0000 | -0.0020 | -0.0014 |
| weakening_trend | 6.0000 | 0.0002 | 0.0008 |

## Risk Engine Effect

- High risk sample count: 15
- Actual max drawdown: 0.0129
- Baseline max drawdown: 0.0189
- Drawdown reduction: 0.3153

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
