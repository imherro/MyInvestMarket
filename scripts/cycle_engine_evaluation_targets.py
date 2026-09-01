"""Build the evaluation-only target layer for Cycle Engine v1.

This module is intentionally downstream of the frozen dataset.  Its targets
use future prices for ex-post evaluation and must never be imported by the
model-side Evidence Vector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_cycle_dataset_contract as freeze  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATASET_PATH = DATA / "cycle_dataset_v1.json"
TARGETS_PATH = DATA / "cycle_engine_evaluation_targets_v1.json"
AUDIT_PATH = DATA / "cycle_engine_evaluation_targets_audit_v1.json"
EVIDENCE_PATH = DATA / "cycle_engine_features_v1.json"

HORIZONS = (3, 6, 12, 24)
RISK_HORIZONS = (6, 12, 24)
BENCHMARKS = ("csi300", "csi500", "broad_proxy")
SPOT_MONTHS = ("2010-01", "2014-06", "2015-06", "2015-08", "2018-01", "2018-12", "2020-03", "2021-02", "2022-04", "2024-02")
EXPECTED_FROZEN_RECORDS_SHA256 = "82d5e6046aa7607d1b9646cd46de02eb512def1bd93a22881b0cc4d02c2c95d0"
EXPECTED_CONTRACT_SHA256 = "062604d15805b01105f5fdf6aa1ecf8bd3024d0a730a341d635eee9331bd60ff"
EXPECTED_MATRIX_SHA256 = "86103098b57d2f084ebec3c565231a785875769841a205eb4685ce1e562b7dca"
EXPECTED_FORBIDDEN_ENGINE_TOKENS = ("forward_", "months_to_", "broad_proxy", "evaluation_target")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha256_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8-sig"))


def close_value(record: dict[str, Any], index: str) -> float | None:
    item = record["trend"]["indices"][index]["close"]
    if not item.get("available") or not isinstance(item.get("value"), (int, float)):
        return None
    return float(item["value"])


def pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 6)


def round_value(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def shift_month(month: str, offset: int) -> str:
    year, current = (int(part) for part in month.split("-"))
    absolute = year * 12 + current - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def max_drawdown(path: list[float]) -> float | None:
    if not path:
        return None
    peak = path[0]
    worst = 0.0
    for value in path:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return pct(worst)


def build_broad_proxy(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    months = [r["month"] for r in records]
    previous: dict[str, float | None] = {"csi300": None, "csi500": None}
    proxy = 100.0
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for record in records:
        closes = {name: close_value(record, name) for name in ("csi300", "csi500")}
        returns: dict[str, float | None] = {}
        for name in ("csi300", "csi500"):
            current = closes[name]
            old = previous[name]
            returns[name] = None if current is None or old is None else current / old - 1.0
        if returns["csi300"] is None or returns["csi500"] is None:
            broad_return = None
            broad_proxy_value = 100.0 if not rows else None
        else:
            broad_return = 0.5 * returns["csi300"] + 0.5 * returns["csi500"]
            proxy *= 1.0 + broad_return
            broad_proxy_value = proxy
        rows.append({
            "month": record["month"],
            "basis_trade_date": record["basis_trade_date"],
            "observation_date": record.get("observation_date", record["basis_trade_date"]),
            "closes": closes,
            "monthly_returns": returns,
            "broad_monthly_return": broad_return,
            "broad_proxy_index": broad_proxy_value,
        })
        previous = closes
    if months != sorted(months) or len(months) != len(set(months)):
        errors.append("dataset months are not strictly unique and ordered")
    return rows, errors


def make_benchmark_series(proxy_rows: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    return {
        "csi300": [row["closes"]["csi300"] for row in proxy_rows],
        "csi500": [row["closes"]["csi500"] for row in proxy_rows],
        "broad_proxy": [row["broad_proxy_index"] for row in proxy_rows],
    }


class FrozenEvaluationSourceInvalid(RuntimeError):
    """Raised when the evaluation source is not the approved Final Freeze."""


def frozen_source_gate(dataset: dict[str, Any]) -> None:
    actual_hash = freeze.sha256(freeze.records_for_hash(dataset, "2026-08"))
    if actual_hash != EXPECTED_FROZEN_RECORDS_SHA256:
        raise FrozenEvaluationSourceInvalid("frozen records hash does not match the approved Final Freeze")
    manifest = json.loads((DATA / "cycle_dataset_freeze_manifest_v1.json").read_text(encoding="utf-8"))
    if manifest.get("contract_sha256") != EXPECTED_CONTRACT_SHA256 or manifest.get("feature_availability_sha256") != EXPECTED_MATRIX_SHA256:
        raise FrozenEvaluationSourceInvalid("freeze manifest hash does not match the approved Final Freeze")
    result = freeze.validate(
        dataset,
        json.loads((DATA / "cycle_dataset_contract_v1.json").read_text(encoding="utf-8")),
        json.loads((DATA / "cycle_dataset_feature_availability_v1.json").read_text(encoding="utf-8")),
        manifest,
        json.loads((DATA / "cycle_dataset_golden_spots_v1.json").read_text(encoding="utf-8")),
    )
    if not result["valid"]:
        raise FrozenEvaluationSourceInvalid("frozen dataset validation failed")


def forward_metrics(series: list[float | None], position: int, horizon: int, months: list[str], month_positions: dict[str, int]) -> dict[str, Any]:
    target_month = shift_month(months[position], horizon)
    target_index = month_positions.get(target_month)
    available = target_index is not None and all(series[i] is not None for i in range(position, target_index + 1))
    if not available:
        return {"target_available": False, "target_month": None, "forward_return_pct": None, "worst_forward_return_pct": None, "best_forward_return_pct": None, "max_drawdown_pct": None, "months_to_worst": None, "months_to_best": None}
    base = float(series[position])
    path = [float(series[i]) for i in range(position, target_index + 1)]
    path_returns = [value / base - 1.0 for value in path]
    worst_i = min(range(len(path_returns)), key=lambda i: path_returns[i])
    best_i = max(range(len(path_returns)), key=lambda i: path_returns[i])
    return {
        "target_available": True,
        "target_month": target_month,
        "forward_return_pct": pct(path[-1] / base - 1.0),
        "worst_forward_return_pct": pct(min(path_returns)),
        "best_forward_return_pct": pct(max(path_returns)),
        "max_drawdown_pct": max_drawdown(path),
        "months_to_worst": worst_i,
        "months_to_best": best_i,
    }


def build_targets(dataset: dict[str, Any]) -> dict[str, Any]:
    source_records = dataset["records"]
    proxy_rows, errors = build_broad_proxy(source_records)
    months = [row["month"] for row in proxy_rows]
    month_positions = {month: i for i, month in enumerate(months)}
    series = make_benchmark_series(proxy_rows)
    records: list[dict[str, Any]] = []
    for i, row in enumerate(proxy_rows):
        benchmarks: dict[str, Any] = {}
        for benchmark in BENCHMARKS:
            metrics = {f"forward_{h}m": forward_metrics(series[benchmark], i, h, months, month_positions) for h in HORIZONS}
            for h in HORIZONS:
                metrics[f"forward_{h}m"]["risk_metric_available"] = h in RISK_HORIZONS and metrics[f"forward_{h}m"]["target_available"]
                if h not in RISK_HORIZONS:
                    metrics[f"forward_{h}m"]["max_drawdown_pct"] = None
            benchmarks[benchmark] = metrics
        records.append({
            "month": row["month"],
            "basis_trade_date": row["basis_trade_date"],
            "observation_date": row["observation_date"],
            "evaluation_only": True,
            "uses_future_information": True,
            "source_closes": row["closes"],
            "monthly_returns": {k: pct(v) for k, v in row["monthly_returns"].items()},
            "broad_monthly_return_pct": pct(row["broad_monthly_return"]),
            "broad_proxy_index": round_value(row["broad_proxy_index"]),
            "benchmarks": benchmarks,
        })
    return {
        "schema_version": "cycle_engine_evaluation_targets_v1",
        "description": "Ex-post market outcomes for evaluating Cycle Engine v1; never a model input.",
        "evaluation_only": True,
        "uses_future_information": True,
        "future_information_required": True,
        "benchmark_definition": "CSI300 and CSI500 monthly price returns; broad_proxy is a 50/50 monthly rebalanced price proxy starting at 100.",
        "horizons_months": list(HORIZONS),
        "risk_horizons_months": list(RISK_HORIZONS),
        "records": records,
        "historical_spots": [record for record in records if record["month"] in SPOT_MONTHS],
        "source_frozen_records_sha256": None,
        "source_record_count": len(source_records),
        "build_warnings": errors,
    }


def get_metric(record: dict[str, Any], benchmark: str, horizon: int, key: str) -> Any:
    return record["benchmarks"][benchmark][f"forward_{horizon}m"][key]


def audit_targets(targets: dict[str, Any], dataset: dict[str, Any], evidence_before: str | None = None) -> dict[str, Any]:
    source_records = dataset["records"]
    proxy_rows, order_errors = build_broad_proxy(source_records)
    months = [row["month"] for row in proxy_rows]
    series = make_benchmark_series(proxy_rows)
    errors: dict[str, int] = {
        "source_close_missing_count": 0, "source_close_future_violation_count": 0,
        "source_month_gap_count": 0, "duplicate_month_count": 0, "order_violation_count": len(order_errors),
        "horizon_alignment_violation_count": 0, "return_formula_violation_count": 0,
        "broad_proxy_formula_violation_count": 0, "max_drawdown_formula_violation_count": 0,
        "tail_availability_violation_count": 0, "evaluation_input_leakage_count": 0,
        "evidence_contamination_count": 0, "frozen_file_mutation_count": 0,
    }
    if len(months) != len(set(months)):
        errors["duplicate_month_count"] += len(months) - len(set(months))
    expected_source_hash = freeze.sha256(freeze.records_for_hash(dataset, "2026-08"))
    if expected_source_hash != EXPECTED_FROZEN_RECORDS_SHA256 or targets.get("source_frozen_records_sha256") != EXPECTED_FROZEN_RECORDS_SHA256:
        errors["frozen_file_mutation_count"] += 1
    if any(shift_month(months[i], 1) != months[i + 1] for i in range(len(months) - 1)):
        errors["source_month_gap_count"] += 1
    manifest = json.loads((DATA / "cycle_dataset_freeze_manifest_v1.json").read_text(encoding="utf-8"))
    if manifest.get("contract_sha256") != EXPECTED_CONTRACT_SHA256 or manifest.get("feature_availability_sha256") != EXPECTED_MATRIX_SHA256:
        errors["frozen_file_mutation_count"] += 1
    engine_source = (ROOT / "scripts/cycle_engine_features.py").read_text(encoding="utf-8")
    if any(token in engine_source for token in EXPECTED_FORBIDDEN_ENGINE_TOKENS):
        errors["evaluation_input_leakage_count"] += 1
    for source_record in source_records:
        for index in ("csi300", "csi500"):
            close = source_record["trend"]["indices"][index]["close"]
            if close.get("available") and close.get("observation_date") and close["observation_date"] > source_record["basis_trade_date"]:
                errors["source_close_future_violation_count"] += 1
    for i, row in enumerate(proxy_rows):
        if row["closes"]["csi300"] is None or row["closes"]["csi500"] is None:
            errors["source_close_missing_count"] += 1
        if i and row["broad_monthly_return"] is not None:
            expected = 0.5 * row["monthly_returns"]["csi300"] + 0.5 * row["monthly_returns"]["csi500"]
            if not math.isclose(row["broad_monthly_return"], expected, abs_tol=1e-9):
                errors["broad_proxy_formula_violation_count"] += 1
    expected_targets = build_targets(dataset)["records"]
    actual_records = targets.get("records", [])
    if len(actual_records) != len(expected_targets):
        errors["horizon_alignment_violation_count"] += 1
    expected_months = {item["month"] for item in expected_targets}
    for i, (expected, actual) in enumerate(zip(expected_targets, actual_records)):
        if actual.get("month") != expected["month"]:
            errors["horizon_alignment_violation_count"] += 1
            continue
        if actual.get("evaluation_only") is not True or actual.get("uses_future_information") is not True:
            errors["evidence_contamination_count"] += 1
        if actual.get("monthly_returns") != expected["monthly_returns"] or actual.get("broad_monthly_return_pct") != expected["broad_monthly_return_pct"] or actual.get("broad_proxy_index") != expected["broad_proxy_index"]:
            errors["broad_proxy_formula_violation_count"] += 1
        for benchmark in BENCHMARKS:
            for horizon in HORIZONS:
                exp = expected["benchmarks"][benchmark][f"forward_{horizon}m"]
                got = actual.get("benchmarks", {}).get(benchmark, {}).get(f"forward_{horizon}m", {})
                complete = exp["target_available"]
                if got.get("target_month") != exp["target_month"] or got.get("target_available") != complete:
                    errors["horizon_alignment_violation_count"] += 1
                if got.get("risk_metric_available") != (horizon in RISK_HORIZONS and complete):
                    errors["horizon_alignment_violation_count"] += 1
                for key in ("forward_return_pct", "worst_forward_return_pct", "best_forward_return_pct"):
                    if got.get(key) != exp[key]:
                        errors["return_formula_violation_count"] += 1
                if got.get("max_drawdown_pct") != (exp["max_drawdown_pct"] if horizon in RISK_HORIZONS else None):
                    errors["max_drawdown_formula_violation_count"] += 1
            for horizon in RISK_HORIZONS:
                if shift_month(expected["month"], horizon) not in expected_months and get_metric(actual, benchmark, horizon, "target_available"):
                    errors["tail_availability_violation_count"] += 1
    if evidence_before is not None and EVIDENCE_PATH.read_text(encoding="utf-8") != evidence_before:
        errors["evidence_contamination_count"] += 1
    violations = sum(errors.values())
    return {
        "schema_version": "cycle_engine_evaluation_targets_audit_v1",
        "record_count": len(actual_records),
        "start_month": months[0] if months else None,
        "end_month": months[-1] if months else None,
        "expected_frozen_records_sha256": EXPECTED_FROZEN_RECORDS_SHA256,
        "actual_frozen_records_sha256": targets.get("source_frozen_records_sha256"),
        "frozen_hash_match": targets.get("source_frozen_records_sha256") == EXPECTED_FROZEN_RECORDS_SHA256,
        "evaluation_only": targets.get("evaluation_only") is True,
        "future_information_required": targets.get("future_information_required") is True,
        **errors,
        "passed": violations == 0 and targets.get("evaluation_only") is True and targets.get("uses_future_information") is True,
    }


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = load_dataset()
    frozen_source_gate(dataset)
    targets = build_targets(dataset)
    targets["source_frozen_records_sha256"] = freeze.sha256(freeze.records_for_hash(dataset, "2026-08"))
    evidence_before = EVIDENCE_PATH.read_text(encoding="utf-8") if EVIDENCE_PATH.exists() else None
    audit = audit_targets(targets, dataset, evidence_before=evidence_before)
    TARGETS_PATH.write_text(json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return targets, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if not args.generate:
        parser.error("use --generate")
    _, audit = generate()
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
