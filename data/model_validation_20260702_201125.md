# MyInvestMarket Phase 6 Backtesting & Model Validation

- Generated at: 2026-07-02T20:11:25+08:00
- Available: True
- Signal delay bars: 1
- Lookahead safe: True

## v3 vs v2 Proxy

| Metric | v3 | v2 proxy | Delta |
|---|---:|---:|---:|
| total_return | -0.0067 | -0.0118 | 0.0051 |
| cagr | -0.1666 | -0.2754 | 0.1089 |
| sharpe_ratio | -2.7607 | -3.6814 | 0.9207 |
| max_drawdown | 0.0108 | 0.0164 | -0.0055 |
| calmar_ratio | -15.3644 | -16.8336 | 1.4693 |
| turnover | 1.0278 | 1.5937 | -0.5659 |
| win_rate | 0.5556 | 0.5556 | 0.0000 |

## Regime Contribution

| Regime | Count | Avg Return | Hit Rate |
|---|---:|---:|---:|
| contraction | 1.0000 | -0.0045 | 0.0000 |
| distribution | 2.0000 | 0.0011 | 1.0000 |
| expansion | 3.0000 | -0.0013 | 0.6667 |
| 结构性偏强但分歧较大 | 1.0000 | -0.0020 | 0.0000 |
| 防守或弱修复 | 2.0000 | 0.0007 | 0.5000 |

## Trend Contribution

| Trend | Count | Avg Return | Alpha vs Avg |
|---|---:|---:|---:|
| early_trend | 3.0000 | -0.0007 | -0.0000 |
| strong_trend | 1.0000 | -0.0071 | -0.0064 |
| unknown | 3.0000 | -0.0002 | 0.0005 |
| weakening_trend | 2.0000 | 0.0016 | 0.0024 |

## Risk Engine Effect

- High risk sample count: 8
- Actual max drawdown: 0.0108
- Baseline max drawdown: 0.0164
- Drawdown reduction: 0.3374

## Calibration Sensitivity

- Available: True
- Tested count: 81
- Best params: `{"weights": {"opportunity_score_scale": 1.05}, "risk_curve": {"risk_discount_shift": -0.05}, "regime_multiplier": {"shift": -0.04}, "trend_multiplier": {"shift": 0.04}}`

## Limitations

- Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.
- All positions are shifted by one bar to avoid lookahead bias.
- The current repository has a short real score history; statistical claims require more post-close records.
