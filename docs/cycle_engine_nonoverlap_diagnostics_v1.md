# Cycle Engine v1 Phase 4.1

This layer measures whether the descriptive relationships from the overlapping
diagnostics remain visible after using fixed non-overlapping cohorts. It is
research-only and never produces a score, ranking, selection, state, weight,
threshold, position, signal, or strategy backtest.

## Cohorts

For each 6, 12, and 24 month horizon, every natural calendar month is assigned
to all fixed offsets using:

`calendar_month_index = year * 12 + month`

`cohort = calendar_month_index % horizon`

Missing months do not renumber later cohorts. All cohorts are emitted, even
when a cohort has too few observations for a correlation result.

## Outputs

Continuous candidates contain sample counts and Spearman rho for forward return
and maximum drawdown. Boolean candidates contain true/false sample counts,
medians, and true-minus-false medians for both outcomes. Each feature and
horizon also contains cohort stability summaries and a descriptive comparison
with the overlapping Phase 3 result.

Run:

`python scripts/cycle_engine_nonoverlap_diagnostics.py --generate`

The output is `data/cycle_engine_nonoverlap_diagnostics_v1.json`; its audit is
`data/cycle_engine_nonoverlap_diagnostics_audit_v1.json`.
