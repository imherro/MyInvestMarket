# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-01T10:04:44+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0011 | -0.0031 | 0.0020 |
| cagr | -0.0385 | -0.1031 | 0.0646 |
| sharpe_ratio | -0.6171 | -1.4795 | 0.8624 |
| max_drawdown | 0.0085 | 0.0111 | -0.0025 |
| calmar_ratio | -4.5054 | -9.2947 | 4.7893 |
| turnover | 1.0278 | 1.3807 | -0.3529 |
| win_rate | 0.5714 | 0.5714 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 1.0000 | -0.0045 | 0.0000 |
| distribution | 2.0000 | 0.0011 | 1.0000 |
| expansion | 1.0000 | 0.0018 | 1.0000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 2.0000 | -0.0019 | -0.0017 |
| unknown | 3.0000 | -0.0002 | -0.0000 |
| weakening_trend | 2.0000 | 0.0016 | 0.0018 |

## Risk Engine Effect

- High risk sample count: 6
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
