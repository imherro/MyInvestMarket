"""Research-only historical replay of a global Cycle State candidate.

This module consumes only the frozen Phase 2 domain signals.  It deliberately
does not emit a score, a position, an allocation, or a trading signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PHASE2_PATH = DATA / "cycle_engine_domain_signals_v1.json"
PHASE2_AUDIT_PATH = DATA / "cycle_engine_domain_signals_audit_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_cycle_state_candidate_v1.json"
AUDIT_PATH = DATA / "cycle_engine_cycle_state_candidate_audit_v1.json"

# This is the byte hash of the corrected Phase 2 artifact on main.
FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 = "29676f1dd6e09631bda9d7cf366ec674edbbf2665e1eee1b30333ee7a1702c50"
CORE_STATES = {"cheap", "neutral", "expensive"}
BULLISH_CANDIDATES = {"bottoming", "early_bull", "bull", "late_bull"}
BEARISH_CANDIDATES = {"distribution", "bear", "deep_bear"}
ALLOWED_CANDIDATES = {"insufficient_history", "deep_bear", "bottoming", "early_bull", "bull", "late_bull", "distribution", "bear", "ambiguous"}
WINDOWS = {
    "2014_2015": ("2014-01", "2015-12"),
    "2018": ("2018-01", "2018-12"),
    "2020_2021": ("2020-01", "2021-12"),
    "2022": ("2022-01", "2022-12"),
    "2024": ("2024-01", "2024-12"),
    "2026": ("2026-01", "2026-08"),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def phase2_sha(phase2: dict[str, Any]) -> str:
    return sha256_bytes(PHASE2_PATH.read_bytes()) if phase2 == json.loads(PHASE2_PATH.read_text(encoding="utf-8")) else sha256_bytes((json.dumps(phase2, ensure_ascii=False, indent=2) + "\n").encode())


def load_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    phase2 = json.loads(PHASE2_PATH.read_text(encoding="utf-8"))
    audit = json.loads(PHASE2_AUDIT_PATH.read_text(encoding="utf-8"))
    if sha256_bytes(PHASE2_PATH.read_bytes()) != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256:
        raise RuntimeError("frozen Phase 2 Domain Signals hash gate failed")
    if audit.get("passed") is not True:
        raise RuntimeError("Phase 2 Domain Signals audit did not pass")
    return phase2, audit


def macro_alignment(candidate: str, macro: str) -> str:
    if candidate in BULLISH_CANDIDATES and macro == "positive":
        return "supportive"
    if candidate in BULLISH_CANDIDATES and macro == "negative":
        return "contradictory"
    if candidate in BEARISH_CANDIDATES and macro == "negative":
        return "supportive"
    if candidate in BEARISH_CANDIDATES and macro == "positive":
        return "contradictory"
    return "neutral"


def _rule_matches(valuation: str, earnings: str, trend: str) -> dict[str, bool]:
    return {
        "deep_bear_rule": trend == "damaged" and valuation == "cheap" and earnings == "deterioration",
        "bottoming_rule_A": valuation == "cheap" and earnings in {"bottoming", "recovery"} and trend in {"damaged", "bottoming", "mixed"},
        "bottoming_rule_B": trend == "bottoming" and valuation != "expensive" and earnings != "deterioration",
        "distribution_extended_rule": earnings == "deterioration" and trend == "extended",
        "distribution_expensive_rule": earnings == "deterioration" and valuation == "expensive" and trend in {"up", "extended", "mixed"},
        "late_bull_extended_rule": earnings != "deterioration" and trend == "extended" and valuation in {"neutral", "expensive"},
        "late_bull_expensive_rule": earnings != "deterioration" and valuation == "expensive" and trend in {"up", "extended"},
        "early_bull_rule": trend == "up" and valuation != "expensive" and earnings in {"bottoming", "recovery"},
        "bear_fallback": trend == "damaged",
        "bull_fallback": trend in {"up", "extended"},
        "ambiguous_fallback": True,
    }


def candidate_state(record: dict[str, Any]) -> tuple[str, list[str]]:
    valuation = record["valuation"]["state"]
    earnings = record["earnings"]["state"]
    trend = record["trend"]["state"]
    if not (record["valuation"].get("ready") and record["earnings"].get("ready") and record["trend"].get("ready")):
        return "insufficient_history", ["core_not_ready"]
    rules = _rule_matches(valuation, earnings, trend)
    if rules["deep_bear_rule"]:
        return "deep_bear", ["deep_bear_rule"]
    if rules["bottoming_rule_A"] or rules["bottoming_rule_B"]:
        reasons = [name for name in ("bottoming_rule_A", "bottoming_rule_B") if rules[name]]
        return "bottoming", reasons
    if rules["distribution_extended_rule"] or rules["distribution_expensive_rule"]:
        reasons = [name for name in ("distribution_extended_rule", "distribution_expensive_rule") if rules[name]]
        return "distribution", reasons
    if rules["late_bull_extended_rule"] or rules["late_bull_expensive_rule"]:
        reasons = [name for name in ("late_bull_extended_rule", "late_bull_expensive_rule") if rules[name]]
        return "late_bull", reasons
    if rules["early_bull_rule"]:
        return "early_bull", ["early_bull_rule"]
    if rules["bear_fallback"]:
        return "bear", ["bear_fallback"]
    if rules["bull_fallback"]:
        return "bull", ["bull_fallback"]
    return "ambiguous", ["ambiguous_fallback"]


def overlay(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in ("state", "score", "available", "observations", "model_ready", "role")}


def build(phase2: dict[str, Any]) -> dict[str, Any]:
    source_sha = phase2_sha(phase2)
    rows = []
    for source in phase2["records"]:
        candidate, reasons = candidate_state(source)
        macro = source["macro_confirmation"]["state"]
        rows.append({
            "month": source["month"],
            "basis_trade_date": source["basis_trade_date"],
            "source_phase2_sha256": source_sha,
            "core_ready": candidate != "insufficient_history",
            "candidate_state": candidate,
            "valuation_state": source["valuation"]["state"],
            "earnings_state": source["earnings"]["state"],
            "trend_state": source["trend"]["state"],
            "macro_confirmation_state": macro,
            "macro_alignment": macro_alignment(candidate, macro),
            "sentiment_overlay": overlay(source["sentiment_overlay"]),
            "reason_codes": reasons,
        })
    ready_rows = [row for row in rows if row["core_ready"]]
    values = [row["candidate_state"] for row in ready_rows]
    runs = {state: _true_runs(values, state) for state in sorted(ALLOWED_CANDIDATES - {"insufficient_history"})}
    states = {}
    for state in sorted(ALLOWED_CANDIDATES - {"insufficient_history"}):
        months = [row["month"] for row in ready_rows if row["candidate_state"] == state]
        lengths = runs[state]
        states[state] = {"month_count": len(months), "percentage_of_core_ready_months": round(len(months) / len(ready_rows) * 100, 6) if ready_rows else 0.0, "first_month": min(months) if months else None, "last_month": max(months) if months else None, "longest_consecutive_run": max(lengths, default=0), "median_run_length": median([float(x) for x in lengths]) if lengths else None}
    transitions = Counter(f"{a}->{b}" for a, b in zip(values, values[1:]))
    outgoing = Counter(a for a, _ in zip(values, values[1:]))
    transition_matrix = {key: {"transition_count": count, "transition_probability": round(count / outgoing[key.split("->")[0]] * 100, 6)} for key, count in sorted(transitions.items())}
    rule_hits = Counter()
    for row in ready_rows:
        matched_rules = _rule_matches(row["valuation_state"], row["earnings_state"], row["trend_state"])
        for name, matched in matched_rules.items():
            is_selected_fallback = name.endswith("_fallback") and name.removesuffix("_fallback") == row["candidate_state"]
            if matched and (not name.endswith("_fallback") or is_selected_fallback):
                rule_hits[name] += 1
    timeline = [{key: row[key] for key in ("month", "candidate_state", "valuation_state", "earnings_state", "trend_state", "macro_confirmation_state", "macro_alignment")} for row in ready_rows]
    windows = {name: [row for row in timeline if start <= row["month"] <= end] for name, (start, end) in WINDOWS.items()}
    return {"schema": "cycle_engine_cycle_state_candidate_v1", "description": "Research-only global cycle state candidate replay.", "research_only": True, "source_phase2_sha256": source_sha, "record_count": len(rows), "first_core_ready_month": ready_rows[0]["month"] if ready_rows else None, "last_core_ready_month": ready_rows[-1]["month"] if ready_rows else None, "records": rows, "diagnostics": {"candidate_state_distribution": states, "monthly_state_change_rate": round(sum(a != b for a, b in zip(values, values[1:])) / (len(values) - 1) * 100, 6) if len(values) > 1 else None, "transition_matrix": transition_matrix, "ambiguous_month_count": values.count("ambiguous"), "ambiguous_pct": round(values.count("ambiguous") / len(values) * 100, 6) if values else 0.0, "rule_hit_counts": {name: rule_hits[name] for name in ("deep_bear_rule", "bottoming_rule_A", "bottoming_rule_B", "distribution_extended_rule", "distribution_expensive_rule", "late_bull_extended_rule", "late_bull_expensive_rule", "early_bull_rule", "bear_fallback", "bull_fallback", "ambiguous_fallback")}, "timeline": timeline, "window_extracts": windows}}


def _true_runs(values: list[str], target: str) -> list[int]:
    runs, current = [], 0
    for value in values:
        if value == target:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def _audit_replay_record(source: dict[str, Any]) -> dict[str, Any]:
    valuation = source["valuation"]["state"]
    earnings = source["earnings"]["state"]
    trend = source["trend"]["state"]
    core_ready = bool(source["valuation"].get("ready") and source["earnings"].get("ready") and source["trend"].get("ready"))
    if not core_ready:
        state, reasons = "insufficient_history", ["core_not_ready"]
    else:
        rules = _rule_matches(valuation, earnings, trend)
        if rules["deep_bear_rule"]:
            state, reasons = "deep_bear", ["deep_bear_rule"]
        elif rules["bottoming_rule_A"] or rules["bottoming_rule_B"]:
            state, reasons = "bottoming", [name for name in ("bottoming_rule_A", "bottoming_rule_B") if rules[name]]
        elif rules["distribution_extended_rule"] or rules["distribution_expensive_rule"]:
            state, reasons = "distribution", [name for name in ("distribution_extended_rule", "distribution_expensive_rule") if rules[name]]
        elif rules["late_bull_extended_rule"] or rules["late_bull_expensive_rule"]:
            state, reasons = "late_bull", [name for name in ("late_bull_extended_rule", "late_bull_expensive_rule") if rules[name]]
        elif rules["early_bull_rule"]:
            state, reasons = "early_bull", ["early_bull_rule"]
        elif rules["bear_fallback"]:
            state, reasons = "bear", ["bear_fallback"]
        elif rules["bull_fallback"]:
            state, reasons = "bull", ["bull_fallback"]
        else:
            state, reasons = "ambiguous", ["ambiguous_fallback"]
    macro = source["macro_confirmation"]["state"]
    if state in BULLISH_CANDIDATES and macro == "positive" or state in BEARISH_CANDIDATES and macro == "negative":
        alignment = "supportive"
    elif state in BULLISH_CANDIDATES and macro == "negative" or state in BEARISH_CANDIDATES and macro == "positive":
        alignment = "contradictory"
    else:
        alignment = "neutral"
    return {"month": source["month"], "basis_trade_date": source["basis_trade_date"], "core_ready": core_ready, "candidate_state": state, "valuation_state": valuation, "earnings_state": earnings, "trend_state": trend, "macro_confirmation_state": macro, "macro_alignment": alignment, "sentiment_overlay": overlay(source["sentiment_overlay"]), "reason_codes": reasons}


def audit(data: dict[str, Any], phase2: dict[str, Any], phase2_audit: dict[str, Any]) -> dict[str, Any]:
    errors = {name: 0 for name in ("source_phase2_audit_violation_count", "source_phase2_hash_violation_count", "record_alignment_violation_count", "core_readiness_violation_count", "candidate_rule_violation_count", "rule_precedence_violation_count", "macro_flip_violation_count", "sentiment_core_leakage_count", "run_length_violation_count", "transition_violation_count", "forbidden_output_violation_count", "future_information_dependency_count", "upstream_mutation_count")}
    actual_sha = sha256_bytes(PHASE2_PATH.read_bytes()) if phase2 == json.loads(PHASE2_PATH.read_text(encoding="utf-8")) else phase2_sha(phase2)
    errors["source_phase2_audit_violation_count"] = int(phase2_audit.get("passed") is not True)
    errors["source_phase2_hash_violation_count"] = int(sha256_bytes(PHASE2_PATH.read_bytes()) != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 or actual_sha != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256 or data.get("source_phase2_sha256") != FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)
    errors["upstream_mutation_count"] = int(errors["source_phase2_hash_violation_count"] or phase2_audit.get("passed") is not True)
    actual_records = data.get("records", [])
    expected_records = [_audit_replay_record(source) for source in phase2["records"]]
    errors["record_alignment_violation_count"] = int(len(actual_records) != len(expected_records) or [item.get("month") for item in actual_records] != [item["month"] for item in expected_records])
    for actual, expected in zip(actual_records, expected_records):
        if any(actual.get(key) != expected.get(key) for key in expected):
            errors["candidate_rule_violation_count"] += 1
        if actual.get("core_ready") != (expected["candidate_state"] != "insufficient_history"):
            errors["core_readiness_violation_count"] += 1
        if actual.get("sentiment_overlay", {}).get("role") != "overlay_only":
            errors["sentiment_core_leakage_count"] += 1
        if actual.get("candidate_state") != "insufficient_history" and actual.get("macro_alignment") not in {"supportive", "contradictory", "neutral"}:
            errors["macro_flip_violation_count"] += 1
    ready = [item for item in expected_records if item["core_ready"]]
    expected_states = [item["candidate_state"] for item in ready]
    diagnostic = data.get("diagnostics", {})
    distribution = diagnostic.get("candidate_state_distribution", {})
    for state in sorted(ALLOWED_CANDIDATES - {"insufficient_history"}):
        expected_lengths = _true_runs(expected_states, state)
        item = distribution.get(state, {})
        if item.get("month_count") != expected_states.count(state) or item.get("longest_consecutive_run") != max(expected_lengths, default=0) or item.get("median_run_length") != (median([float(x) for x in expected_lengths]) if expected_lengths else None):
            errors["run_length_violation_count"] += 1
    transitions = Counter(f"{a}->{b}" for a, b in zip(expected_states, expected_states[1:]))
    if {key: value["transition_count"] for key, value in diagnostic.get("transition_matrix", {}).items()} != dict(sorted(transitions.items())):
        errors["transition_violation_count"] += 1
    forbidden = json.dumps(data, ensure_ascii=False).lower()
    if any(token in forbidden for token in ("cycle_score", "bull_bear_score", "market_score", "recommended_position", "equity_position", "allocation", "buy_signal", "sell_signal")):
        errors["forbidden_output_violation_count"] += 1
    if any(token in key.lower() for key in data for token in ("forward", "future_return", "evaluation_target")):
        errors["future_information_dependency_count"] += 1
    return {"schema": "cycle_engine_cycle_state_candidate_audit_v1", "record_count": len(expected_records), **errors, "passed": not any(errors.values())}


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    phase2, phase2_audit = load_sources()
    output = build(phase2)
    result = audit(output, phase2, phase2_audit)
    if not result["passed"]:
        raise RuntimeError("cycle state candidate audit failed: " + json.dumps(result, ensure_ascii=False))
    return output, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    output, result = generate()
    if args.generate:
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        AUDIT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
