# Cycle Engine v1 Evidence Vector

Phase 1 is a contract-bound adapter from `cycle_dataset_v1` to a traceable monthly Evidence Vector. It is an input layer only: it does not calculate a cycle score, regime, state, weight, position, or backtest result.

## Gate

`scripts/cycle_engine_features.py` validates the frozen dataset, contract, availability matrix, manifest, and golden spots before reading any record. Any frozen hash mismatch, structural/PIT failure, unexpected missing input, registry drift, or golden drift stops generation.

## Output

- `data/cycle_engine_features_v1.json`: 200 monthly evidence records from `2010-01` through `2026-08`.
- `data/cycle_engine_features_audit_v1.json`: whitelist, PIT, type, normalization, family, missing-input, and frozen-layer audit. It independently replays history observations/readiness and separates continuous rank leakage from identity-transform violations.

Every feature retains its registry path, raw value, availability, domain, role, unit, direction hint, feature family, model-candidate flag, PIT date, PIT safety, expected-missing flag, missing reason, normalization source, expanding rank, and history length/readiness.

## Normalization

Numeric candidate fields use only values available through the current month. The deterministic rank is `(count(lower) + 0.5 * count(equal)) / count(history) * 100`, including the current value. Native valuation percentiles and A-FEAR are copied as identity transforms; booleans are not ranked. Every candidate keeps a cumulative available-observation count, including across missing months; readiness is `observations >= 36`. Fewer than 36 observations is marked not ready but is never nulled. Non-candidates always have null rank/history and `normalization_source=not_model_candidate`.

## Boundaries

The registry is the only input allowlist and remains a pure frozen Dataset contract. Feature family and model-candidate status live in `ENGINE_FEATURE_POLICY` inside the Engine. The Engine hard-checks the contract, records, availability matrix, golden spots, and Final Freeze v1.1 manifest hashes before generation. Legacy v3.4 scores, regime/risk/trend outputs, flows, themes, short-term momentum, crowding, and allocation are excluded. Phase 1 deliberately emits no score or investment conclusion.
