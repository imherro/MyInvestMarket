"""Build the contract-bound Cycle Engine v1 evidence vector.

This module is deliberately an adapter only. It produces traceable inputs and
PIT-safe transforms; it does not calculate a cycle score, regime, or position.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import validate_cycle_dataset_contract as freeze


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATASET_PATH = DATA / "cycle_dataset_v1.json"
CONTRACT_PATH = DATA / "cycle_dataset_contract_v1.json"
MANIFEST_PATH = DATA / "cycle_dataset_freeze_manifest_v1.json"
MATRIX_PATH = DATA / "cycle_dataset_feature_availability_v1.json"
GOLDEN_PATH = DATA / "cycle_dataset_golden_spots_v1.json"
FEATURES_PATH = DATA / "cycle_engine_features_v1.json"
AUDIT_PATH = DATA / "cycle_engine_features_audit_v1.json"
MIN_NORMALIZATION_HISTORY = 36
FROZEN_RECORDS_SHA256 = "82d5e6046aa7607d1b9646cd46de02eb512def1bd93a22881b0cc4d02c2c95d0"
FROZEN_CONTRACT_SHA256 = "062604d15805b01105f5fdf6aa1ecf8bd3024d0a730a341d635eee9331bd60ff"
FROZEN_MATRIX_SHA256 = "86103098b57d2f084ebec3c565231a785875769841a205eb4685ce1e562b7dca"
FROZEN_GOLDEN_SHA256 = "99a108058d224b1634f03f1c07a17796ecaf88eb2e266d097e2520983ab79419"


def feature_family(path: str) -> str:
    if path.startswith("valuation.indices."):
        return "valuation_level"
    if path == "valuation.csi300_erp_pct.value":
        return "relative_valuation"
    if path.startswith("valuation."):
        return "valuation_lineage"
    if "net_profit" in path:
        return "earnings_growth"
    if "roe_ttm" in path:
        return "earnings_quality"
    if path.startswith("earnings.pmi."):
        return "macro_confirmation"
    if path.startswith("trend.indices."):
        field = path.rsplit(".", 2)[-2]
        if field in ("ma250_deviation_pct", "above_ma250"):
            return "trend_level"
        if field == "ma250_slope_3m_pct":
            return "trend_direction"
        if field in ("return_6m_pct", "return_12m_pct"):
            return "trend_momentum"
        return "trend_damage"
    if path == "sentiment.a_fear.fear_score":
        return "sentiment_overlay"
    return "unclassified"


def model_candidate(path: str) -> bool:
    if path.startswith("valuation.indices."):
        return path.endswith("percentile_expanding")
    return path not in ("valuation.csi300_earnings_yield_pct.value", "valuation.china_10y_government_bond_yield_pct.value")


def build_engine_feature_policy(registry: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["path"]: {"feature_family": feature_family(item["path"]), "model_candidate": model_candidate(item["path"])} for item in registry}


class FrozenDatasetInvalid(RuntimeError):
    """Raised when the frozen input gate does not pass."""


def load_source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8-sig"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    expected_paths = {item["path"] for item in freeze.build_registry()}
    actual_paths = {item.get("path") for item in contract.get("model_input_registry", [])}
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        raise FrozenDatasetInvalid(f"model input registry mismatch: missing={missing}; extra={extra}")
    if set(build_engine_feature_policy(contract.get("model_input_registry", []))) != actual_paths:
        raise FrozenDatasetInvalid("engine feature policy does not cover the frozen registry exactly")
    result = freeze.validate(payload, contract, matrix, manifest, golden)
    if not result["valid"]:
        raise FrozenDatasetInvalid("frozen dataset validation failed: " + "; ".join(result["errors"]))
    if manifest.get("frozen_records_sha256") != FROZEN_RECORDS_SHA256 or manifest.get("contract_sha256") != FROZEN_CONTRACT_SHA256:
        raise FrozenDatasetInvalid("Final Freeze v1.1 manifest baseline mismatch")
    if freeze.sha256(contract) != FROZEN_CONTRACT_SHA256 or freeze.sha256(matrix) != FROZEN_MATRIX_SHA256 or freeze.sha256(golden) != FROZEN_GOLDEN_SHA256:
        raise FrozenDatasetInvalid("Final Freeze v1.1 frozen layer hash mismatch")
    return payload, contract, matrix, manifest, golden


def resolve(record: dict[str, Any], path: str) -> Any:
    return freeze.resolve(record, path)


def source_row(record: dict[str, Any], path: str) -> dict[str, Any]:
    row_path = path.rsplit(".", 1)[0]
    value = resolve(record, row_path)
    return value if isinstance(value, dict) else {}


def pit_date(record: dict[str, Any], item: dict[str, Any]) -> str | None:
    path = item["path"]
    row = source_row(record, path)
    field = item["pit_date_field"]
    value = row.get(field)
    if value is None and field == "basis_trade_date":
        value = record.get("basis_trade_date")
    return value


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def rank_pct(history: list[float], current: float) -> float:
    lower = sum(value < current for value in history)
    equal = sum(value == current for value in history)
    return round((lower + 0.5 * equal) / len(history) * 100, 6)


def is_native_percentile(path: str) -> bool:
    return path.endswith("percentile_expanding")


def is_native_fear(path: str) -> bool:
    return path == "sentiment.a_fear.fear_score"


def expected_missing(path: str, month: str, policy: list[dict[str, Any]]) -> bool:
    return freeze.is_expected_missing(path, month, policy)


def missing_reason(record: dict[str, Any], item: dict[str, Any], expected: bool) -> str | None:
    row = source_row(record, item["path"])
    if expected:
        return next((rule["reason"] for rule in []), "accepted expected missing by contract policy")
    return row.get("reason") or row.get("source_error") or "unexpected missing input"


def build_features(records: list[dict[str, Any]], contract: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    registry = contract["model_input_registry"]
    policy = contract["expected_missing_policy"]
    history: dict[str, list[float]] = defaultdict(list)
    available_counts: dict[str, int] = defaultdict(int)
    output: list[dict[str, Any]] = []
    policy_map = build_engine_feature_policy(registry)
    for record in records:
        month = record["month"]
        basis = record["basis_trade_date"]
        features: dict[str, Any] = {}
        domain: dict[str, dict[str, Any]] = defaultdict(lambda: {"candidate_feature_count": 0, "available_candidate_count": 0, "unavailable_paths": []})
        for item in registry:
            path = item["path"]
            policy_item = policy_map[path]
            family = policy_item["feature_family"]
            candidate = policy_item["model_candidate"]
            raw = resolve(record, path)
            available = raw is not None
            pit = pit_date(record, item)
            pit_safe = bool(available and pit and parse_date(pit) <= parse_date(basis))
            expected = not available and expected_missing(path, month, policy)
            feature: dict[str, Any] = {
                "path": path,
                "raw_value": raw,
                "available": available,
                "domain": item["domain"],
                "role": item["role"],
                "unit": item["unit"],
                "direction_hint": item["direction_hint"],
                "feature_family": family,
                "model_candidate": candidate,
                "pit_date": pit,
                "pit_safe": pit_safe,
                "expected_missing": expected,
                "missing_reason": None if available else missing_reason(record, item, expected),
                "normalization_source": None,
                "expanding_rank_pct": None,
                "normalization_history_observations": None if not candidate else available_counts[path],
                "normalization_history_ready": False,
            }
            if item["role"] == "core" or candidate:
                domain_name = family if family in ("earnings_growth", "earnings_quality", "macro_confirmation") else ("long_term_trend" if family.startswith("trend_") else ("sentiment_overlay" if family == "sentiment_overlay" else "valuation"))
                if candidate:
                    domain[domain_name]["candidate_feature_count"] += 1
                    if available:
                        domain[domain_name]["available_candidate_count"] += 1
                    else:
                        domain[domain_name]["unavailable_paths"].append(path)
            if not candidate:
                feature["normalization_source"] = "not_model_candidate"
            elif available:
                available_counts[path] += 1
                feature["normalization_history_observations"] = available_counts[path]
                feature["normalization_history_ready"] = available_counts[path] >= MIN_NORMALIZATION_HISTORY
                if item["unit"] == "boolean":
                    feature["normalization_source"] = "boolean_identity"
                elif is_native_percentile(path):
                    feature["expanding_rank_pct"] = raw
                    feature["normalization_source"] = "dataset_native_percentile"
                elif is_native_fear(path):
                    feature["expanding_rank_pct"] = raw
                    feature["normalization_source"] = "native_a_fear_score"
                elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    values = history[path] + [float(raw)]
                    feature["expanding_rank_pct"] = rank_pct(values, float(raw))
                    feature["normalization_source"] = "pit_expanding_rank_pct"
                    feature["normalization_history_observations"] = len(values)
                    history[path].append(float(raw))
                else:
                    feature["normalization_source"] = "unsupported_value_type"
            elif candidate:
                feature["normalization_history_ready"] = available_counts[path] >= MIN_NORMALIZATION_HISTORY
            features[path] = feature
        for value in domain.values():
            count = value["candidate_feature_count"]
            value["coverage_pct"] = round(value["available_candidate_count"] / count * 100, 2) if count else 0.0
        output.append({"month": month, "basis_trade_date": basis, "contract_version": contract["contract_version"], "dataset_frozen_hash": manifest["frozen_records_sha256"], "features": features, "domain_availability": dict(domain)})
    return output


def build_audit(rows: list[dict[str, Any]], records: list[dict[str, Any]], contract: dict[str, Any], manifest: dict[str, Any], matrix: dict[str, Any] | None = None, golden: dict[str, Any] | None = None) -> dict[str, Any]:
    registry_paths = {item["path"] for item in contract["model_input_registry"]}
    policy_map = build_engine_feature_policy(contract["model_input_registry"])
    unauthorized: list[str] = []
    future_pit = 0
    missing_registry = 0
    type_violations = 0
    family_missing = 0
    candidate_missing = 0
    unexpected = 0
    normalization_future_leakage = 0
    normalization_transform_errors = 0
    normalization_history_errors = 0
    normalization_readiness_errors = 0
    frozen_layer_mutations = 0
    rank_history: dict[str, list[float]] = defaultdict(list)
    observation_counts: dict[str, int] = defaultdict(int)
    for row, record in zip(rows, records):
        for path, feature in row["features"].items():
            if path not in registry_paths:
                unauthorized.append(path)
            policy_item = policy_map.get(path)
            candidate = bool(policy_item and policy_item["model_candidate"])
            if feature.get("available") and not feature.get("pit_safe"):
                future_pit += 1
            if not feature.get("feature_family"):
                family_missing += 1
            if not isinstance(feature.get("model_candidate"), bool):
                candidate_missing += 1
            raw = feature.get("raw_value")
            unit = feature.get("unit")
            if raw is not None and (not isinstance(raw, (bool, int, float)) or (unit == "boolean" and not isinstance(raw, bool)) or (unit != "boolean" and (isinstance(raw, bool) or not isinstance(raw, (int, float))))):
                type_violations += 1
            if not feature.get("available") and not feature.get("expected_missing"):
                unexpected += 1
            if candidate:
                expected_raw = resolve(record, path)
                expected_available = expected_raw is not None
                observation_counts[path] += int(expected_available)
                if feature.get("normalization_history_observations") != observation_counts[path]:
                    normalization_history_errors += 1
                if feature.get("normalization_history_ready") != (observation_counts[path] >= MIN_NORMALIZATION_HISTORY):
                    normalization_readiness_errors += 1
                if not expected_available:
                    if feature.get("expanding_rank_pct") is not None:
                        normalization_transform_errors += 1
                elif item := next((item for item in contract["model_input_registry"] if item["path"] == path), None):
                    source = feature.get("normalization_source")
                    if item["unit"] == "boolean":
                        if feature.get("expanding_rank_pct") is not None or source != "boolean_identity":
                            normalization_transform_errors += 1
                    elif is_native_percentile(path):
                        if feature.get("expanding_rank_pct") != expected_raw or source != "dataset_native_percentile":
                            normalization_transform_errors += 1
                    elif is_native_fear(path):
                        if feature.get("expanding_rank_pct") != expected_raw or source != "native_a_fear_score":
                            normalization_transform_errors += 1
                    elif isinstance(expected_raw, (int, float)) and not isinstance(expected_raw, bool):
                        values = rank_history[path] + [float(expected_raw)]
                        expected_rank = rank_pct(values, float(expected_raw))
                        if feature.get("expanding_rank_pct") != expected_rank or source != "pit_expanding_rank_pct":
                            normalization_future_leakage += 1
                        rank_history[path].append(float(expected_raw))
                    else:
                        normalization_transform_errors += 1
            elif path in registry_paths:
                if feature.get("expanding_rank_pct") is not None or feature.get("normalization_history_observations") is not None or feature.get("normalization_history_ready") is not False or feature.get("normalization_source") != "not_model_candidate":
                    normalization_transform_errors += 1
        missing_registry += sum(path not in row["features"] for path in registry_paths)
    matrix = matrix if matrix is not None else json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    golden = golden if golden is not None else json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    frozen_hashes = {
        "records": freeze.sha256(freeze.records_for_hash({"records": records}, freeze.FROZEN_THROUGH)),
        "contract": freeze.sha256(contract),
        "matrix": freeze.sha256(matrix),
        "golden": freeze.sha256(golden),
    }
    if frozen_hashes != {"records": FROZEN_RECORDS_SHA256, "contract": FROZEN_CONTRACT_SHA256, "matrix": FROZEN_MATRIX_SHA256, "golden": FROZEN_GOLDEN_SHA256} or manifest.get("frozen_records_sha256") != FROZEN_RECORDS_SHA256 or manifest.get("contract_sha256") != FROZEN_CONTRACT_SHA256:
        frozen_layer_mutations += 1
    audit = {"record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "source_contract_version": contract["contract_version"], "source_contract_sha256": frozen_hashes["contract"], "source_frozen_records_sha256": frozen_hashes["records"], "unauthorized_input_count": len(set(unauthorized)), "unauthorized_inputs": sorted(set(unauthorized)), "future_pit_date_count": future_pit, "missing_registry_path_count": missing_registry, "feature_type_violation_count": type_violations, "normalization_future_leakage_count": normalization_future_leakage, "normalization_transform_violation_count": normalization_transform_errors, "normalization_history_violation_count": normalization_history_errors, "normalization_readiness_violation_count": normalization_readiness_errors, "feature_family_missing_count": family_missing, "candidate_flag_missing_count": candidate_missing, "unexpected_input_missing_count": unexpected, "frozen_layer_mutation_count": frozen_layer_mutations, "passed": False}
    audit["passed"] = all(value == 0 for key, value in audit.items() if key.endswith("_count") and key != "record_count")
    return audit


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    payload, contract, _matrix, manifest, _golden = load_source()
    records = freeze.records_for_hash(payload, freeze.FROZEN_THROUGH)
    rows = build_features(records, contract, manifest)
    audit = build_audit(rows, records, contract, manifest)
    if not audit["passed"]:
        raise FrozenDatasetInvalid("evidence audit failed: " + json.dumps(audit, ensure_ascii=False))
    result = {"feature_version": "cycle_engine_features_v1", "contract_version": contract["contract_version"], "dataset_version": contract["dataset"]["dataset_version"], "source_frozen_records_sha256": manifest["frozen_records_sha256"], "record_count": len(rows), "start_month": rows[0]["month"], "end_month": rows[-1]["month"], "records": rows}
    return result, audit


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    result, audit = generate()
    if args.generate:
        write_json(FEATURES_PATH, result)
        write_json(AUDIT_PATH, audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
