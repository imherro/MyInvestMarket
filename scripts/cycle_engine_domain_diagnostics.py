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
    result: list[int] = []
    length = 0
    for value in values:
        if value == target:
            length += 1
        elif length:
            result.append(length)
            length = 0
    if length:
        result.append(length)
    return result


def state_distribution(records: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    descriptive_available = domain == "sentiment_overlay"
    selected = [record for record in records if (record[domain].get("available") is True if descriptive_available else ready(record, domain))]
    values = [state(record, domain) for record in selected]
    result: dict[str, Any] = {}
    for value, count in sorted(Counter(values).items()):
        state_runs = [length for length in target_run_lengths(values, value) if length]
        months = [record["month"] for record in selected if state(record, domain) == value]
        result[value] = {"month_count": count, ("percentage_of_available_months" if descriptive_available else "percentage_of_ready_months"): round(count / len(selected) * 100, 6) if selected else 0.0, "first_month": min(months) if months else None, "last_month": max(months) if months else None, "longest_consecutive_run": max(state_runs, default=0), "median_run_length": median([float(item) for item in state_runs])}
    return {"ready_month_count": 0 if descriptive_available else len(selected), "available_month_count": len(selected) if descriptive_available else None, "model_ready_month_count": sum(ready(record, domain) for record in selected) if descriptive_available else None, "states": result}


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
    rules = {"valuation_cheap_damaged": (("valuation", "trend"), lambda r: state(r, "valuation") == "cheap" and state(r, "trend") == "damaged"), "valuation_expensive_up": (("valuation", "trend"), lambda r: state(r, "valuation") == "expensive" and state(r, "trend") in ("up", "extended")), "earnings_deterioration_up": (("earnings", "trend"), lambda r: state(r, "earnings") == "deterioration" and state(r, "trend") in ("up", "extended")), "earnings_recovery_damaged": (("earnings", "trend"), lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "trend") == "damaged"), "earnings_recovery_macro_negative": (("earnings", "macro_confirmation"), lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "macro_confirmation") == "negative"), "earnings_deterioration_macro_positive": (("earnings", "macro_confirmation"), lambda r: state(r, "earnings") == "deterioration" and state(r, "macro_confirmation") == "positive")}
    result = {}
    for name, (required_domains, predicate) in rules.items():
        months = [record["month"] for record in records if all(ready(record, domain) for domain in required_domains) and predicate(record)]
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
                    cohort_summaries = {}
                    for cohort, cohort_points in sorted(cohorts.items()):
                        cohort_returns = [float(target["forward_return_pct"]) for _, target in cohort_points if target.get("forward_return_pct") is not None]
                        cohort_drawdowns = [float(target["max_drawdown_pct"]) for _, target in cohort_points if target.get("max_drawdown_pct") is not None]
                        cohort_summaries[str(cohort)] = {"sample_count": len(cohort_returns), "mean_forward_return": round(statistics.mean(cohort_returns), 6) if cohort_returns else None, "median_forward_return": median(cohort_returns), "win_rate": round(sum(value > 0 for value in cohort_returns) / len(cohort_returns) * 100, 6) if cohort_returns else None, "q25": percentile(cohort_returns, .25), "q75": percentile(cohort_returns, .75), "median_future_max_drawdown": median(cohort_drawdowns), "worst_future_max_drawdown": min(cohort_drawdowns) if cohort_drawdowns else None, "origin_months": [month for month, _ in cohort_points]}
                    cohort_means = [item["mean_forward_return"] for item in cohort_summaries.values() if item["mean_forward_return"] is not None]
                    cohort_medians = [item["median_forward_return"] for item in cohort_summaries.values() if item["median_forward_return"] is not None]
                    cohort_win_rates = [item["win_rate"] for item in cohort_summaries.values() if item["win_rate"] is not None]
                    cohort_sizes = [item["sample_count"] for item in cohort_summaries.values()]
                    cohort_drawdown_medians = [item["median_future_max_drawdown"] for item in cohort_summaries.values() if item["median_future_max_drawdown"] is not None]
                    state_out[value] = {"aggregation_unit": "cohort", "sample_count": len(returns), "total_origin_count": len(returns), "cohort_count": len(cohorts), "cohort_sample_counts": cohort_sizes, "effective_sample_count": median([float(item) for item in cohort_sizes]), "min_cohort_sample_count": min(cohort_sizes, default=0), "max_cohort_sample_count": max(cohort_sizes, default=0), "mean_of_cohort_mean_forward_return": round(statistics.mean(cohort_means), 6) if cohort_means else None, "median_of_cohort_mean_forward_return": median(cohort_means), "q25_of_cohort_mean_forward_return": percentile(cohort_means, .25), "q75_of_cohort_mean_forward_return": percentile(cohort_means, .75), "mean_of_cohort_win_rate": round(statistics.mean(cohort_win_rates), 6) if cohort_win_rates else None, "median_of_cohort_win_rate": median(cohort_win_rates), "median_of_cohort_median_drawdown": median(cohort_drawdown_medians), "global_worst_origin_drawdown": min(drawdowns) if drawdowns else None, "small_sample": (median([float(item) for item in cohort_sizes]) or 0) < 12, "origin_months": [month for month, _ in points], "cohort_summaries": cohort_summaries}
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
    combinations_out = combinations(records)
    conflicts_out = conflicts(records)
    evaluation_out = evaluation(records, targets)
    state_forward = {benchmark: benchmark_data for benchmark, benchmark_data in evaluation_out["benchmarks"].items()}
    state_sizes = {benchmark: {horizon: {domain: {value: item["sample_count"] for value, item in domain_values.items()} for domain, domain_values in horizon_data.items()} for horizon, horizon_data in benchmark_data.items()} for benchmark, benchmark_data in state_forward.items()}
    insufficient = {benchmark: {horizon: {domain: {value: item["small_sample"] for value, item in domain_values.items()} for domain, domain_values in horizon_data.items()} for horizon, horizon_data in benchmark_data.items()} for benchmark, benchmark_data in state_forward.items()}
    phase3_evidence = {"valuation_state_distribution": distribution_summary["valuation"], "earnings_state_distribution": distribution_summary["earnings"], "trend_state_distribution": distribution_summary["trend"], "macro_state_distribution": distribution_summary["macro_confirmation"], "domain_change_rates": {domain: domain_transitions[domain]["monthly_state_change_rate"] for domain in CORE}, "median_state_durations": {domain: domain_transitions[domain]["median_state_duration_months"] for domain in CORE}, "most_common_combinations": combinations_out, "major_conflicts": conflicts_out, "state_forward_return_summary": state_forward, "state_sample_sizes": state_sizes, "insufficient_sample_flags": insufficient}
    return {"schema": "cycle_engine_domain_diagnostics_v1", "description": "Research-only historical diagnostics for frozen Phase 2 Domain Signals; no model rule changes.", "research_only": True, "uses_future_information": True, "source_phase2_sha256": sha256_bytes(PHASE2_PATH.read_bytes()), "source_phase2_audit_sha256": canonical_sha(json.loads(PHASE2_AUDIT_PATH.read_text(encoding="utf-8"))), "source_evaluation_sha256": canonical_sha(targets), "record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "coverage": domain_coverage, "state_distribution": domain_distributions, "transitions": domain_transitions, "combinations": combinations_out, "conflicts": conflicts_out, "timeline": timeline, "window_extracts": window_extracts, "evaluation": evaluation_out, "phase3_design_evidence": phase3_evidence}


def audit_replay_snapshot(phase2: dict[str, Any]) -> dict[str, Any]:
    def true_runs(values: list[str], target: str) -> list[int]:
        runs: list[int] = []
        current = 0
        for value in values:
            if value == target:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        if current:
            runs.append(current)
        return runs

    records = phase2["records"]
    coverage_out = {}
    distribution_out = {}
    for domain in DOMAINS:
        descriptive = domain == "sentiment_overlay"
        selected = [record for record in records if (record[domain].get("available") is True if descriptive else record[domain].get("ready") is True)]
        values = [record[domain]["state"] for record in selected]
        states = {}
        for value, count in sorted(Counter(values).items()):
            lengths = true_runs(values, value)
            months = [record["month"] for record in selected if record[domain]["state"] == value]
            states[value] = {"month_count": count, ("percentage_of_available_months" if descriptive else "percentage_of_ready_months"): round(count / len(selected) * 100, 6) if selected else 0.0, "first_month": min(months) if months else None, "last_month": max(months) if months else None, "longest_consecutive_run": max(lengths, default=0), "median_run_length": median([float(length) for length in lengths])}
        coverage_out[domain] = {"first_ready_month": min([record["month"] for record in records if ready(record, domain)], default=None), "ready_month_count": sum(ready(record, domain) for record in records), "ready_pct": round(sum(ready(record, domain) for record in records) / len(records) * 100, 6), "unavailable_month_count": sum(record[domain]["state"] == "unavailable" for record in records), "insufficient_history_month_count": sum(record[domain]["state"] == "insufficient_history" or (descriptive and not ready(record, domain) and record[domain]["state"] != "unavailable") for record in records)}
        distribution_out[domain] = {"ready_month_count": 0 if descriptive else len(selected), "available_month_count": len(selected) if descriptive else None, "model_ready_month_count": sum(ready(record, domain) for record in selected) if descriptive else None, "states": states}
    transition_out = {}
    for domain in CORE:
        selected = [record for record in records if ready(record, domain)]
        values = [record[domain]["state"] for record in selected]
        counts = Counter(f"{a}->{b}" for a, b in zip(values, values[1:]))
        outgoing = Counter(key.split("->")[0] for key in counts for _ in range(counts[key]))
        matrix = {key: {"transition_count": count, "transition_probability": round(count / outgoing[key.split("->")[0]] * 100, 6)} for key, count in sorted(counts.items())}
        durations = run_lengths(values)
        transition_out[domain] = {"transition_matrix": matrix, "self_transition_probability": round(sum(count for key, count in counts.items() if key.split("->")[0] == key.split("->")[1]) / sum(counts.values()) * 100, 6) if counts else None, "monthly_state_change_rate": round(sum(a != b for a, b in zip(values, values[1:])) / (len(values) - 1) * 100, 6) if len(values) > 1 else None, "median_state_duration_months": median([float(length) for length in durations])}
    specs = (("valuation_x_earnings", ("valuation", "earnings")), ("valuation_x_trend", ("valuation", "trend")), ("earnings_x_trend", ("earnings", "trend")), ("earnings_x_macro", ("earnings", "macro_confirmation")), ("valuation_x_earnings_x_trend", ("valuation", "earnings", "trend")))
    combinations_out = {}
    for name, domains in specs:
        points = [record for record in records if all(ready(record, domain) for domain in domains)]
        counts = Counter(" x ".join(record[domain]["state"] for domain in domains) for record in points)
        combinations_out[name] = {"combinations": {key: {"month_count": count, "first_month": min(record["month"] for record in points if " x ".join(record[domain]["state"] for domain in domains) == key), "last_month": max(record["month"] for record in points if " x ".join(record[domain]["state"] for domain in domains) == key)} for key, count in sorted(counts.items())}, "top_20": [list(item) for item in counts.most_common(20)], "rare_1_or_2": sorted(key for key, count in counts.items() if count <= 2)}
    rules = {"valuation_cheap_damaged": (("valuation", "trend"), lambda r: state(r, "valuation") == "cheap" and state(r, "trend") == "damaged"), "valuation_expensive_up": (("valuation", "trend"), lambda r: state(r, "valuation") == "expensive" and state(r, "trend") in ("up", "extended")), "earnings_deterioration_up": (("earnings", "trend"), lambda r: state(r, "earnings") == "deterioration" and state(r, "trend") in ("up", "extended")), "earnings_recovery_damaged": (("earnings", "trend"), lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "trend") == "damaged"), "earnings_recovery_macro_negative": (("earnings", "macro_confirmation"), lambda r: state(r, "earnings") in ("recovery", "expansion") and state(r, "macro_confirmation") == "negative"), "earnings_deterioration_macro_positive": (("earnings", "macro_confirmation"), lambda r: state(r, "earnings") == "deterioration" and state(r, "macro_confirmation") == "positive")}
    conflicts_out = {}
    for name, (required, predicate) in rules.items():
        months = [record["month"] for record in records if all(ready(record, domain) for domain in required) and predicate(record)]
        hits = ["hit" if record["month"] in months else "miss" for record in records]
        conflicts_out[name] = {"occurrence_count": len(months), "months": months, "longest_duration": max(true_runs(hits, "hit"), default=0)}
    timeline = [{"month": record["month"], "valuation": state(record, "valuation"), "earnings": state(record, "earnings"), "macro_confirmation": state(record, "macro_confirmation"), "trend": state(record, "trend"), "a_fear_state": state(record, "sentiment_overlay"), "a_fear_model_ready": record["sentiment_overlay"].get("model_ready") is True} for record in records]
    windows = {name: [item for item in timeline if start <= item["month"] <= end] for name, (start, end) in WINDOWS.items()}
    return {"coverage": coverage_out, "state_distribution": distribution_out, "transitions": transition_out, "combinations": combinations_out, "conflicts": conflicts_out, "timeline": timeline, "window_extracts": windows}


