# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-01T20:12:30+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | 0.0004 | -0.0006 | 0.0010 |
| cagr | 0.0128 | -0.0182 | 0.0310 |
| sharpe_ratio | 0.2464 | -0.2382 | 0.4846 |
| max_drawdown | 0.0085 | 0.0111 | -0.0025 |
| calmar_ratio | 1.4933 | -1.6449 | 3.1383 |
| turnover | 1.0278 | 1.5742 | -0.5464 |
| win_rate | 0.6250 | 0.6250 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 1.0000 | -0.0045 | 0.0000 |
| distribution | 2.0000 | 0.0011 | 1.0000 |
| expansion | 2.0000 | 0.0017 | 1.0000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 3.0000 | -0.0007 | -0.0008 |
| unknown | 3.0000 | -0.0002 | -0.0003 |
| weakening_trend | 2.0000 | 0.0016 | 0.0016 |

## Risk Engine Effect

- High risk sample count: 7
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
