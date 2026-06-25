# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-06-25T11:33:18+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0006 | -0.0027 | 0.0021 |
| cagr | -0.0485 | -0.2002 | 0.1517 |
| sharpe_ratio | -0.5268 | -1.9884 | 1.4616 |
| max_drawdown | 0.0048 | 0.0073 | -0.0026 |
| calmar_ratio | -10.1473 | -27.2994 | 17.1521 |
| turnover | 0.5896 | 0.7274 | -0.1378 |
| win_rate | 0.3333 | 0.3333 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| unknown | 3.0000 | -0.0002 | 0.0000 |

## Risk Engine Effect

- High risk sample count: 2
- Actual max drawdown: 0.0048
- Baseline max drawdown: 0.0073
- Drawdown reduction: 0.3482

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 0.95}, "risk_curve": {"risk_discount_shift": -0.05}, "regime_multiplier": {"shift": -0.04}, "trend_multiplier": {"shift": -0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
