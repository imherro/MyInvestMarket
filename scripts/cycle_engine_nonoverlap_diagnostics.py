"""Fixed-calendar non-overlapping cohort diagnostics for Cycle Engine research."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
E = DATA / "cycle_engine_features_v1.json"
EA = DATA / "cycle_engine_features_audit_v1.json"
T = DATA / "cycle_engine_evaluation_targets_v1.json"
TA = DATA / "cycle_engine_evaluation_targets_audit_v1.json"
D = DATA / "cycle_engine_feature_diagnostics_v1.json"
DA = DATA / "cycle_engine_feature_diagnostics_audit_v1.json"
W = DATA / "cycle_engine_walk_forward_diagnostics_v1.json"
WA = DATA / "cycle_engine_walk_forward_diagnostics_audit_v1.json"
OUT = DATA / "cycle_engine_nonoverlap_diagnostics_v1.json"
AUD = DATA / "cycle_engine_nonoverlap_diagnostics_audit_v1.json"
HORIZONS = (6, 12, 24)
ERAS = {"A": ("2010-01", "2014-12"), "B": ("2015-01", "2019-12"), "C": ("2020-01", "2026-08")}
UPSTREAM_FILES = (E, EA, T, TA, D, DA, W, WA)
UPSTREAM_INPUTS = (E, T, D, W)
FORBIDDEN_OUTPUT_KEYS = {"score", "ranking", "selection", "state", "regime", "weight", "position", "allocation", "signal", "trade", "backtest", "threshold", "recommendation", "strongest_features", "weakest_features", "recommended_features", "selected_features", "drop_features", "feature_rank", "importance", "p_value", "t_stat", "significance_label"}


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def upstream_file_hashes() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in UPSTREAM_INPUTS}


def month_index(month: str) -> int:
    year, mon = (int(x) for x in month.split("-"))
    return year * 12 + mon


def rank(values: list[float]) -> list[float]:
    return [sum(x < z for x in values) + (sum(x == z for x in values) + 1) / 2 for z in values]


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return None if not den else round(sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / den, 6)


def median(values: list[float]) -> float | None:
    values = [value for value in values if value is not None]
    return None if not values else round(sorted(values)[len(values) // 2], 6)


def target_map(targets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["month"]: r for r in targets["records"]}


def valid_target(targets: dict[str, Any], origin: str, horizon: int) -> dict[str, Any] | None:
    record = target_map(targets).get(origin)
    if not record:
        return None
    target = record["benchmarks"]["broad_proxy"][f"forward_{horizon}m"]
    return target if target.get("target_available") else None


def measure(values: list[float], targets: list[dict[str, Any]], key: str) -> dict[str, Any]:
    points = [(x, t[key]) for x, t in zip(values, targets) if t.get(key) is not None]
    return {"sample_count": len(points), "spearman_rho": spearman([x for x, _ in points], [y for _, y in points])}


def boolean_measure(rows: list[tuple[bool, dict[str, Any]]], key: str) -> dict[str, Any]:
    groups = {}
    for state in (True, False):
        values = [target[key] for value, target in rows if value is state and target.get(key) is not None]
        groups["true" if state else "false"] = {"sample_count": len(values), "median": median(values)}
    true_median, false_median = groups["true"]["median"], groups["false"]["median"]
    groups["true_minus_false_median"] = round(true_median - false_median, 6) if true_median is not None and false_median is not None else None
    return groups


def stability(values: list[float | None]) -> dict[str, Any]:
    valid = [v for v in values if v is not None]
    pos, neg = sum(v > 0 for v in valid), sum(v < 0 for v in valid)
    return {"valid_cohort_count": len(valid), "median_rho": median(valid), "minimum_rho": min(valid) if valid else None,
            "maximum_rho": max(valid) if valid else None, "positive_cohort_count": pos, "negative_cohort_count": neg,
            "zero_or_null_cohort_count": len(values) - len(valid) + sum(v == 0 for v in valid),
            "sign_consistency_ratio": round(max(pos, neg) / len(valid), 6) if valid else None,
            "max_abs_rho": max((abs(v) for v in valid), default=None), "min_abs_rho": min((abs(v) for v in valid), default=None)}


def boolean_stability(values: list[float | None]) -> dict[str, Any]:
    valid = [v for v in values if v is not None]
    pos, neg = sum(v > 0 for v in valid), sum(v < 0 for v in valid)
    return {"valid_cohort_count": len(valid), "median_difference": median(valid), "minimum_difference": min(valid) if valid else None,
            "maximum_difference": max(valid) if valid else None, "positive_cohort_count": pos, "negative_cohort_count": neg,
            "sign_consistency_ratio": round(max(pos, neg) / len(valid), 6) if valid else None}


def load() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = json.loads(E.read_text(encoding="utf-8")); targets = json.loads(T.read_text(encoding="utf-8")); phase3 = json.loads(D.read_text(encoding="utf-8"))
    return evidence, targets, phase3


def build(evidence: dict[str, Any], targets: dict[str, Any], phase3: dict[str, Any]) -> dict[str, Any]:
    em = {r["month"]: r for r in evidence["records"]}; tm = target_map(targets); months = sorted(em)
    candidates = [p for p, f in evidence["records"][-1]["features"].items() if f.get("model_candidate")]
    features = {}
    for path in candidates:
        is_boolean = any(isinstance(em[m]["features"].get(path, {}).get("raw_value"), bool) for m in months)
        feature_out = {"feature_family": evidence["records"][-1]["features"].get(path, {}).get("feature_family"), "feature_type": "boolean" if is_boolean else "continuous", "horizons": {}}
        for horizon in HORIZONS:
            cohorts = {}
            for cohort in range(horizon):
                rows = []
                for month in months:
                    f = em[month]["features"].get(path, {})
                    if month_index(month) % horizon != cohort or not f.get("available") or not f.get("normalization_history_ready"):
                        continue
                    target = tm.get(month, {}).get("benchmarks", {}).get("broad_proxy", {}).get(f"forward_{horizon}m")
                    if not target or not target.get("target_available"):
                        continue
                    raw, rank_value = f.get("raw_value"), f.get("expanding_rank_pct")
                    if is_boolean and isinstance(raw, bool): rows.append((month, raw, target))
                    elif not is_boolean and rank_value is not None: rows.append((month, float(rank_value), target))
                item = {"cohort": f"cohort_{cohort}", "cohort_rule": f"calendar_month_index % {horizon}", "origin_months": [m for m, _, _ in rows]}
                if is_boolean:
                    bool_rows = [(value, target) for _, value, target in rows]
                    item["boolean"] = {"forward_return": boolean_measure(bool_rows, "forward_return_pct"), "max_drawdown": boolean_measure(bool_rows, "max_drawdown_pct")}
                else:
                    values, target_rows = [value for _, value, _ in rows], [target for _, _, target in rows]
                    item["continuous"] = {"forward_return": measure(values, target_rows, "forward_return_pct"), "max_drawdown": measure(values, target_rows, "max_drawdown_pct")}
                cohorts[f"cohort_{cohort}"] = item
            horizon_out = {"cohorts": cohorts}
            if is_boolean:
                ret = [v["boolean"]["forward_return"]["true_minus_false_median"] for v in cohorts.values()]
                dd = [v["boolean"]["max_drawdown"]["true_minus_false_median"] for v in cohorts.values()]
                horizon_out["stability"] = {"forward_return": boolean_stability(ret), "max_drawdown": boolean_stability(dd)}
                overlap = phase3.get("feature_diagnostics", {}).get(path, {}).get("target_diagnostics", {})
                old_ret = overlap.get(f"forward_{horizon}m_boolean_groups", {}).get("true_minus_false_median")
                old_dd = None
                horizon_out["overlap_comparison"] = {"forward_return": _comparison(old_ret, median(ret)), "max_drawdown": _comparison(old_dd, median(dd))}
            else:
                ret = [v["continuous"]["forward_return"]["spearman_rho"] for v in cohorts.values()]
                dd = [v["continuous"]["max_drawdown"]["spearman_rho"] for v in cohorts.values()]
                horizon_out["stability"] = {"forward_return": stability(ret), "max_drawdown": stability(dd)}
                overlap = phase3.get("feature_diagnostics", {}).get(path, {}).get("target_diagnostics", {})
                horizon_out["overlap_comparison"] = {"forward_return": _comparison(overlap.get(f"forward_{horizon}m_return_pct", {}).get("spearman_rho"), median(ret)), "max_drawdown": _comparison(overlap.get(f"forward_{horizon}m_max_drawdown_pct", {}).get("spearman_rho"), median(dd))}
            feature_out["horizons"][f"forward_{horizon}m"] = horizon_out
        features[path] = feature_out
    return {"schema": "cycle_engine_nonoverlap_diagnostics_v1", "research_only": True, "uses_future_information": True,
            "description": "Fixed natural-calendar non-overlapping cohort diagnostics; descriptive only, never a model input.",
            "cohort_rule": "calendar_month_index = year*12 + month; cohort = calendar_month_index % horizon",
            "horizons_months": list(HORIZONS), "eras": ERAS, "feature_count": len(evidence["records"][-1]["features"]), "candidate_feature_count": len(features), "features": features,
            "source_evidence_sha": canonical_sha(evidence), "source_evaluation_sha": canonical_sha(targets), "source_phase3_sha": canonical_sha(phase3),
            "source_phase4_sha": canonical_sha(json.loads(W.read_text(encoding="utf-8"))), "upstream_file_sha256": upstream_file_hashes()}


def _comparison(overlapping: float | None, nonoverlap: float | None) -> dict[str, Any]:
    return {"overlapping_value": overlapping, "nonoverlap_median_value": nonoverlap,
            "absolute_difference": round(abs(overlapping - nonoverlap), 6) if overlapping is not None and nonoverlap is not None else None,
            "same_sign": (overlapping == 0 and nonoverlap == 0) or (overlapping is not None and nonoverlap is not None and overlapping * nonoverlap > 0)}


def audit_v2(data: dict[str, Any]) -> dict[str, Any]:
    evidence, targets, phase3 = load(); expected = build(evidence, targets, phase3)
    errors = {"natural_month_cohort_violation_count": 0, "cohort_rule_violation_count": 0, "overlapping_origin_violation_count": 0, "cohort_spacing_violation_count": 0, "origin_membership_violation_count": 0, "candidate_scope_violation_count": 0, "feature_scope_violation_count": 0, "schema_violation_count": 0, "schema_metadata_violation_count": 0, "hierarchy_structure_violation_count": 0, "readiness_rule_violation_count": 0, "target_availability_violation_count": 0, "sample_alignment_violation_count": 0, "correlation_formula_violation_count": 0, "continuous_formula_violation_count": 0, "boolean_formula_violation_count": 0, "stability_summary_violation_count": 0, "stability_formula_violation_count": 0, "overlap_comparison_violation_count": 0, "era_boundary_violation_count": 0, "research_boundary_violation_count": 0, "source_mutation_count": 0, "upstream_mutation_count": 0, "upstream_audit_gate_violation_count": 0, "forbidden_output_violation_count": 0}
    if any(data.get(k) != expected.get(k) for k in ("source_evidence_sha", "source_evaluation_sha", "source_phase3_sha", "source_phase4_sha")): errors["source_mutation_count"] += 1
    if data.get("cohort_rule") != "calendar_month_index = year*12 + month; cohort = calendar_month_index % horizon": errors["natural_month_cohort_violation_count"] += 1; errors["cohort_rule_violation_count"] += 1
    if data.get("eras") != ERAS: errors["era_boundary_violation_count"] += 1
    all_paths = set(evidence["records"][-1]["features"])
    formal = {p for p, f in evidence["records"][-1]["features"].items() if f.get("model_candidate")}
    actual = set(data.get("features", {})); scope_error = len(actual - formal) + len(formal - actual); errors["candidate_scope_violation_count"] += scope_error; errors["feature_scope_violation_count"] += scope_error
    metadata_error = int(data.get("feature_count") != len(all_paths) or data.get("candidate_feature_count") != len(formal) or len(actual) != len(formal) or data.get("horizons_months") != list(HORIZONS))
    errors["schema_violation_count"] += metadata_error
    errors["schema_metadata_violation_count"] += metadata_error
    errors["research_boundary_violation_count"] += int(data.get("research_only") is not True or data.get("uses_future_information") is not True)
    if [r["month"] for r in evidence["records"]] != [r["month"] for r in targets["records"]]: errors["sample_alignment_violation_count"] += 1
    def forbidden(value: Any) -> int:
        if isinstance(value, dict):
            return sum((1 if str(k).lower() in FORBIDDEN_OUTPUT_KEYS else 0) + forbidden(v) for k, v in value.items())
        if isinstance(value, list): return sum(forbidden(v) for v in value)
        return 0
    errors["forbidden_output_violation_count"] = forbidden(data)
    for path in formal:
        feature = data.get("features", {}).get(path)
        if not feature: continue
        expected_feature = expected["features"][path]
        actual_horizons = set(feature.get("horizons", {}))
        expected_horizon_keys = set(expected_feature["horizons"])
        if actual_horizons != expected_horizon_keys:
            errors["hierarchy_structure_violation_count"] += 1
        for key in sorted(actual_horizons & expected_horizon_keys):
            horizon = feature["horizons"][key]
            h = int(key.split("_")[1][:-1]); cohorts = horizon.get("cohorts", {})
            expected_horizon = expected_feature["horizons"][key]
            expected_origins = expected_horizon["cohorts"]
            expected_cohort_keys = set(expected_origins)
            if set(cohorts) != expected_cohort_keys:
                errors["hierarchy_structure_violation_count"] += 1
            for cohort_id in sorted(set(cohorts) & expected_cohort_keys):
                item = cohorts[cohort_id]
                months = item.get("origin_months", [])
                if any(month_index(m) % h != int(cohort_id.split("_")[1]) for m in months): errors["natural_month_cohort_violation_count"] += 1
                if any(month_index(b) - month_index(a) < h for a, b in zip(months, months[1:])): errors["overlapping_origin_violation_count"] += 1; errors["cohort_spacing_violation_count"] += 1
                if months != expected_origins.get(cohort_id, {}).get("origin_months", []):
                    errors["origin_membership_violation_count"] += 1
                    extra = set(months) - set(expected_origins.get(cohort_id, {}).get("origin_months", []))
                    for month in extra:
                        row = next((r for r in targets.get("records", []) if r["month"] == month), None)
                        target_item = row["benchmarks"]["broad_proxy"].get(key) if row else None
                        if not target_item or not target_item.get("target_available"): errors["target_availability_violation_count"] += 1
                        else: errors["readiness_rule_violation_count"] += 1
                if feature.get("feature_type") == "boolean":
                    if "boolean" not in item or item.get("boolean") != expected_origins.get(cohort_id, {}).get("boolean"): errors["boolean_formula_violation_count"] += 1
                elif "continuous" not in item or item.get("continuous") != expected_origins.get(cohort_id, {}).get("continuous"):
                    errors["correlation_formula_violation_count"] += 1; errors["continuous_formula_violation_count"] += 1
            if horizon.get("stability") != expected_horizon.get("stability"): errors["stability_summary_violation_count"] += 1; errors["stability_formula_violation_count"] += 1
            if horizon.get("overlap_comparison") != expected_horizon.get("overlap_comparison"): errors["overlap_comparison_violation_count"] += 1
    source_ok = (data.get("source_evidence_sha") == canonical_sha(evidence) and data.get("source_evaluation_sha") == canonical_sha(targets) and data.get("source_phase3_sha") == canonical_sha(phase3) and data.get("source_phase4_sha") == canonical_sha(json.loads(W.read_text(encoding="utf-8"))))
    upstream_passed = all(json.loads(p.read_text(encoding="utf-8")).get("passed") is True for p in (EA, TA, DA, WA))
    if not upstream_passed: errors["upstream_audit_gate_violation_count"] += 1
    current_upstream = upstream_file_hashes()
    if data.get("upstream_file_sha256") != current_upstream: errors["upstream_mutation_count"] += 1
    upstream_hash_match = all(p.exists() for p in UPSTREAM_FILES) and source_ok and data.get("upstream_file_sha256") == current_upstream
    return {"schema": "cycle_engine_nonoverlap_diagnostics_audit_v1", "feature_count": len(evidence["records"][-1]["features"]), "candidate_feature_count": len(formal), "upstream_hash_match": upstream_hash_match, "upstream_audits_passed": upstream_passed, **errors, "passed": data.get("research_only") is True and data.get("uses_future_information") is True and upstream_hash_match and upstream_passed and not any(errors.values())}


def audit(data: dict[str, Any]) -> dict[str, Any]:
    return audit_v2(data)


def generate() -> None:
    evidence, targets, phase3 = load(); data = build(evidence, targets, phase3); result = audit(data)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); AUD.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--generate", action="store_true"); parser.parse_args(); generate()
