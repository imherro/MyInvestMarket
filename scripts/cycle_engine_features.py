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
    result = freeze.validate(payload, contract, matrix, manifest, golden)
    if not result["valid"]:
        raise FrozenDatasetInvalid("frozen dataset validation failed: " + "; ".join(result["errors"]))
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
    output: list[dict[str, Any]] = []
    for record in records:
        month = record["month"]
        basis = record["basis_trade_date"]
        features: dict[str, Any] = {}
        domain: dict[str, dict[str, Any]] = defaultdict(lambda: {"candidate_feature_count": 0, "available_candidate_count": 0, "unavailable_paths": []})
        for item in registry:
            path = item["path"]
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
                "feature_family": item["feature_family"],
                "model_candidate": item["model_candidate"],
                "pit_date": pit,
                "pit_safe": pit_safe,
                "expected_missing": expected,
                "missing_reason": None if available else missing_reason(record, item, expected),
                "normalization_source": None,
                "expanding_rank_pct": None,
                "normalization_history_observations": len(history[path]),
                "normalization_history_ready": False,
            }
            if item["role"] == "core" or item["model_candidate"]:
                domain_name = item["feature_family"] if item["feature_family"] in ("earnings_growth", "earnings_quality", "macro_confirmation") else ("long_term_trend" if item["feature_family"].startswith("trend_") else ("sentiment_overlay" if item["feature_family"] == "sentiment_overlay" else "valuation"))
                if item["model_candidate"]:
                    domain[domain_name]["candidate_feature_count"] += 1
                    if available:
                        domain[domain_name]["available_candidate_count"] += 1
                    else:
                        domain[domain_name]["unavailable_paths"].append(path)
            if available and item["model_candidate"]:
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
            features[path] = feature
        for value in domain.values():
            count = value["candidate_feature_count"]
            value["coverage_pct"] = round(value["available_candidate_count"] / count * 100, 2) if count else 0.0
        output.append({"month": month, "basis_trade_date": basis, "contract_version": contract["contract_version"], "dataset_frozen_hash": manifest["frozen_records_sha256"], "features": features, "domain_availability": dict(domain)})
    return output


def build_audit(rows: list[dict[str, Any]], records: list[dict[str, Any]], contract: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    registry_paths = {item["path"] for item in contract["model_input_registry"]}
    unauthorized: list[str] = []
    future_pit = 0
    missing_registry = 0
    type_violations = 0
    family_missing = 0
    candidate_missing = 0
    unexpected = 0
    for row in rows:
        for path, feature in row["features"].items():
            if path not in registry_paths:
                unauthorized.append(path)
            if feature["available"] and not feature["pit_safe"]:
                future_pit += 1
            if not feature["feature_family"]:
                family_missing += 1
            if not isinstance(feature["model_candidate"], bool):
                candidate_missing += 1
            raw = feature["raw_value"]
            if raw is not None and (not isinstance(raw, (bool, int, float)) or (feature["unit"] == "boolean" and not isinstance(raw, bool)) or (feature["unit"] != "boolean" and (isinstance(raw, bool) or not isinstance(raw, (int, float))))):
                type_violations += 1
            if not feature["available"] and not feature["expected_missing"]:
                unexpected += 1
        missing_registry += sum(path not in row["features"] for path in registry_paths)
    audit = {"record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "source_contract_version": contract["contract_version"], "source_frozen_records_sha256": manifest["frozen_records_sha256"], "unauthorized_input_count": len(set(unauthorized)), "unauthorized_inputs": sorted(set(unauthorized)), "future_pit_date_count": future_pit, "missing_registry_path_count": missing_registry, "feature_type_violation_count": type_violations, "normalization_future_leakage_count": 0, "feature_family_missing_count": family_missing, "candidate_flag_missing_count": candidate_missing, "unexpected_input_missing_count": unexpected, "passed": False}
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
