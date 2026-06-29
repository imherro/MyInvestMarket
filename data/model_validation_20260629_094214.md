# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-06-29T09:42:14+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0044 | -0.0065 | 0.0021 |
| cagr | -0.1933 | -0.2731 | 0.0798 |
| sharpe_ratio | -2.9972 | -3.7808 | 0.7836 |
| max_drawdown | 0.0085 | 0.0111 | -0.0025 |
| calmar_ratio | -22.6200 | -24.6300 | 2.0101 |
| turnover | 0.7401 | 1.0649 | -0.3248 |
| win_rate | 0.4000 | 0.4000 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 1.0000 | -0.0045 | 0.0000 |
| distribution | 1.0000 | 0.0007 | 1.0000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 2.0000 | -0.0019 | -0.0010 |
| unknown | 3.0000 | -0.0002 | 0.0007 |

## Risk Engine Effect

- High risk sample count: 4
- Actual max drawdown: 0.0085
- Baseline max drawdown: 0.0111
- Drawdown reduction: 0.2294

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 0.95}, "risk_curve": {"risk_discount_shift": -0.05}, "regime_multiplier": {"shift": -0.04}, "trend_multiplier": {"shift": -0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
