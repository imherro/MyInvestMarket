# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-10T13:03:50+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0073 | -0.0136 | 0.0063 |
| cagr | -0.1001 | -0.1782 | 0.0782 |
| sharpe_ratio | -2.3060 | -3.1853 | 0.8793 |
| max_drawdown | 0.0129 | 0.0189 | -0.0060 |
| calmar_ratio | -7.7442 | -9.4445 | 1.7003 |
| turnover | 2.0342 | 3.4564 | -1.4222 |
| win_rate | 0.5294 | 0.5294 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 4.0000 | -0.0005 | 0.5000 |
| distribution | 6.0000 | 0.0010 | 0.8333 |
| expansion | 6.0000 | -0.0015 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0009 |
| strong_trend | 2.0000 | -0.0059 | -0.0055 |
| unknown | 1.0000 | -0.0020 | -0.0016 |
| weakening_trend | 7.0000 | 0.0005 | 0.0009 |

## Risk Engine Effect

- High risk sample count: 16
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
