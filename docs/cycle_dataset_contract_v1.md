# Cycle Dataset v1 Contract

Cycle Dataset v1 is the frozen, point-in-time research input layer for the future Cycle Engine. It is not a trading signal, position recommendation, or bull/bear forecast.

## Scope

The core domains are valuation, earnings, macro confirmation through Manufacturing PMI, and long-term index trend. A-FEAR is a separate modern-history fear overlay and is not a substitute for the core history.

Every observation is monthly. `basis_trade_date` is the last open SSE trading day in the natural month. A field is usable only when its source observation or announcement/publication date is visible at that basis. Missing values remain `null`; the contract forbids neutral, mean, current-value, or proxy imputation.

## Frozen Artifacts

- `data/cycle_dataset_v1.json`: 2010-01 through 2026-08 PIT records.
- `data/cycle_dataset_contract_v1.json`: machine-readable registry, missing rules, and exclusions.
- `data/cycle_dataset_feature_availability_v1.json`: field-level availability and expected/unexpected missing counts.
- `data/cycle_dataset_golden_spots_v1.json`: compact regression fixtures for key historical months.
- `data/cycle_dataset_freeze_manifest_v1.json`: deterministic hashes and freeze gate results.

The frozen record hash covers only records through the frozen month, with records sorted by month and object keys sorted in canonical UTF-8 JSON. Generated timestamps, refresh metadata, and Git timestamps are excluded from the record hash. Future months may be appended without changing the frozen hash.

## Input Roles

Valuation describes relative expensiveness and ERP describes equity-versus-bond attractiveness. Earnings and ROE describe profitability and quality. PMI confirms the direction of manufacturing activity. Long-term trend describes whether the index is above or below its long-term path, including slope, returns, and drawdown. These fields describe economic direction only; they are not weights or scores.

The future Cycle Engine may use only the paths listed in the model input registry. Short-term momentum, breadth, flows, crowding, the legacy v3.4 score, legacy state/risk/trend outputs, and four-sleeve allocation are explicitly excluded.

## Accepted Limitations

CSI1000 valuation is currently unavailable from the configured valuation source and must not be proxied. A-FEAR begins in modern history and its pre-history is expected missing. PMI release-date PIT is available, but a complete real-time revision-vintage database is not. Financial source revisions cannot be fully reconstructed when upstream vintages are absent. Index backfilled histories may be used for warm-up only after each index's official launch date; pre-launch Trend is unavailable.

## Validation

Run:

```text
python scripts/validate_cycle_dataset_contract.py
```

Generation is explicit:

```text
python scripts/validate_cycle_dataset_contract.py --generate
```

The validator checks required records and structure, PIT and lineage audit results, official launch visibility, expected versus unexpected missing inputs, registry exclusions, and both frozen/current record hashes. `structural_freeze_passed` may be true while `freshness_at_freeze` is false; the latter records the real remote-cache freshness state and must not be cosmetically changed.
