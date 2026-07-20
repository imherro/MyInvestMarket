# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-20T18:16:48+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0245 | -0.0310 | 0.0065 |
| cagr | -0.2232 | -0.2742 | 0.0510 |
| sharpe_ratio | -5.4017 | -5.5710 | 0.1693 |
| max_drawdown | 0.0288 | 0.0350 | -0.0062 |
| calmar_ratio | -7.7589 | -7.8436 | 0.0848 |
| turnover | 3.0029 | 4.5283 | -1.5254 |
| win_rate | 0.4583 | 0.4583 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 5.0000 | -0.0002 | 0.6000 |
| distribution | 8.0000 | 0.0003 | 0.7500 |
| expansion | 10.0000 | -0.0024 | 0.2000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0015 |
| strong_trend | 2.0000 | -0.0059 | -0.0049 |
| unknown | 1.0000 | -0.0020 | -0.0010 |
| weakening_trend | 14.0000 | -0.0010 | 0.0000 |

## Risk Engine Effect

- High risk sample count: 23
- Actual max drawdown: 0.0288
- Baseline max drawdown: 0.0350
- Drawdown reduction: 0.1771

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
