# Cycle Engine v1 Domain Signals

Phase 2 reduces the frozen Phase 1 Evidence Vector into five explainable,
point-in-time-safe sections: valuation, earnings, PMI confirmation, long-term
trend, and the independent A-FEAR overlay.

The production input is limited to:

- `data/cycle_engine_features_v1.json`
- `data/cycle_engine_features_audit_v1.json`

Evaluation targets, feature diagnostics, walk-forward diagnostics,
non-overlap diagnostics, legacy market outputs, and v3.4 are not inputs.

## Reduction Rules

Valuation has three formal votes: CSI300 percentile, CSI500 percentile, and
CSI300 ERP percentile. Raw PE/PB, earnings yield, and China 10Y yield are
lineage or explanation fields only. CSI1000 valuation remains unavailable and
is never proxied.

Earnings is split into growth and quality. PMI is confirmation only. The
earnings state uses the strict natural-month `t-3` comparison and requires
Phase 1 history readiness.

The six trend fields for each index are reduced to one index state before
CSI300/CSI500/CSI1000 states are reduced to one broad trend state. CSI1000 is
omitted until its own six fields are ready.

Every formal domain state observes the Phase 1 `normalization_history_ready`
gate. Early months therefore report `insufficient_history` rather than a
synthetic neutral state. Trend `dispersion` counts only participating indices;
unavailable or immature indices are excluded.

A-FEAR is always `overlay_only`; it never participates in a core vote. Its
bands are `[0,20) calm`, `[20,40) normal`, `[40,60) watch`, `[60,80) high_fear`,
and `[80,100] extreme_fear`.

## Audit

`data/cycle_engine_domain_signals_audit_v1.json` rebuilds the reduction output,
checks the Phase 1 source gate and canonical hash, validates
readiness and natural-month alignment, rejects non-candidate or future-data
use, and ensures all forbidden global score/regime/allocation outputs remain
absent. Production generation accepts only the frozen Phase 1 Evidence
canonical SHA256. Phase 2 does not emit a Cycle Score, global regime, position,
allocation, or trading signal.

Generate with:

```text
python scripts/cycle_engine_domain_signals.py --generate
```
