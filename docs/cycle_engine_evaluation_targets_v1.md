# Cycle Engine v1 Ex-post Evaluation Targets

This layer evaluates historical outcomes after each monthly observation. It is
strictly downstream of the Cycle Engine Evidence Vector and is not a model
input.

## Boundary

- `evaluation_only=true`
- `uses_future_information=true`
- `future_information_required=true`
- It does not calculate a score, regime, label, threshold, weight, position, or trading signal.
- It must not be imported by `scripts/cycle_engine_features.py`.
- No `forward_*`, `months_to_*`, `broad_proxy_index`, or other target field may enter `ENGINE_FEATURE_POLICY`.

## Benchmark and proxy

The evaluation universe is CSI300 and CSI500. Each month uses the frozen
month-end `close.value`. The broad proxy starts at 100 and compounds:

`0.5 * CSI300 monthly return + 0.5 * CSI500 monthly return`.

It does not average index levels.

## Targets

For 3, 6, 12, and 24 natural months, each benchmark records the forward return,
worst and best path return, target month, availability, and months to worst/best.
For 6, 12, and 24 months it also records peak-to-trough maximum drawdown over
the full future path beginning at the observation month.

Incomplete tails are `target_available=false` with null numeric values. The
horizon is the calendar month `M+h`, never the h-th remaining record.

## Audit and regeneration

Run:

```text
python scripts/cycle_engine_evaluation_targets.py --generate
```

The generator writes `data/cycle_engine_evaluation_targets_v1.json` and its
audit. The audit replays formulas, natural-month alignment, tail semantics,
source availability, broad proxy compounding, maximum drawdown, Evidence
independence, and frozen-record identity.
