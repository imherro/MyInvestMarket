# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-06-30T14:28:24+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0029 | -0.0050 | 0.0021 |
| cagr | -0.1107 | -0.1847 | 0.0740 |
| sharpe_ratio | -1.7707 | -2.6233 | 0.8527 |
| max_drawdown | 0.0085 | 0.0111 | -0.0025 |
| calmar_ratio | -12.9606 | -16.6575 | 3.6968 |
| turnover | 0.8087 | 1.1335 | -0.3248 |
| win_rate | 0.5000 | 0.5000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 1.0000 | -0.0045 | 0.0000 |
| distribution | 2.0000 | 0.0011 | 1.0000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 2.0000 | -0.0019 | -0.0014 |
| unknown | 3.0000 | -0.0002 | 0.0003 |
| weakening_trend | 1.0000 | 0.0015 | 0.0020 |

## Risk Engine Effect

- High risk sample count: 5
- Actual max drawdown: 0.0085
- Baseline max drawdown: 0.0111
- Drawdown reduction: 0.2294

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 0.95}, "risk_curve": {"risk_discount_shift": -0.05}, "regime_multiplier": {"shift": -0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
