# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-21T18:13:26+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0212 | -0.0277 | 0.0065 |
| cagr | -0.1884 | -0.2396 | 0.0512 |
| sharpe_ratio | -4.3543 | -4.6970 | 0.3427 |
| max_drawdown | 0.0288 | 0.0350 | -0.0062 |
| calmar_ratio | -6.5495 | -6.8547 | 0.3052 |
| turnover | 3.0775 | 4.6029 | -1.5254 |
| win_rate | 0.4800 | 0.4800 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 6.0000 | 0.0004 | 0.6667 |
| distribution | 8.0000 | 0.0003 | 0.7500 |
| expansion | 10.0000 | -0.0024 | 0.2000 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 7.0000 | 0.0005 | 0.0013 |
| strong_trend | 2.0000 | -0.0059 | -0.0051 |
| unknown | 1.0000 | -0.0020 | -0.0012 |
| weakening_trend | 15.0000 | -0.0007 | 0.0001 |

## Risk Engine Effect

- High risk sample count: 24
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