def audit_replay_evaluation(data: dict[str, Any], phase2: dict[str, Any], targets: dict[str, Any]) -> tuple[int, int]:
    target_map = {record["month"]: record for record in targets["records"]}
    alignment_errors = 0
    sample_errors = 0
    for benchmark in ("csi300", "csi500"):
        for horizon in HORIZONS:
            horizon_data = data.get("evaluation", {}).get("benchmarks", {}).get(benchmark, {}).get(f"forward_{horizon}m", {})
            for domain in CORE:
                actual_states = horizon_data.get(domain, {})
                expected_states: dict[str, dict[int, list[tuple[str, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
                for record in phase2["records"]:
                    if not ready(record, domain) or month_index(record["month"]) % horizon >= horizon:
                        continue
                    target = target_metric(target_map.get(record["month"], {}), benchmark, horizon)
                    if target is not None:
                        expected_states[state(record, domain)][month_index(record["month"]) % horizon].append((record["month"], target))
                for state_name, cohorts in expected_states.items():
                    actual = actual_states.get(state_name, {})
                    expected_cohort_summaries = {}
                    for cohort, points in sorted(cohorts.items()):
                        returns = [float(target["forward_return_pct"]) for _, target in points if target.get("forward_return_pct") is not None]
                        drawdowns = [float(target["max_drawdown_pct"]) for _, target in points if target.get("max_drawdown_pct") is not None]
                        expected_cohort_summaries[str(cohort)] = {"sample_count": len(returns), "mean_forward_return": round(statistics.mean(returns), 6) if returns else None, "median_forward_return": median(returns), "win_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 6) if returns else None, "q25": percentile(returns, .25), "q75": percentile(returns, .75), "median_future_max_drawdown": median(drawdowns), "worst_future_max_drawdown": min(drawdowns) if drawdowns else None, "origin_months": [month for month, _ in points]}
                    if actual.get("cohort_summaries") != expected_cohort_summaries:
                        alignment_errors += 1
                    cohort_sizes = [item["sample_count"] for item in expected_cohort_summaries.values()]
                    cohort_means = [item["mean_forward_return"] for item in expected_cohort_summaries.values() if item["mean_forward_return"] is not None]
                    cohort_win_rates = [item["win_rate"] for item in expected_cohort_summaries.values() if item["win_rate"] is not None]
                    cohort_dd = [item["median_future_max_drawdown"] for item in expected_cohort_summaries.values() if item["median_future_max_drawdown"] is not None]
                    expected_aggregate = {"aggregation_unit": "cohort", "sample_count": sum(cohort_sizes), "total_origin_count": sum(cohort_sizes), "cohort_count": len(cohort_sizes), "cohort_sample_counts": cohort_sizes, "effective_sample_count": median([float(item) for item in cohort_sizes]) if cohort_sizes else None, "min_cohort_sample_count": min(cohort_sizes, default=0), "max_cohort_sample_count": max(cohort_sizes, default=0), "mean_of_cohort_mean_forward_return": round(statistics.mean(cohort_means), 6) if cohort_means else None, "median_of_cohort_mean_forward_return": median(cohort_means), "q25_of_cohort_mean_forward_return": percentile(cohort_means, .25), "q75_of_cohort_mean_forward_return": percentile(cohort_means, .75), "mean_of_cohort_win_rate": round(statistics.mean(cohort_win_rates), 6) if cohort_win_rates else None, "median_of_cohort_win_rate": median(cohort_win_rates), "median_of_cohort_median_drawdown": median(cohort_dd), "global_worst_origin_drawdown": min((item["worst_future_max_drawdown"] for item in expected_cohort_summaries.values() if item["worst_future_max_drawdown"] is not None), default=None), "small_sample": (median([float(item) for item in cohort_sizes]) or 0) < 12}
                    if any(actual.get(key) != value for key, value in expected_aggregate.items()):
                        alignment_errors += 1
                    if actual.get("effective_sample_count") is not None and actual.get("small_sample") != (actual["effective_sample_count"] < 12):
                        sample_errors += 1
    return alignment_errors, sample_errors


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
    expected = audit_replay_snapshot(phase2)
    errors = {name: 0 for name in ("source_phase2_audit_violation_count", "source_phase2_hash_violation_count", "record_alignment_violation_count", "readiness_summary_violation_count", "state_distribution_violation_count", "transition_matrix_violation_count", "run_length_violation_count", "combination_count_violation_count", "conflict_diagnostic_violation_count", "evaluation_alignment_violation_count", "nonoverlap_cohort_violation_count", "sample_count_violation_count", "future_data_boundary_violation_count", "production_rule_mutation_count", "forbidden_output_violation_count", "upstream_mutation_count")}
    errors["source_phase2_audit_violation_count"] = int(phase2_audit.get("passed") is not True)
    errors["source_phase2_hash_violation_count"] = int(sha256_bytes(PHASE2_PATH.read_bytes()) != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 or data.get("source_phase2_sha256") != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)
    errors["upstream_mutation_count"] = int(canonical_sha(phase2) != canonical_sha(json.loads(PHASE2_PATH.read_text(encoding="utf-8"))) or phase2_audit.get("passed") is not True)
    errors["record_alignment_violation_count"] = int(data.get("record_count") != len(phase2["records"]) or data.get("start_month") != phase2["records"][0]["month"] or data.get("end_month") != phase2["records"][-1]["month"])
    for section in ("coverage", "state_distribution", "transitions", "combinations", "conflicts", "timeline", "window_extracts"):
        key = "readiness_summary_violation_count" if section == "coverage" else ("state_distribution_violation_count" if section == "state_distribution" else ("transition_matrix_violation_count" if section == "transitions" else ("combination_count_violation_count" if section == "combinations" else ("conflict_diagnostic_violation_count" if section == "conflicts" else "evaluation_alignment_violation_count"))))
        if data.get(section) != expected.get(section):
            errors[key] += 1
    for domain in CORE:
        actual = data.get("transitions", {}).get(domain, {})
        if actual.get("median_state_duration_months") != expected["transitions"][domain].get("median_state_duration_months"):
            errors["run_length_violation_count"] += 1
    for domain in DOMAINS:
        actual_states = data.get("state_distribution", {}).get(domain, {}).get("states", {})
        expected_states = expected["state_distribution"][domain].get("states", {})
        for state_name, expected_item in expected_states.items():
            actual_item = actual_states.get(state_name, {})
            if actual_item.get("longest_consecutive_run") != expected_item.get("longest_consecutive_run") or actual_item.get("median_run_length") != expected_item.get("median_run_length"):
                errors["run_length_violation_count"] += 1
    for name, expected_conflict in expected["conflicts"].items():
        actual_conflict = data.get("conflicts", {}).get(name, {})
        if actual_conflict.get("occurrence_count") != expected_conflict.get("occurrence_count") or actual_conflict.get("longest_duration") != expected_conflict.get("longest_duration") or actual_conflict.get("months") != expected_conflict.get("months"):
            errors["conflict_diagnostic_violation_count"] += 1
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
                    for values in horizon.get(domain, {}).values():
                        cohort_sizes = [item.get("sample_count", 0) for item in values.get("cohort_summaries", {}).values()]
                        if values.get("aggregation_unit") != "cohort" or values.get("total_origin_count") != len(values.get("origin_months", [])) or values.get("cohort_count") != len(cohort_sizes) or values.get("cohort_sample_counts") != cohort_sizes:
                            errors["sample_count_violation_count"] += 1
                        effective = median([float(item) for item in cohort_sizes]) if cohort_sizes else None
                        if values.get("effective_sample_count") != effective or values.get("small_sample") != ((effective or 0) < 12):
                            errors["sample_count_violation_count"] += 1
                        required = ("sample_count", "mean_forward_return", "median_forward_return", "win_rate", "q25", "q75", "median_future_max_drawdown", "worst_future_max_drawdown", "origin_months")
                        if any(any(key not in item for key in required) for item in values.get("cohort_summaries", {}).values()):
                            errors["evaluation_alignment_violation_count"] += 1
    evaluation_errors, sample_errors = audit_replay_evaluation(data, phase2, targets)
    errors["evaluation_alignment_violation_count"] += evaluation_errors
    errors["sample_count_violation_count"] += sample_errors
    phase3 = data.get("phase3_design_evidence", {})
    if not phase3.get("state_forward_return_summary") or not phase3.get("state_sample_sizes") or not phase3.get("insufficient_sample_flags"):
        errors["evaluation_alignment_violation_count"] += 1
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
