"""Research-only historical diagnostics for the frozen Cycle Engine domains.

This module describes historical behaviour.  It never changes Domain rules and
never emits a score, regime, allocation, position, or trading signal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PHASE2_PATH = DATA / "cycle_engine_domain_signals_v1.json"
PHASE2_AUDIT_PATH = DATA / "cycle_engine_domain_signals_audit_v1.json"
TARGETS_PATH = DATA / "cycle_engine_evaluation_targets_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_domain_diagnostics_v1.json"
AUDIT_PATH = DATA / "cycle_engine_domain_diagnostics_audit_v1.json"
FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 = "f204c5798bb96c4b0a0b28edfec2914496c908ae17ff9b7832e5400ced69f326"
HORIZONS = (6, 12, 24)
CORE = ("valuation", "earnings", "macro_confirmation", "trend")
DOMAINS = CORE + ("sentiment_overlay",)
FORBIDDEN_KEYS = {"cycle_score", "bull_bear_score", "market_score", "cycle_state", "regime", "recommended_position", "equity_position", "allocation", "buy_signal", "sell_signal", "etf_recommendation", "state_machine"}
WINDOWS = {"2012_2013": ("2012-01", "2013-12"), "2014_2015": ("2014-01", "2015-12"), "2018": ("2018-01", "2018-12"), "2020_2021": ("2020-01", "2021-12"), "2022": ("2022-01", "2022-12"), "2024": ("2024-01", "2024-12"), "2026": ("2026-01", "2026-08")}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha256_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())


def month_index(month: str) -> int:
    year, mon = (int(x) for x in month.split("-"))
    return year * 12 + mon


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 6)


def load_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    phase2 = json.loads(PHASE2_PATH.read_text(encoding="utf-8"))
    phase2_audit = json.loads(PHASE2_AUDIT_PATH.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    if sha256_bytes(PHASE2_PATH.read_bytes()) != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256:
        raise RuntimeError("frozen Phase 2 Domain Signals hash gate failed")
    if phase2_audit.get("passed") is not True:
        raise RuntimeError("Phase 2 Domain Signals audit did not pass")
    return phase2, phase2_audit, targets


def state(record: dict[str, Any], domain: str) -> str:
    return record[domain]["state"]


def ready(record: dict[str, Any], domain: str) -> bool:
    section = record[domain]
    return section.get("model_ready", False) if domain == "sentiment_overlay" else section.get("ready") is True


def run_lengths(values: list[str]) -> list[int]:
    result: list[int] = []
    previous = None
    length = 0
    for value in values:
        if value == previous:
            length += 1
        else:
            if length:
                result.append(length)
            previous, length = value, 1
    if length:
        result.append(length)
    return result


def target_run_lengths(values: list[str], target: str) -> list[int]:
    return run_lengths([value if value == target else "__other__" for value in values])


def state_distribution(records: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    selected = [record for record in records if ready(record, domain)]
    values = [state(record, domain) for record in selected]
    result: dict[str, Any] = {}
    for value, count in sorted(Counter(values).items()):
        state_runs = [length for length in target_run_lengths(values, value) if length]
        months = [record["month"] for record in selected if state(record, domain) == value]
        result[value] = {"month_count": count, "percentage_of_ready_months": round(count / len(selected) * 100, 6) if selected else 0.0, "first_month": min(months) if months else None, "last_month": max(months) if months else None, "longest_consecutive_run": max(state_runs, default=0), "median_run_length": median([float(item) for item in state_runs])}
    return {"ready_month_count": len(selected), "states": result}


def coverage(records: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    ready_months = [record["month"] for record in records if ready(record, domain)]
    unavailable = [record["month"] for record in records if state(record, domain) == "unavailable"]
    insufficient = [record["month"] for record in records if state(record, domain) == "insufficient_history" or (domain == "sentiment_overlay" and not ready(record, domain) and state(record, domain) != "unavailable")]
    return {"first_ready_month": min(ready_months) if ready_months else None, "ready_month_count": len(ready_months), "ready_pct": round(len(ready_months) / len(records) * 100, 6) if records else 0.0, "unavailable_month_count": len(unavailable), "insufficient_history_month_count": len(insufficient)}


def transitions(records: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    selected = [record for record in records if ready(record, domain)]
    counts: Counter[str] = Counter(f"{state(a, domain)}->{state(b, domain)}" for a, b in zip(selected, selected[1:]))
    outgoing: Counter[str] = Counter()
    for key, value in counts.items():
        outgoing[key.split("->")[0]] += value
    matrix = {key: {"transition_count": value, "transition_probability": round(value / outgoing[key.split("->")[0]] * 100, 6)} for key, value in sorted(counts.items())}
    changes = sum(a != b for a, b in zip([state(r, domain) for r in selected], [state(r, domain) for r in selected[1:]]))
    durations = run_lengths([state(r, domain) for r in selected])
    return {"transition_matrix": matrix, "self_transition_probability": round(sum(value for key, value in counts.items() if key.split("->")[0] == key.split("->")[1]) / sum(counts.values()) * 100, 6) if counts else None, "monthly_state_change_rate": round(changes / (len(selected) - 1) * 100, 6) if len(selected) > 1 else None, "median_state_duration_months": median([float(item) for item in durations])}


def combinations(records: list[dict[str, Any]]) -> dict[str, Any]:
    specs = (("valuation_x_earnings", ("valuation", "earnings")), ("valuation_x_trend", ("valuation", "trend")), ("earnings_x_trend", ("earnings", "trend")), ("earnings_x_macro", ("earnings", "macro_confirmation")), ("valuation_x_earnings_x_trend", ("valuation", "earnings", "trend")))
    output = {}
    for name, domains in specs:
        counts: Counter[str] = Counter(" x ".join(state(record, domain) for domain in domains) for record in records if all(ready(record, domain) for domain in domains))
        output[name] = {"combinations": {key: {"month_count": value, "first_month": min(record["month"] for record in records if " x ".join(state(record, domain) for domain in domains) == key and all(ready(record, domain) for domain in domains)), "last_month": max(record["month"] for record in records if " x ".join(state(record, domain) for domain in domains) == key and all(ready(record, domain) for domain in domains))} for key, value in sorted(counts.items())}, "top_20": [list(item) for item in counts.most_common(20)], "rare_1_or_2": sorted(key for key, value in counts.items() if value <= 2)}
    return output


def conflicts(records: list[dict[str, Any]]) -> dict[str, Any]:
    rules = {"valuation_cheap_damaged": lambda r: state(r, "valuation") == "cheap" and state(r, "trend") == "damaged", "valuation_expensive_up": lambda r: state(r, "valuation") == "expensive" and state(r, "trend") in ("up", "extended"), "earnings_deterioration_up": lambda r: state(r, "earnings") == "deterioration" and state(r, "trend") in ("up", "extended"), "earnings_recovery_damaged": lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "trend") == "damaged", "earnings_recovery_macro_negative": lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "macro_confirmation") == "negative", "earnings_deterioration_macro_positive": lambda r: state(r, "earnings") == "deterioration" and state(r, "macro_confirmation") == "positive"}
    result = {}
    for name, predicate in rules.items():
        months = [record["month"] for record in records if all(ready(record, domain) for domain in CORE) and predicate(record)]
        result[name] = {"occurrence_count": len(months), "months": months, "longest_duration": max(target_run_lengths(["hit" if month in months else "miss" for month in [record["month"] for record in records]], "hit"), default=0)}
    return result


def target_metric(target: dict[str, Any], benchmark: str, horizon: int) -> dict[str, Any] | None:
    item = target.get("benchmarks", {}).get(benchmark, {}).get(f"forward_{horizon}m")
    return item if item and item.get("target_available") else None


def evaluation(records: list[dict[str, Any]], targets: dict[str, Any]) -> dict[str, Any]:
    target_map = {record["month"]: record for record in targets["records"]}
    output: dict[str, Any] = {"research_only": True, "uses_future_information": True, "cohort_rule": "calendar_month_index % horizon; each cohort is evaluated independently", "benchmarks": {}}
    for benchmark in ("csi300", "csi500"):
        output["benchmarks"][benchmark] = {}
        for horizon in HORIZONS:
            domains_out: dict[str, Any] = {}
            for domain in CORE:
                by_state: dict[str, dict[int, list[tuple[str, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
                for cohort in range(horizon):
                    cohort_rows = [(record, target_metric(target_map.get(record["month"], {}), benchmark, horizon)) for record in records if ready(record, domain) and month_index(record["month"]) % horizon == cohort]
                    cohort_rows = [(record, target) for record, target in cohort_rows if target is not None]
                    for record, target in cohort_rows:
                        by_state[state(record, domain)][cohort].append((record["month"], target))
                state_out = {}
                for value, cohorts in sorted(by_state.items()):
                    points = [point for cohort_points in cohorts.values() for point in cohort_points]
                    returns = [float(target["forward_return_pct"]) for _, target in points if target.get("forward_return_pct") is not None]
                    drawdowns = [float(target["max_drawdown_pct"]) for _, target in points if target.get("max_drawdown_pct") is not None]
                    cohort_means = [statistics.mean(float(target["forward_return_pct"]) for _, target in cohort_points if target.get("forward_return_pct") is not None) for cohort_points in cohorts.values() if any(target.get("forward_return_pct") is not None for _, target in cohort_points)]
                    cohort_medians = [median([float(target["forward_return_pct"]) for _, target in cohort_points if target.get("forward_return_pct") is not None]) for cohort_points in cohorts.values()]
                    cohort_win_rates = [sum(float(target["forward_return_pct"]) > 0 for _, target in cohort_points if target.get("forward_return_pct") is not None) / len([target for _, target in cohort_points if target.get("forward_return_pct") is not None]) * 100 for cohort_points in cohorts.values() if any(target.get("forward_return_pct") is not None for _, target in cohort_points)]
                    state_out[value] = {"sample_count": len(returns), "cohort_count": len(cohorts), "mean_forward_return": round(statistics.mean(cohort_means), 6) if cohort_means else None, "median_forward_return": median([value for value in cohort_medians if value is not None]), "win_rate": round(statistics.mean(cohort_win_rates), 6) if cohort_win_rates else None, "q25": percentile([value for value in cohort_medians if value is not None], .25), "q75": percentile([value for value in cohort_medians if value is not None], .75), "median_future_max_drawdown": median(drawdowns), "worst_future_max_drawdown": min(drawdowns) if drawdowns else None, "small_sample": len(returns) < 12, "origin_months": [month for month, _ in points], "cohort_summaries": {str(cohort): {"sample_count": len(cohort_points), "origin_months": [month for month, _ in cohort_points]} for cohort, cohort_points in sorted(cohorts.items())}}
                domains_out[domain] = state_out
            output["benchmarks"][benchmark][f"forward_{horizon}m"] = domains_out
    return output


def build(phase2: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    records = phase2["records"]
    domain_distributions = {domain: state_distribution(records, domain) for domain in DOMAINS}
    domain_coverage = {domain: coverage(records, domain) for domain in DOMAINS}
    domain_transitions = {domain: transitions(records, domain) for domain in CORE}
    timeline = [{"month": r["month"], "valuation": state(r, "valuation"), "earnings": state(r, "earnings"), "macro_confirmation": state(r, "macro_confirmation"), "trend": state(r, "trend"), "a_fear_state": state(r, "sentiment_overlay"), "a_fear_model_ready": r["sentiment_overlay"].get("model_ready") is True} for r in records]
    window_extracts = {name: [item for item in timeline if start <= item["month"] <= end] for name, (start, end) in WINDOWS.items()}
    distribution_summary = {domain: domain_distributions[domain]["states"] for domain in DOMAINS}
    phase3_evidence = {"valuation_state_distribution": distribution_summary["valuation"], "earnings_state_distribution": distribution_summary["earnings"], "trend_state_distribution": distribution_summary["trend"], "macro_state_distribution": distribution_summary["macro_confirmation"], "domain_change_rates": {domain: domain_transitions[domain]["monthly_state_change_rate"] for domain in CORE}, "median_state_durations": {domain: domain_transitions[domain]["median_state_duration_months"] for domain in CORE}, "most_common_combinations": combinations(records), "major_conflicts": conflicts(records), "state_forward_return_summary": {}, "state_sample_sizes": {}, "insufficient_sample_flags": {}}
    return {"schema": "cycle_engine_domain_diagnostics_v1", "description": "Research-only historical diagnostics for frozen Phase 2 Domain Signals; no model rule changes.", "research_only": True, "uses_future_information": True, "source_phase2_sha256": sha256_bytes(PHASE2_PATH.read_bytes()), "source_phase2_audit_sha256": canonical_sha(json.loads(PHASE2_AUDIT_PATH.read_text(encoding="utf-8"))), "source_evaluation_sha256": canonical_sha(targets), "record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "coverage": domain_coverage, "state_distribution": domain_distributions, "transitions": domain_transitions, "combinations": combinations(records), "conflicts": conflicts(records), "timeline": timeline, "window_extracts": window_extracts, "evaluation": evaluation(records, targets), "phase3_design_evidence": phase3_evidence}


def forbidden(value: Any) -> int:
    if isinstance(value, dict):
        return sum((1 if str(key).lower() in FORBIDDEN_KEYS else 0) + forbidden(child) for key, child in value.items())
    if isinstance(value, list):
        return sum(forbidden(child) for child in value)
    return 0


def audit(data: dict[str, Any], phase2: dict[str, Any] | None = None, phase2_audit: dict[str, Any] | None = None, targets: dict[str, Any] | None = None) -> dict[str, Any]:
    if phase2 is None:
        phase2, phase2_audit, targets = load_sources()
    assert phase2_audit is not None and targets is not None
    expected = build(phase2, targets)
    errors = {name: 0 for name in ("source_phase2_audit_violation_count", "source_phase2_hash_violation_count", "record_alignment_violation_count", "readiness_summary_violation_count", "state_distribution_violation_count", "transition_matrix_violation_count", "run_length_violation_count", "combination_count_violation_count", "conflict_diagnostic_violation_count", "evaluation_alignment_violation_count", "nonoverlap_cohort_violation_count", "sample_count_violation_count", "future_data_boundary_violation_count", "production_rule_mutation_count", "forbidden_output_violation_count", "upstream_mutation_count")}
    errors["source_phase2_audit_violation_count"] = int(phase2_audit.get("passed") is not True)
    errors["source_phase2_hash_violation_count"] = int(sha256_bytes(PHASE2_PATH.read_bytes()) != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 or data.get("source_phase2_sha256") != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)
    errors["upstream_mutation_count"] = int(canonical_sha(phase2) != canonical_sha(json.loads(PHASE2_PATH.read_text(encoding="utf-8"))) or phase2_audit.get("passed") is not True)
    errors["record_alignment_violation_count"] = int(data.get("record_count") != len(phase2["records"]) or data.get("start_month") != phase2["records"][0]["month"] or data.get("end_month") != phase2["records"][-1]["month"])
    for section in ("coverage", "state_distribution", "transitions", "combinations", "conflicts", "timeline", "evaluation", "window_extracts", "phase3_design_evidence"):
        key = "readiness_summary_violation_count" if section == "coverage" else ("state_distribution_violation_count" if section == "state_distribution" else ("transition_matrix_violation_count" if section == "transitions" else ("combination_count_violation_count" if section == "combinations" else ("conflict_diagnostic_violation_count" if section == "conflicts" else "evaluation_alignment_violation_count"))))
        if data.get(section) != expected.get(section):
            errors[key] += 1
    for domain in CORE:
        actual = data.get("transitions", {}).get(domain, {})
        if actual.get("median_state_duration_months") != expected["transitions"][domain].get("median_state_duration_months"):
            errors["run_length_violation_count"] += 1
    for benchmark in data.get("evaluation", {}).get("benchmarks", {}).values():
        for horizon_key, horizon in benchmark.items():
            horizon_months = int(horizon_key.split("_")[1][:-1])
            for domain in CORE:
                for values in horizon.get(domain, {}).values():
                    origins = values.get("origin_months", [])
                    if len(origins) != len(set(origins)):
                        errors["nonoverlap_cohort_violation_count"] += 1
                    for cohort in range(horizon_months):
                        cohort_origins = sorted(month for month in origins if month_index(month) % horizon_months == cohort)
                        if any(month_index(b) - month_index(a) < horizon_months for a, b in zip(cohort_origins, cohort_origins[1:])):
                            errors["nonoverlap_cohort_violation_count"] += 1
    errors["future_data_boundary_violation_count"] = int(data.get("research_only") is not True or data.get("uses_future_information") is not True)
    errors["forbidden_output_violation_count"] = forbidden(data)
    errors["production_rule_mutation_count"] = int(data.get("source_phase2_sha256") != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)
    return {"schema": "cycle_engine_domain_diagnostics_audit_v1", "record_count": len(phase2["records"]), **errors, "passed": not any(errors.values())}


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    phase2, phase2_audit, targets = load_sources()
    data = build(phase2, targets)
    result = audit(data, phase2, phase2_audit, targets)
    if not result["passed"]:
        raise RuntimeError("domain diagnostics audit failed: " + json.dumps(result, ensure_ascii=False))
    return data, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.parse_args()
    data, result = generate()
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUDIT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
