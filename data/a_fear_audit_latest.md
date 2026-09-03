# A-FEAR v1 Audit

- Generated at: 2026-09-03T21:02:48+08:00
- Passed: True
- Source observations: 761
- Complete IO/MO observations: 715
- Official scores: 466
- Latest: 2026-09-03 / 64.9285 / high
- Score range: 10.9538 .. 99.0023

## Checks

| Check | Passed | Detail |
|---|---:|---|
| source_history_depth | True | 761 source observations; target 750. |
| official_history_depth | True | 466 official daily scores after the minimum-sample warm-up. |
| latest_is_official | True | Latest 2026-09-03 score=64.9285 confidence=high. |
| score_bounds | True | Observed range 10.9538..99.0023. |
| component_independence | True | Highest absolute pairwise component Spearman correlation=0.6615. |
| jump_frequency | True | Absolute one-day changes above 30: 14/466 (3.0%). |
| latest_broad_panic_consistency | True | Latest score is below the extreme-panic threshold; breadth/tail confirmation is not required. |

## Largest One-Day Changes

| Date | Previous | Current | Absolute change |
|---|---:|---:|---:|
| 2025-04-07 | 47.9524 | 99.0023 | 51.0499 |
| 2024-10-09 | 47.7758 | 91.0875 | 43.3117 |
| 2026-03-10 | 68.9744 | 31.5121 | 37.4623 |
| 2026-03-24 | 96.3819 | 59.1975 | 37.1844 |
| 2026-02-03 | 84.265 | 50.1056 | 34.1594 |
| 2026-03-19 | 46.9378 | 80.5506 | 33.6128 |
| 2026-07-27 | 87.8748 | 55.2758 | 32.599 |
| 2026-07-28 | 55.2758 | 87.8712 | 32.5954 |
| 2026-07-31 | 91.8694 | 59.5231 | 32.3463 |
| 2025-02-28 | 40.2356 | 71.4431 | 31.2075 |
| 2024-09-02 | 16.8375 | 47.8867 | 31.0492 |
| 2026-03-26 | 53.0334 | 83.4316 | 30.3982 |
| 2025-02-19 | 56.2015 | 25.8401 | 30.3614 |
| 2026-03-09 | 38.6798 | 68.9744 | 30.2946 |

## Limitations

- This is an implementation and behavior audit, not evidence that A-FEAR predicts future returns.
- The first official score appears only after the 250-observation warm-up and sufficient option-IV history.
- Large daily changes are retained because the indicator is intended to react to panic shocks; they require live monitoring.
- A-FEAR v1 remains observational and does not modify the official position recommendation.
