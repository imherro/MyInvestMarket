# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-07T20:14:00+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0091 | -0.0154 | 0.0063 |
| cagr | -0.1388 | -0.2230 | 0.0843 |
| sharpe_ratio | -3.1587 | -3.9215 | 0.7628 |
| max_drawdown | 0.0124 | 0.0184 | -0.0060 |
| calmar_ratio | -11.1527 | -12.1250 | 0.9724 |
| turnover | 1.9372 | 3.3594 | -1.4222 |
| win_rate | 0.5333 | 0.5333 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 2.0000 | -0.0020 | 0.5000 |
| distribution | 6.0000 | 0.0010 | 0.8333 |
| expansion | 6.0000 | -0.0015 | 0.3333 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0011 |
| strong_trend | 2.0000 | -0.0059 | -0.0053 |
| unknown | 1.0000 | -0.0020 | -0.0014 |
| weakening_trend | 5.0000 | 0.0003 | 0.0009 |

## Risk Engine Effect

- High risk sample count: 14
- Actual max drawdown: 0.0124
- Baseline max drawdown: 0.0184
- Drawdown reduction: 0.3237

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
