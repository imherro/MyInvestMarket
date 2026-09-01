"""Generate and validate the frozen Cycle Dataset v1 contract artifacts."""

import argparse
import hashlib
import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

import build_cycle_dataset as cycle


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONTRACT_PATH = DATA / "cycle_dataset_contract_v1.json"
MATRIX_PATH = DATA / "cycle_dataset_feature_availability_v1.json"
GOLDEN_PATH = DATA / "cycle_dataset_golden_spots_v1.json"
MANIFEST_PATH = DATA / "cycle_dataset_freeze_manifest_v1.json"
FROZEN_THROUGH = "2026-08"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def resolve(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def has_path(record: dict[str, Any], path: str) -> bool:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


def entry(path: str, domain: str, role: str, unit: str, direction: str, availability: str, pit_date: str, description: str) -> dict[str, str]:
    return {"path": path, "domain": domain, "role": role, "unit": unit, "direction_hint": direction, "availability_rule": availability, "pit_date_field": pit_date, "missing_policy": "null; never impute or proxy", "description": description}


def build_registry() -> list[dict[str, str]]:
    registry: list[dict[str, str]] = []
    for index in ("csi300", "csi500", "csi1000"):
        for field, direction, description in (("pe_ttm", "higher is more expensive", "TTM PE level"), ("pb", "higher is more expensive", "PB level")):
            registry.extend([
                entry(f"valuation.indices.{index}.{field}.value", "valuation", "core", "ratio", direction, "PIT-visible index valuation", "observation_date", description),
                entry(f"valuation.indices.{index}.{field}.percentile_expanding", "valuation", "core", "percentile", direction, "PIT-visible expanding history", "observation_date", f"Expanding historical percentile of {field}"),
            ])
    registry.extend([
        entry("valuation.csi300_earnings_yield_pct.value", "valuation", "core", "percent", "higher is more attractive", "PIT-visible derived CSI300 earnings yield", "observation_date", "CSI300 earnings yield"),
        entry("valuation.china_10y_government_bond_yield_pct.value", "valuation", "core", "percent", "higher raises discount rate", "PIT-visible bond yield", "observation_date", "China 10-year government bond yield"),
        entry("valuation.csi300_erp_pct.value", "valuation", "core", "percent", "higher is more attractive", "derived from PIT-visible earnings yield and bond yield", "observation_date", "CSI300 equity risk premium"),
    ])
    for field, direction, description in (("all_a_net_profit_yoy_pct", "higher/improving is better", "All-A net profit YoY"), ("nonfinancial_a_net_profit_yoy_pct", "higher/improving is better", "Nonfinancial All-A net profit YoY"), ("all_a_roe_ttm_pct", "higher/improving is better", "All-A ROE TTM"), ("nonfinancial_a_roe_ttm_pct", "higher/improving is better", "Nonfinancial ROE TTM")):
        registry.append(entry(f"earnings.{field}.value", "earnings", "core", "percent", direction, "PIT-visible announced financial data", "announcement_date", description))
    registry.extend([
        entry("earnings.pmi.value", "macro_confirmation", "core", "index", "above 50 is expansion", "trusted published PMI release visible at basis", "publish_date", "Manufacturing PMI value"),
        entry("earnings.pmi.change_1m", "macro_confirmation", "core", "index points", "positive is improving", "exact natural prior month must be trusted and published", "publish_date", "PMI change versus natural prior data month"),
        entry("earnings.pmi.change_3m", "macro_confirmation", "core", "index points", "positive is improving", "exact natural three-month prior month must be trusted and published", "publish_date", "PMI change versus natural three-month prior data month"),
        entry("earnings.pmi.above_50", "macro_confirmation", "core", "boolean", "true is expansion", "same as trusted PMI value", "publish_date", "PMI above 50 flag"),
    ])
    for index in cycle.INDEXES:
        for field, direction, description in (("ma250_deviation_pct", "positive is above long-term mean", "Close deviation from 250-observation mean"), ("above_ma250", "true is above long-term mean", "Close above 250-observation mean"), ("ma250_slope_3m_pct", "positive is rising", "250-observation mean slope over 63 observations"), ("return_6m_pct", "positive is upward momentum", "126-observation return"), ("return_12m_pct", "positive is upward momentum", "252-observation return"), ("drawdown_12m_high_pct", "more negative is weaker", "Drawdown from inclusive rolling 252-observation high")):
            registry.append(entry(f"trend.indices.{index}.{field}.value", "long_term_trend", "core", "percent" if field != "above_ma250" else "boolean", direction, "PIT-visible index history after official launch", "observation_date", f"{index} {description}"))
    registry.append(entry("sentiment.a_fear.fear_score", "sentiment", "overlay", "0-100", "higher is more fearful", "available only when local A-FEAR history is present", "basis_trade_date", "A-FEAR extreme-fear overlay"))
    return annotate_registry(registry)


def feature_family(path: str) -> str:
    if path.startswith("valuation.indices."):
        return "valuation_level"
    if path == "valuation.csi300_erp_pct.value":
        return "relative_valuation"
    if path.startswith("valuation."):
        return "valuation_lineage"
    if path.startswith("earnings.all_a_net_profit") or path.startswith("earnings.nonfinancial_a_net_profit"):
        return "earnings_growth"
    if path.startswith("earnings.all_a_roe") or path.startswith("earnings.nonfinancial_a_roe"):
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
    if path in ("valuation.csi300_earnings_yield_pct.value", "valuation.china_10y_government_bond_yield_pct.value"):
        return False
    return True


def annotate_registry(registry: list[dict[str, str]]) -> list[dict[str, str]]:
    for item in registry:
        path = item["path"]
        item["feature_family"] = feature_family(path)
        item["model_candidate"] = model_candidate(path)
    return registry


EXCLUDED = [
    "industrial_profit_yoy_pct", "ppi_yoy_pct", "CPI", "M1", "M2", "social_financing", "credit_impulse", "capital_flow", "northbound_flow", "main_fund_flow", "theme_concentration", "short_term_5d_20d_momentum", "short_term_breadth", "daily_volume_ratio", "current_v3.4_market_score", "market_regime.py output", "market_risk.py output", "market_trend.py legacy output", "crowding_score", "four_sleeve_allocation",
]


ACCEPTED_LIMITATIONS = [
    {"id": "csi1000_valuation_unavailable", "description": "Tushare index_dailybasic currently has no CSI1000 valuation records; no proxy is permitted."},
    {"id": "a_fear_begins_2024", "description": "A-FEAR is a modern historical overlay and is intentionally unavailable before its local history begins."},
    {"id": "pmi_revision_vintage_unavailable", "description": "PMI release-date PIT is maintained, but a complete real-time revision vintage database is not available."},
    {"id": "financial_revision_vintage_limitation", "description": "Financial announcement-date/version handling is retained, but upstream revisions cannot be fully reconstructed when the source does not expose every vintage."},
    {"id": "index_backfilled_histories", "description": "Index backfilled history may warm up calculations only on or after the official launch date; pre-launch snapshots are unavailable."},
]


def build_contract(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": "cycle_dataset_contract_v1",
        "dataset": {"contract_version": "cycle_dataset_contract_v1", "dataset_version": cycle.DATASET_VERSION, "frequency": "monthly", "start_month": records[0]["month"], "frozen_through_month": FROZEN_THROUGH, "basis_rule": "last open SSE trading day of natural month", "timezone": "Asia/Shanghai"},
        "model_input_registry": build_registry(),
        "expected_missing_policy": build_expected_missing_policy(),
        "excluded_from_cycle_engine_v1": EXCLUDED,
        "missing_policy": {"default": None, "rules": ["unavailable remains null", "never impute 0, 50, historical mean, current value, or proxy", "pre-launch index history is expected missing", "CSI1000 valuation source absence is an accepted limitation", "A-FEAR pre-history is expected missing", "PMI release conflicts are not resolved randomly", "financial fields use only PIT-visible announced periods"]},
        "accepted_limitations": ACCEPTED_LIMITATIONS,
    }


def build_expected_missing_policy() -> list[dict[str, Any]]:
    policy: list[dict[str, Any]] = []
    for field in ("pe_ttm.value", "pe_ttm.percentile_expanding", "pb.value", "pb.percentile_expanding"):
        policy.append({"path": f"valuation.indices.csi1000.{field}", "rule_type": "all_frozen_window", "from_month": "2010-01", "through_month": FROZEN_THROUGH, "future_behavior": "continue_until_source_restored", "reason": "CSI1000 valuation source is unavailable; no proxy is permitted", "accepted_limitation_id": "csi1000_valuation_unavailable"})
    for field in ("ma250_deviation_pct.value", "above_ma250.value", "ma250_slope_3m_pct.value", "return_6m_pct.value", "return_12m_pct.value", "drawdown_12m_high_pct.value"):
        policy.append({"path": f"trend.indices.csi1000.{field}", "rule_type": "before_month", "from_month": "2010-01", "through_month": "2014-09", "reason": "CSI1000 was not officially published before 2014-10", "accepted_limitation_id": "index_backfilled_histories"})
    policy.append({"path": "sentiment.a_fear.fear_score", "rule_type": "before_month", "from_month": "2010-01", "through_month": "2024-07", "reason": "A-FEAR local history begins at 2024-08", "accepted_limitation_id": "a_fear_begins_2024"})
    for field in ("all_a_net_profit_yoy_pct", "nonfinancial_a_net_profit_yoy_pct", "all_a_roe_ttm_pct", "nonfinancial_a_roe_ttm_pct"):
        policy.append({"path": f"earnings.{field}.value", "rule_type": "explicit_months", "months": ["2010-01", "2010-02", "2010-03"], "reason": "the frozen financial history has no eligible PIT observation in the initial three months", "accepted_limitation_id": "financial_revision_vintage_limitation"})
    policy.extend([
        {"path": "earnings.pmi.change_1m", "rule_type": "explicit_months", "months": ["2026-02", "2026-03", "2026-04", "2026-05"], "reason": "the natural prior PMI data month is unavailable in the frozen release-date history", "accepted_limitation_id": "pmi_revision_vintage_unavailable"},
        {"path": "earnings.pmi.change_3m", "rule_type": "explicit_months", "months": ["2026-02", "2026-03", "2026-06"], "reason": "the natural three-month prior PMI data month is unavailable in the frozen release-date history", "accepted_limitation_id": "pmi_revision_vintage_unavailable"},
    ])
    return policy


def is_expected_missing(path: str, month: str, policy: list[dict[str, Any]]) -> bool:
    for item in policy:
        if item.get("path") != path:
            continue
        rule_type = item.get("rule_type")
        if rule_type == "all_frozen_window":
            return item.get("from_month") <= month <= item.get("through_month") or (month > item.get("through_month") and item.get("future_behavior") == "continue_until_source_restored")
        if rule_type == "before_month":
            return item.get("from_month") <= month <= item.get("through_month")
        if rule_type == "explicit_months":
            return month in item.get("months", [])
    return False


def build_matrix(records: list[dict[str, Any]], registry: list[dict[str, str]], policy: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    policy = policy or []
    fields: dict[str, Any] = {}
    for item in registry:
        path = item["path"]
        available_months = [r["month"] for r in records if resolve(r, path) is not None]
        first = min(available_months) if available_months else None
        expected = [r["month"] for r in records if resolve(r, path) is None and is_expected_missing(path, r["month"], policy)]
        unexpected = [r["month"] for r in records if resolve(r, path) is None and r["month"] not in expected]
        fields[path] = {"domain": item["domain"], "available_month_count": len(available_months), "unavailable_month_count": len(records) - len(available_months), "availability_pct": round(len(available_months) / len(records) * 100, 2) if records else 0.0, "first_available_month": first, "last_available_month": max(available_months) if available_months else None, "expected_missing_count": len(expected), "unexpected_missing_count": len(unexpected), "expected_missing_months": expected, "unexpected_missing_months": unexpected}
    return {"contract_version": "cycle_dataset_contract_v1", "record_count": len(records), "fields": fields, "unexpected_required_input_missing_count": sum(v["unexpected_missing_count"] for v in fields.values())}


def build_golden(records: list[dict[str, Any]], registry: list[dict[str, str]]) -> dict[str, Any]:
    months = ["2010-01", "2014-09", "2014-10", "2015-06", "2015-08", "2018-12", "2020-03", "2021-02", "2024-02", "2026-08"]
    selected = {"valuation.indices.csi300.pe_ttm.percentile_expanding", "valuation.indices.csi500.pe_ttm.percentile_expanding", "valuation.csi300_erp_pct.value", "earnings.all_a_net_profit_yoy_pct.value", "earnings.nonfinancial_a_net_profit_yoy_pct.value", "earnings.all_a_roe_ttm_pct.value", "earnings.nonfinancial_a_roe_ttm_pct.value", "earnings.pmi.value", "sentiment.a_fear.fear_score"}
    paths = [item["path"] for item in registry if item["path"] in selected or item["path"].startswith("trend.indices.")]
    paths.append("earnings.pmi.data_month")
    output: dict[str, Any] = {"contract_version": "cycle_dataset_contract_v1", "months": {}}
    for month in months:
        record = next(r for r in records if r["month"] == month)
        output["months"][month] = {path: resolve(record, path) for path in paths}
    return output


def records_for_hash(payload: dict[str, Any], through: str | None = None) -> list[dict[str, Any]]:
    records = [r for r in payload.get("records", []) if through is None or r.get("month", "") <= through]
    return sorted(records, key=lambda r: r.get("month", ""))


def validate(payload: dict[str, Any], contract: dict[str, Any], matrix: dict[str, Any], manifest: dict[str, Any] | None = None, golden: dict[str, Any] | None = None) -> dict[str, Any]:
    records = payload.get("records", [])
    errors: list[str] = []
    try:
        audit = cycle.audit_dataset(payload)
    except (TypeError, ValueError, KeyError) as exc:
        audit = {"structural_passed": False, "validator_exception": f"{type(exc).__name__}: {exc}"}
        errors.append("dataset audit could not be completed")
    frozen_records = [record for record in records if record.get("month", "") <= FROZEN_THROUGH]
    expected_frozen_months = [f"{year:04d}-{month:02d}" for year in range(2010, 2027) for month in range(1, 13) if f"{year:04d}-{month:02d}" <= FROZEN_THROUGH]
    if len(frozen_records) != 200 or [record.get("month") for record in frozen_records] != expected_frozen_months:
        errors.append("record range/count mismatch")
    dataset = contract.get("dataset", {})
    expected_dataset = {
        "contract_version": "cycle_dataset_contract_v1",
        "dataset_version": cycle.DATASET_VERSION,
        "frequency": "monthly",
        "start_month": "2010-01",
        "frozen_through_month": FROZEN_THROUGH,
        "basis_rule": "last open SSE trading day of natural month",
        "timezone": "Asia/Shanghai",
    }
    for key, expected in expected_dataset.items():
        if dataset.get(key) != expected:
            errors.append(f"dataset metadata mismatch: {key}")
    registry = contract.get("model_input_registry", [])
    policy = contract.get("expected_missing_policy", [])
    policy_keys = {"path", "rule_type", "reason", "accepted_limitation_id"}
    for item in policy:
        if not policy_keys.issubset(item):
            errors.append(f"expected missing policy entry missing keys: {item.get('path', '<unknown>')}")
        if item.get("rule_type") in ("all_frozen_window", "before_month") and not {"from_month", "through_month"}.issubset(item):
            errors.append(f"expected missing policy range missing: {item.get('path', '<unknown>')}")
        if item.get("rule_type") == "explicit_months" and not isinstance(item.get("months"), list):
            errors.append(f"expected missing policy months missing: {item.get('path', '<unknown>')}")
    required_keys = {"path", "domain", "role", "unit", "direction_hint", "availability_rule", "pit_date_field", "missing_policy", "description", "feature_family", "model_candidate"}
    for item in registry:
        if not required_keys.issubset(item):
            errors.append(f"registry entry missing keys: {item.get('path', '<unknown>')}")
        expected_boolean = item.get("unit") == "boolean"
        if not isinstance(item.get("model_candidate"), bool) or not item.get("feature_family"):
            errors.append(f"registry metadata mismatch: {item.get('path', '<unknown>')}")
        for record in records:
            if not has_path(record, item.get("path", "")):
                errors.append(f"required path missing: {item.get('path')}")
                break
            value = resolve(record, item["path"])
            if value is not None and ((expected_boolean and not isinstance(value, bool)) or (not expected_boolean and (not isinstance(value, (int, float)) or isinstance(value, bool)))):
                errors.append(f"field type mismatch: {item['path']}")
                break
    excluded_text = set(contract.get("excluded_from_cycle_engine_v1", []))
    if any(item.get("path") in excluded_text for item in registry):
        errors.append("excluded field is in model registry")
    if audit.get("structural_passed") is not True:
        errors.append("structural audit failed")
    if matrix.get("unexpected_required_input_missing_count", 0) != 0:
        errors.append("unexpected required input missing")
    actual_matrix = build_matrix(records, registry, policy)
    if actual_matrix != matrix:
        errors.append("feature availability matrix mismatch")
    if actual_matrix.get("unexpected_required_input_missing_count", 0) != 0:
        errors.append("actual unexpected required input missing")
    if manifest:
        frozen_hash = sha256(records_for_hash(payload, FROZEN_THROUGH))
        current_hash = sha256(records_for_hash(payload))
        if manifest.get("records_sha256", manifest.get("frozen_records_sha256")) != frozen_hash or manifest.get("frozen_records_sha256") != frozen_hash:
            errors.append("frozen history hash mismatch")
        if manifest.get("current_records_sha256") != current_hash:
            errors.append("current history hash mismatch")
        if manifest.get("contract_sha256") != sha256(contract):
            errors.append("contract hash mismatch")
        if manifest.get("feature_availability_sha256") != sha256(matrix):
            errors.append("feature availability hash mismatch")
        if manifest.get("structural_freeze_passed") is not True or manifest.get("structural_passed_at_freeze") is not True:
            errors.append("structural freeze gate not passed")
    if golden:
        for month, expected in golden.get("months", {}).items():
            record = next((item for item in records if item.get("month") == month), None)
            if record is None:
                errors.append(f"golden month missing: {month}")
                continue
            for path, expected_value in expected.items():
                actual = resolve(record, path)
                if isinstance(expected_value, (int, float)) and isinstance(actual, (int, float)):
                    if abs(float(actual) - float(expected_value)) > 0.00011:
                        errors.append(f"golden drift: {month} {path}")
                elif actual != expected_value:
                    errors.append(f"golden drift: {month} {path}")
    return {"valid": not errors, "errors": errors, "audit": audit, "unexpected_required_input_missing_count": actual_matrix.get("unexpected_required_input_missing_count", 0)}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate() -> dict[str, Any]:
    payload = json.loads((DATA / "cycle_dataset_v1.json").read_text(encoding="utf-8-sig"))
    records = records_for_hash(payload)
    contract = build_contract(records)
    matrix = build_matrix(records, contract["model_input_registry"], contract["expected_missing_policy"])
    golden = build_golden(records, contract["model_input_registry"])
    audit = cycle.audit_dataset(payload)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    frozen_hash = sha256(records_for_hash(payload, FROZEN_THROUGH))
    manifest = {"contract_version": contract["contract_version"], "frozen_through_month": FROZEN_THROUGH, "record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "baseline_git_commit": baseline, "records_sha256": frozen_hash, "frozen_records_sha256": frozen_hash, "current_records_sha256": sha256(records_for_hash(payload)), "contract_sha256": sha256(contract), "feature_availability_sha256": sha256(matrix), "structural_freeze_passed": bool(audit.get("structural_passed")), "freshness_at_freeze": bool(audit.get("freshness_passed")), "structural_passed_at_freeze": bool(audit.get("structural_passed")), "unexpected_required_input_missing_count": matrix["unexpected_required_input_missing_count"], "accepted_limitations": ACCEPTED_LIMITATIONS, "created_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    write_json(CONTRACT_PATH, contract)
    write_json(MATRIX_PATH, matrix)
    write_json(GOLDEN_PATH, golden)
    write_json(MANIFEST_PATH, manifest)
    result = validate(payload, contract, matrix, manifest, golden)
    result["manifest"] = manifest
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if args.generate:
        result = generate()
    else:
        payload = json.loads((DATA / "cycle_dataset_v1.json").read_text(encoding="utf-8-sig"))
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        result = validate(payload, contract, matrix, manifest, golden)
    print(json.dumps({"valid": result["valid"], "errors": result["errors"], "unexpected_required_input_missing_count": result["unexpected_required_input_missing_count"]}, ensure_ascii=False))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
