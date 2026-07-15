# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-15T09:29:49+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0149 | -0.0214 | 0.0065 |
| cagr | -0.1675 | -0.2320 | 0.0645 |
| sharpe_ratio | -3.9163 | -4.4005 | 0.4842 |
| max_drawdown | 0.0193 | 0.0255 | -0.0062 |
| calmar_ratio | -8.6574 | -9.0869 | 0.4295 |
| turnover | 2.5074 | 3.9846 | -1.4772 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 4.0000 | -0.0005 | 0.5000 |
| distribution | 7.0000 | 0.0010 | 0.8571 |
| expansion | 8.0000 | -0.0023 | 0.2500 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0012 |
| strong_trend | 2.0000 | -0.0059 | -0.0052 |
| unknown | 1.0000 | -0.0020 | -0.0013 |
| weakening_trend | 10.0000 | -0.0004 | 0.0003 |

## Risk Engine Effect

- High risk sample count: 19
- Actual max drawdown: 0.0193
- Baseline max drawdown: 0.0255
- Drawdown reduction: 0.2422

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
