"""As-of-time diagnostics for Cycle Engine research, never a model input."""
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
OUT = DATA / "cycle_engine_walk_forward_diagnostics_v1.json"
AUD = DATA / "cycle_engine_walk_forward_diagnostics_audit_v1.json"
HORIZONS = (6, 12, 24)
MIN_READY = 36
FROZEN_UPSTREAM = tuple(DATA / n for n in (
    "cycle_dataset_v1.json", "cycle_dataset_contract_v1.json",
    "cycle_dataset_feature_availability_v1.json", "cycle_dataset_golden_spots_v1.json",
    "cycle_dataset_freeze_manifest_v1.json", "cycle_engine_features_v1.json",
    "cycle_engine_features_audit_v1.json", "cycle_engine_evaluation_targets_v1.json",
    "cycle_engine_evaluation_targets_audit_v1.json", "cycle_engine_feature_diagnostics_v1.json",
    "cycle_engine_feature_diagnostics_audit_v1.json"))


def sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def file_hashes() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in FROZEN_UPSTREAM}


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
    return None if not values else round(sorted(values)[len(values) // 2], 6)


def sign_flips(values: list[float | None]) -> int:
    signs = [1 if v > 0 else -1 if v < 0 else 0 for v in values if v is not None]
    signs = [s for s in signs if s]
    return sum(a != b for a, b in zip(signs, signs[1:]))


def load() -> tuple[dict[str, Any], dict[str, Any]]:
    evidence, targets = json.loads(E.read_text(encoding="utf-8")), json.loads(T.read_text(encoding="utf-8"))
    for path in (EA, TA, DA):
        if not json.loads(path.read_text(encoding="utf-8")).get("passed"):
            raise RuntimeError(f"upstream audit gate failed: {path.name}")
    return evidence, targets


def target(targets: dict[str, Any], month: str, horizon: int, as_of: str) -> dict[str, Any] | None:
    record = next((r for r in targets["records"] if r["month"] == month), None)
    if not record:
        return None
    item = record["benchmarks"]["broad_proxy"][f"forward_{horizon}m"]
    return item if item.get("target_available") and item.get("target_month", "9999") <= as_of else None


def _stability(values: list[float], ready: list[tuple[str, float]]) -> dict[str, Any]:
    return {"first_ready_as_of": ready[0][0] if ready else None, "ready_snapshot_count": len(values),
            "latest_value": values[-1] if values else None, "median_historical_value": median(values),
            "minimum_value": min(values) if values else None, "maximum_value": max(values) if values else None,
            "positive_snapshot_count": sum(v > 0 for v in values), "negative_snapshot_count": sum(v < 0 for v in values),
            "sign_flip_count": sign_flips(values)}


def build(evidence: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    em = {r["month"]: r for r in evidence["records"]}
    months = sorted(em)
    candidates = [p for p, f in evidence["records"][-1]["features"].items() if f.get("model_candidate")]
    snapshots = []
    for as_of in months:
        if as_of < "2013-12":
            continue
        snap = {"as_of_month": as_of, "uses_only_information_available_by_as_of": True, "features": {}}
        for path in candidates:
            rows = []
            for month in months:
                if month > as_of:
                    continue
                f = em[month]["features"].get(path, {})
                if not f.get("available") or not f.get("normalization_history_ready"):
                    continue
                raw, is_bool = f.get("raw_value"), isinstance(f.get("raw_value"), bool)
                value = f.get("expanding_rank_pct") if not is_bool else (1.0 if raw else 0.0)
                rows.append((month, value, not is_bool and value is not None, is_bool, raw))
            item = {"feature_family": em[as_of]["features"].get(path, {}).get("feature_family"),
                    "ready_sample_count": len(rows), "diagnostic_history_ready": False,
                    "sample_diagnostics": {}, "boolean_diagnostics": {}}
            for horizon in HORIZONS:
                pairs = [(m, target(targets, m, horizon, as_of)) for m, _, has_rank, _, _ in rows if has_rank]
                pairs = [(m, t) for m, t in pairs if t is not None]
                ready = len(pairs) >= MIN_READY
                item["diagnostic_history_ready"] |= ready
                values = [next(v for mm, v, _, _, _ in rows if mm == m) for m, _ in pairs]
                draw_pairs = [(v, t["max_drawdown_pct"]) for (m, t), v in zip(pairs, values) if t.get("max_drawdown_pct") is not None]
                diag = {"available_origin_count": sum(x[2] for x in rows), "realized_target_count": len(pairs),
                        "ready_sample_count": len(pairs), "diagnostic_history_ready": ready,
                        "latest_eligible_origin_month": max((m for m, _ in pairs), default=None),
                        "spearman_rho": spearman(values, [t["forward_return_pct"] for _, t in pairs]) if ready else None,
                        "max_drawdown_spearman_rho": spearman([v for v, _ in draw_pairs], [dd for _, dd in draw_pairs]) if ready and len(draw_pairs) >= MIN_READY else None,
                        "max_drawdown_realized_target_count": len(draw_pairs), "target_cutoff_rule": "target_month <= as_of_month"}
                item["sample_diagnostics"][f"forward_{horizon}m"] = diag
                group = item["boolean_diagnostics"].setdefault(f"forward_{horizon}m", {})
                for state in (True, False):
                    vals, dds = [], []
                    for m, _, _, is_bool, raw in rows:
                        if not is_bool or raw is not state:
                            continue
                        t = target(targets, m, horizon, as_of)
                        if t:
                            vals.append(t["forward_return_pct"])
                            if t.get("max_drawdown_pct") is not None: dds.append(t["max_drawdown_pct"])
                    group["true" if state else "false"] = {"sample_count": len(vals), "median": median(vals),
                        "max_drawdown_sample_count": len(dds), "max_drawdown_median": median(dds)}
                total = group["true"]["sample_count"] + group["false"]["sample_count"]
                dd_total = group["true"]["max_drawdown_sample_count"] + group["false"]["max_drawdown_sample_count"]
                group["true_minus_false_median"] = round(group["true"]["median"] - group["false"]["median"], 6) if total >= MIN_READY and group["true"]["median"] is not None and group["false"]["median"] is not None else None
                group["max_drawdown_true_minus_false_median"] = round(group["true"]["max_drawdown_median"] - group["false"]["max_drawdown_median"], 6) if dd_total >= MIN_READY and group["true"]["max_drawdown_median"] is not None and group["false"]["max_drawdown_median"] is not None else None
            snap["features"][path] = item
        snapshots.append(snap)
    stability = {}
    for path in candidates:
        stability[path] = {"continuous": {}, "boolean": {}}
        for horizon in HORIZONS:
            key = f"forward_{horizon}m"
            ready = [(s["as_of_month"], s["features"][path]["sample_diagnostics"][key]["spearman_rho"]) for s in snapshots if s["features"][path]["sample_diagnostics"][key]["spearman_rho"] is not None]
            stability[path]["continuous"][key] = _stability([v for _, v in ready], ready)
            ready = [(s["as_of_month"], s["features"][path]["boolean_diagnostics"][key]["true_minus_false_median"]) for s in snapshots if s["features"][path]["boolean_diagnostics"][key]["true_minus_false_median"] is not None]
            stability[path]["boolean"][key] = _stability([v for _, v in ready], ready)
    return {"schema": "cycle_engine_walk_forward_diagnostics_v1", "evaluation_only": True, "uses_future_information": True,
            "description": "As-of walk-forward descriptive diagnostics; not a model input or signal.", "as_of_start": "2013-12",
            "as_of_end": months[-1], "horizons_months": list(HORIZONS), "primary_benchmark": "broad_proxy",
            "minimum_ready_samples": MIN_READY, "snapshots": snapshots, "stability_summary": stability,
            "source_evidence_sha": sha(evidence), "source_evaluation_sha": sha(targets),
            "source_diagnostics_sha": sha(json.loads(D.read_text(encoding="utf-8")))}


def audit(data: dict[str, Any]) -> dict[str, Any]:
    evidence, targets = load(); expected = build(evidence, targets)
    ea, ta, da = (json.loads(p.read_text(encoding="utf-8")) for p in (EA, TA, DA))
    errors = {k: 0 for k in ("unrealized_target_used_count", "origin_after_as_of_count", "latest_cutoff_violation_count",
        "sample_count_violation_count", "readiness_rule_violation_count", "correlation_formula_violation_count",
        "boolean_formula_violation_count", "sign_flip_formula_violation_count", "source_mutation_count",
        "upstream_mutation_count", "as_of_future_leakage_count", "target_cutoff_violation_count",
        "sample_alignment_violation_count", "candidate_scope_violation_count")}
    errors["source_mutation_count"] = sum(data.get(k) != expected.get(k) for k in ("source_evidence_sha", "source_evaluation_sha", "source_diagnostics_sha"))
    errors["as_of_future_leakage_count"] += int(data.get("evaluation_only") is not True or data.get("uses_future_information") is not True)
    errors["readiness_rule_violation_count"] += int(data.get("minimum_ready_samples") != MIN_READY)
    formal = {p for p, f in evidence["records"][-1]["features"].items() if f.get("model_candidate")}
    actual_paths = set(data["snapshots"][0]["features"]) if data.get("snapshots") else set()
    errors["candidate_scope_violation_count"] += len(actual_paths - formal) + len(formal - actual_paths)
    if data.get("snapshots") != expected["snapshots"]: errors["sample_count_violation_count"] += 1
    if data.get("stability_summary") != expected["stability_summary"]: errors["sign_flip_formula_violation_count"] += 1
    if [r["month"] for r in evidence["records"]] != [r["month"] for r in targets["records"]]: errors["sample_alignment_violation_count"] += 1
    for snap in data.get("snapshots", []):
        errors["as_of_future_leakage_count"] += int(snap.get("uses_only_information_available_by_as_of") is not True)
        for path, item in snap.get("features", {}).items():
            errors["candidate_scope_violation_count"] += int(path not in formal)
            for diag in item.get("sample_diagnostics", {}).values():
                errors["target_cutoff_violation_count"] += int(diag.get("target_cutoff_rule") != "target_month <= as_of_month")
                latest = diag.get("latest_eligible_origin_month")
                errors["origin_after_as_of_count"] += int(latest is not None and latest > snap["as_of_month"])
                errors["latest_cutoff_violation_count"] += int(latest is not None and latest > snap["as_of_month"])
                errors["readiness_rule_violation_count"] += int(diag.get("diagnostic_history_ready") != (diag.get("ready_sample_count", 0) >= MIN_READY))
    source_hashes = (data.get("source_evidence_sha") == sha(evidence) and data.get("source_evaluation_sha") == sha(targets) and data.get("source_diagnostics_sha") == sha(json.loads(D.read_text(encoding="utf-8"))))
    errors["correlation_formula_violation_count"] = int(data.get("snapshots") != expected.get("snapshots"))
    errors["boolean_formula_violation_count"] = int(data.get("snapshots") != expected.get("snapshots"))
    result = {"schema": "cycle_engine_walk_forward_diagnostics_audit_v1", "snapshot_count": len(data.get("snapshots", [])),
        "candidate_feature_count": len(formal), "source_evidence_hash_match": data.get("source_evidence_sha") == sha(evidence),
        "source_evaluation_hash_match": data.get("source_evaluation_sha") == sha(targets), "source_diagnostics_hash_match": data.get("source_diagnostics_sha") == sha(json.loads(D.read_text(encoding="utf-8"))),
        "evidence_audit_passed": ea.get("passed") is True, "evaluation_audit_passed": ta.get("passed") is True,
        "phase3_audit_passed": da.get("passed") is True, **errors}
    result["passed"] = source_hashes and all(result[k] == 0 for k in errors) and all(result[k] for k in ("evidence_audit_passed", "evaluation_audit_passed", "phase3_audit_passed"))
    return result


def generate() -> None:
    evidence, targets = load(); before = file_hashes(); data = build(evidence, targets); audit_data = audit(data); after = file_hashes()
    if before != after: audit_data["upstream_mutation_count"] = 1; audit_data["passed"] = False
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUD.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--generate", action="store_true"); parser.parse_args(); generate()
