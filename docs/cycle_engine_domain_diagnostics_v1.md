# Cycle Engine v1 Domain Historical Diagnostics

This is a research-only diagnostic layer over the frozen Phase 2 Domain
Signals. It describes historical readiness, state distributions, transitions,
cross-domain combinations, conflicts, timelines, and ex-post forward-return
observations. It does not change any Phase 2 rule.

## Boundary

The diagnostic input is the byte-frozen
`data/cycle_engine_domain_signals_v1.json`, protected by
`FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256`, plus its passing audit and the existing
evaluation-only targets. Future information is used only in the explicitly
labelled `evaluation` subsection. Natural-month cohorts are separated by
`month_index % horizon`; origins inside each cohort are at least one horizon
apart.

The evaluation is descriptive. Full cohort details remain under `evaluation`.
The `phase3_design_evidence.state_forward_return_summary` is an aggregate-only
contract: each state is summarized at `aggregation_unit="cohort"`, with
`effective_sample_count` defined as the median of non-empty cohort sample
counts. `insufficient_sample_flags` stores an object per state with
`small_sample` and either `reason="effective_sample_count_lt_12"` or `null`.
A-FEAR is not treated as a predictive efficacy claim because its history is
immature.

## Outputs

- `coverage`: readiness and availability timelines
- `state_distribution`: counts and consecutive run statistics
- `transitions`: state transition matrices and change rates
- `combinations`: cross-domain combinations, top and rare cases
- `conflicts`: fixed explanatory conflict flags and months
- `timeline` and `window_extracts`: complete historical review timeline
- `evaluation`: CSI300/CSI500 non-overlap ex-post summaries for 6/12/24 months
- `phase3_design_evidence`: factual evidence for later review, with no rule
  recommendation; its forward-return summary, cohort sample-size contract,
  and insufficient-sample flags are independently replayed by the audit

Generate with:

```text
python scripts/cycle_engine_domain_diagnostics.py --generate
```

The audit has its own snapshot, cohort-evaluation, Phase 3 evidence, run-length
and conflict-duration replays. This layer never emits a score, global cycle
state, regime, position, allocation, signal, or ETF recommendation.
