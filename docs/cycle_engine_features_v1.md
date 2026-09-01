# Cycle Engine v1 Evidence Vector

Phase 1 is a contract-bound adapter from `cycle_dataset_v1` to a traceable monthly Evidence Vector. It is an input layer only: it does not calculate a cycle score, regime, state, weight, position, or backtest result.

## Gate

`scripts/cycle_engine_features.py` validates the frozen dataset, contract, availability matrix, manifest, and golden spots before reading any record. Any frozen hash mismatch, structural/PIT failure, unexpected missing input, registry drift, or golden drift stops generation.

## Output

- `data/cycle_engine_features_v1.json`: 200 monthly evidence records from `2010-01` through `2026-08`.
- `data/cycle_engine_features_audit_v1.json`: whitelist, PIT, type, normalization, family, and missing-input audit.

Every feature retains its registry path, raw value, availability, domain, role, unit, direction hint, feature family, model-candidate flag, PIT date, PIT safety, expected-missing flag, missing reason, normalization source, expanding rank, and history length/readiness.

## Normalization

Numeric candidate fields use only values available through the current month. The deterministic rank is `(count(lower) + 0.5 * count(equal)) / count(history) * 100`, including the current value. Native valuation percentiles and A-FEAR are copied as identity transforms; booleans are not ranked. Fewer than 36 observations is marked not ready but is never nulled.

## Boundaries

The registry is the only input allowlist. Legacy v3.4 scores, regime/risk/trend outputs, flows, themes, short-term momentum, crowding, and allocation are excluded. Phase 1 deliberately emits no score or investment conclusion.
