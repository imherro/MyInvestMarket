# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-08-10T18:12:06+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0147 | -0.0189 | 0.0042 |
| cagr | -0.0904 | -0.1150 | 0.0246 |
| sharpe_ratio | -2.0210 | -2.1989 | 0.1780 |
| max_drawdown | 0.0324 | 0.0386 | -0.0062 |
| calmar_ratio | -2.7913 | -2.9832 | 0.1918 |
| turnover | 5.1288 | 7.1891 | -2.0603 |
| win_rate | 0.5526 | 0.5526 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 7.0000 | 0.0005 | 0.7143 |
| distribution | 11.0000 | 0.0005 | 0.8182 |
| expansion | 19.0000 | -0.0012 | 0.3684 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 9.0000 | 0.0009 | 0.0013 |
| strong_trend | 3.0000 | -0.0032 | -0.0028 |
| unknown | 1.0000 | -0.0020 | -0.0016 |
| weakening_trend | 25.0000 | -0.0005 | -0.0001 |

## Risk Engine Effect

- High risk sample count: 37
- Actual max drawdown: 0.0324
- Baseline max drawdown: 0.0386
- Drawdown reduction: 0.1599

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": 0.05}, "regime_multiplier": {"shift": 0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
