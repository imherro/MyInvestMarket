"""Research-only stateful replay over the frozen Phase 3.0 candidate artifact."""

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
CANDIDATE_PATH = DATA / "cycle_engine_cycle_state_candidate_v1.json"
CANDIDATE_AUDIT_PATH = DATA / "cycle_engine_cycle_state_candidate_audit_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_state_machine_v1.json"
AUDIT_PATH = DATA / "cycle_engine_state_machine_audit_v1.json"

FROZEN_PHASE3_CANDIDATE_SHA256 = "9764e56c8b094d7d5927964bfdee20ba62efb98da55edbb9a2e50cbfc87e161a"
STATES = ("insufficient_history", "deep_bear", "bottoming", "early_bull", "bull", "late_bull", "distribution", "bear", "ambiguous")
TRANSITION_STATUSES = ("insufficient_history", "uninitialized_ambiguous", "initialized", "held_same", "held_ambiguous", "pending_started", "pending_continued", "pending_replaced", "pending_expired", "transition_confirmed")
WINDOWS = {"2014_2015": ("2014-01", "2015-12"), "2018": ("2018-01", "2018-12"), "2020_2021": ("2020-01", "2021-12"), "2022": ("2022-01", "2022-12"), "2024": ("2024-01", "2024-12"), "2026": ("2026-01", "2026-08")}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def candidate_byte_sha(candidate: dict[str, Any]) -> str:
    # Frozen artifacts are committed with CRLF bytes on Windows.
    text = json.dumps(candidate, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n"
    return sha256_bytes(text.encode("utf-8"))


def load_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    audit = json.loads(CANDIDATE_AUDIT_PATH.read_text(encoding="utf-8"))
    if sha256_bytes(CANDIDATE_PATH.read_bytes()) != FROZEN_PHASE3_CANDIDATE_SHA256:
        raise RuntimeError("frozen Phase 3.0 Candidate hash gate failed")
    if audit.get("passed") is not True:
        raise RuntimeError("Phase 3.0 Candidate audit did not pass")
    return candidate, audit


def _overlay(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in ("state", "score", "available", "observations", "model_ready", "role")}


def _step(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stable = "insufficient_history"
    initialized = False
    pending_target: str | None = None
    pending_count = 0
    pending_gap = 0
    pending_first_month: str | None = None
    rows: list[dict[str, Any]] = []
    for source in records:
        raw = source["candidate_state"]
        previous_stable = stable
        previous_pending = pending_target
        transition_status = "insufficient_history"
        transition_from = None
        transition_to = None
        used_grace = False
        first_evidence = None
        if raw == "insufficient_history":
            stable = "insufficient_history"
            initialized = False
            pending_target = None
            pending_count = 0
            pending_gap = 0
            pending_first_month = None
            transition_status = "insufficient_history"
        elif not initialized:
            if raw == "ambiguous":
                stable = "ambiguous"
                pending_target = None
                pending_count = 0
                pending_gap = 0
                pending_first_month = None
                transition_status = "uninitialized_ambiguous"
            else:
                stable = raw
                initialized = True
                pending_target = None
                pending_count = 0
                pending_gap = 0
                pending_first_month = None
                transition_status = "initialized"
        elif raw == stable:
            if pending_target is not None:
                transition_status = "held_same"
            else:
                transition_status = "held_same"
            pending_target = None
            pending_count = 0
            pending_gap = 0
            pending_first_month = None
        elif raw == "ambiguous":
            if pending_target is None:
                transition_status = "held_ambiguous"
            elif pending_gap == 0:
                pending_gap = 1
                transition_status = "held_ambiguous"
            else:
                pending_target = None
                pending_count = 0
                pending_gap = 0
                pending_first_month = None
                transition_status = "pending_expired"
        elif pending_target == raw:
            pending_count += 1
            used_grace = pending_gap == 1
            first_evidence = pending_first_month
            transition_from = stable
            transition_to = raw
            stable = raw
            pending_target = None
            pending_count = 0
            pending_gap = 0
            pending_first_month = None
            transition_status = "transition_confirmed"
        elif pending_target is not None:
            pending_target = raw
            pending_count = 1
            pending_gap = 0
            pending_first_month = source["month"]
            transition_status = "pending_replaced"
        else:
            pending_target = raw
            pending_count = 1
            pending_gap = 0
            pending_first_month = source["month"]
            transition_status = "pending_started"
        stable_reason = {
            "insufficient_history": "insufficient_history",
            "uninitialized_ambiguous": "uninitialized_ambiguous",
            "initialized": "initial_non_ambiguous_state",
            "held_same": "current_state_reconfirmed",
            "held_ambiguous": "ambiguous_hold",
            "pending_started": "pending_first_evidence",
            "pending_continued": "pending_same_target",
            "pending_replaced": "pending_replaced_by_competing_candidate",
            "pending_expired": "pending_expired_after_two_ambiguous",
            "transition_confirmed": "two_hit_transition_confirmed",
        }[transition_status]
        if transition_status == "held_same" and previous_pending is not None:
            stable_reason = "pending_cancelled_by_current_state"
        rows.append({
            "month": source["month"], "basis_trade_date": source["basis_trade_date"], "source_candidate_sha256": FROZEN_PHASE3_CANDIDATE_SHA256,
            "core_ready": source["core_ready"], "raw_candidate_state": raw, "stable_state": stable, "initialized": initialized,
            "transition_status": transition_status, "transition_from": transition_from, "transition_to": transition_to,
            "pending_target": pending_target, "pending_count": pending_count, "pending_gap_months": pending_gap,
            "raw_reason_codes": source.get("reason_codes", []), "stable_reason_codes": [stable_reason],
            "macro_alignment": source.get("macro_alignment"), "sentiment_overlay": _overlay(source.get("sentiment_overlay", {})),
        })
    return rows


def _runs(values: list[str], target: str) -> list[int]:
    result, current = [], 0
    for value in values:
        if value == target:
            current += 1
        elif current:
            result.append(current)
            current = 0
    if current:
        result.append(current)
    return result


def _diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [row for row in rows if row["core_ready"]]
    raw_values = [row["raw_candidate_state"] for row in ready]
    stable_values = [row["stable_state"] for row in ready]
    raw_changes = sum(a != b for a, b in zip(raw_values, raw_values[1:]))
    stable_changes = sum(a != b for a, b in zip(stable_values, stable_values[1:]))
    raw_rate = raw_changes / (len(raw_values) - 1) * 100 if len(raw_values) > 1 else None
    stable_rate = stable_changes / (len(stable_values) - 1) * 100 if len(stable_values) > 1 else None
    dist = {}
    for state in STATES:
        months = [row["month"] for row in ready if row["stable_state"] == state]
        lengths = _runs(stable_values, state)
        dist[state] = {"month_count": len(months), "percentage_of_core_ready_months": round(len(months) / len(ready) * 100, 6) if ready else 0.0, "first_month": min(months) if months else None, "last_month": max(months) if months else None, "longest_run": max(lengths, default=0), "median_run": median([float(x) for x in lengths]) if lengths else None}
    events = []
    for index, row in enumerate(ready):
        if row["transition_status"] == "transition_confirmed":
            first = next((candidate for candidate in ready[: index + 1] if candidate["month"] == row["month"]), row)
            # The first evidence month is retained in the pending trace below.
            prior = ready[index - 1] if index else row
            used_grace = prior["raw_candidate_state"] == "ambiguous"
            first_month = ready[index - 2]["month"] if used_grace and index >= 2 else prior["month"]
            events.append({"from": row["transition_from"], "to": row["transition_to"], "first_evidence_month": first_month, "confirmation_month": row["month"], "confirmation_delay_months": max(0, index - next((j for j, x in enumerate(ready) if x["month"] == first_month), index)), "used_ambiguous_grace": used_grace, "trigger_raw_candidate": row["raw_candidate_state"]})
    transitions = Counter(f"{a}->{b}" for a, b in zip(stable_values, stable_values[1:]))
    raw_stable = Counter(f"{row['raw_candidate_state']}->{row['stable_state']}" for row in ready)
    status_counts = Counter(row["transition_status"] for row in rows)
    pending_confirmed = sum(row["transition_status"] == "transition_confirmed" for row in rows)
    pending_started = sum(row["transition_status"] == "pending_started" for row in rows)
    pending_replaced = sum(row["transition_status"] == "pending_replaced" for row in rows)
    pending_expired = sum(row["transition_status"] == "pending_expired" for row in rows)
    pending_cancelled = sum(row["transition_status"] == "held_same" and row["raw_candidate_state"] == row["stable_state"] for row in rows)
    windows = {name: [{key: row[key] for key in ("month", "raw_candidate_state", "stable_state", "pending_target", "transition_status")} for row in rows if start <= row["month"] <= end] for name, (start, end) in WINDOWS.items()}
    return {"raw_vs_stable": {"raw_monthly_state_change_rate": round(raw_rate, 6) if raw_rate is not None else None, "stable_monthly_state_change_rate": round(stable_rate, 6) if stable_rate is not None else None, "absolute_reduction": round(raw_rate - stable_rate, 6) if raw_rate is not None and stable_rate is not None else None, "relative_reduction_pct": round((raw_rate - stable_rate) / raw_rate * 100, 6) if raw_rate else None}, "ambiguous": {"raw_month_count": raw_values.count("ambiguous"), "raw_pct": round(raw_values.count("ambiguous") / len(raw_values) * 100, 6) if raw_values else 0.0, "stable_month_count": stable_values.count("ambiguous"), "stable_after_initialization_count": sum(row["stable_state"] == "ambiguous" and row["initialized"] for row in ready)}, "stable_state_distribution": dist, "transitions": {"confirmed_transition_count": len(events), "transition_matrix": {key: {"transition_count": value} for key, value in sorted(transitions.items())}, "transition_events": events}, "pending": {"pending_started_count": pending_started, "pending_confirmed_count": pending_confirmed, "pending_replaced_count": pending_replaced, "pending_expired_count": pending_expired, "pending_cancelled_by_current_state_count": pending_cancelled, "status_counts": dict(sorted(status_counts.items()))}, "raw_to_stable_matrix": {key: value for key, value in sorted(raw_stable.items())}, "window_extracts": windows}


def build(candidate: dict[str, Any]) -> dict[str, Any]:
    rows = _step(candidate["records"])
    return {"schema": "cycle_engine_state_machine_v1", "description": "Research-only stateful replay over frozen candidate evidence.", "research_only": True, "source_candidate_sha256": FROZEN_PHASE3_CANDIDATE_SHA256, "record_count": len(rows), "first_core_ready_month": next((row["month"] for row in rows if row["core_ready"]), None), "records": rows, "diagnostics": _diagnostics(rows)}


def _audit_replay(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Independent implementation; deliberately does not call _step/build.
    stable = "insufficient_history"
    initialized = False
    pending = None
    count = 0
    gap = 0
    first = None
    output = []
    for source in records:
        raw = source["candidate_state"]
        status = "insufficient_history"
        old = stable
        had_pending = pending is not None
        from_state = None
        to_state = None
        if raw == "insufficient_history":
            stable, initialized, pending, count, gap, first = "insufficient_history", False, None, 0, 0, None
        elif not initialized:
            if raw == "ambiguous":
                stable, pending, count, gap, first, status = "ambiguous", None, 0, 0, None, "uninitialized_ambiguous"
            else:
                stable, initialized, pending, count, gap, first, status = raw, True, None, 0, 0, None, "initialized"
        elif raw == stable:
            pending, count, gap, first, status = None, 0, 0, None, "held_same"
        elif raw == "ambiguous":
            if pending is None:
                status = "held_ambiguous"
            elif gap == 0:
                gap, status = 1, "held_ambiguous"
            else:
                pending, count, gap, first, status = None, 0, 0, None, "pending_expired"
        elif pending == raw:
            from_state, to_state = stable, raw
            stable, pending, count, gap, first, status = raw, None, 0, 0, None, "transition_confirmed"
        elif pending is not None:
            pending, count, gap, first, status = raw, 1, 0, source["month"], "pending_replaced"
        else:
            pending, count, gap, first, status = raw, 1, 0, source["month"], "pending_started"
        reason = {"insufficient_history": "insufficient_history", "uninitialized_ambiguous": "uninitialized_ambiguous", "initialized": "initial_non_ambiguous_state", "held_same": "current_state_reconfirmed", "held_ambiguous": "ambiguous_hold", "pending_started": "pending_first_evidence", "pending_replaced": "pending_replaced_by_competing_candidate", "pending_expired": "pending_expired_after_two_ambiguous", "transition_confirmed": "two_hit_transition_confirmed"}[status]
        if status == "held_same" and had_pending:
            reason = "pending_cancelled_by_current_state"
        output.append({"month": source["month"], "basis_trade_date": source["basis_trade_date"], "core_ready": source["core_ready"], "raw_candidate_state": raw, "stable_state": stable, "initialized": initialized, "transition_status": status, "transition_from": from_state, "transition_to": to_state, "pending_target": pending, "pending_count": count, "pending_gap_months": gap, "raw_reason_codes": source.get("reason_codes", []), "stable_reason_codes": [reason], "macro_alignment": source.get("macro_alignment"), "sentiment_overlay": _overlay(source.get("sentiment_overlay", {}))})
    return output


def _contains_forbidden(value: Any) -> bool:
    forbidden = ("cycle_score", "bull_bear_score", "market_score", "recommended_position", "equity_position", "allocation", "buy_signal", "sell_signal", "trade_signal")
    if isinstance(value, dict):
        return any(any(token in str(key).lower() for token in forbidden) or _contains_forbidden(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden(child) for child in value)
    return False


def _contains_future_marker(value: Any) -> bool:
    markers = ("forward", "future_return", "evaluation_target", "evaluation", "ex_post")
    if isinstance(value, dict):
        return any(any(marker in str(key).lower() for marker in markers) or _contains_future_marker(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_future_marker(child) for child in value)
    return False


def audit(data: dict[str, Any], candidate: dict[str, Any], candidate_audit: dict[str, Any]) -> dict[str, Any]:
    names = ("source_candidate_audit_violation_count", "source_candidate_hash_violation_count", "record_alignment_violation_count", "initialization_violation_count", "ambiguous_hold_violation_count", "pending_state_violation_count", "confirmation_rule_violation_count", "pending_expiry_violation_count", "stable_state_violation_count", "transition_metadata_violation_count", "stable_diagnostics_violation_count", "transition_diagnostics_violation_count", "stability_improvement_violation_count", "macro_core_leakage_count", "sentiment_core_leakage_count", "future_information_dependency_count", "forbidden_output_violation_count", "upstream_mutation_count")
    errors = {name: 0 for name in names}
    actual_file_sha = sha256_bytes(CANDIDATE_PATH.read_bytes())
    errors["source_candidate_audit_violation_count"] = int(candidate_audit.get("passed") is not True)
    errors["source_candidate_hash_violation_count"] = int(actual_file_sha != FROZEN_PHASE3_CANDIDATE_SHA256 or candidate_byte_sha(candidate) != FROZEN_PHASE3_CANDIDATE_SHA256 or data.get("source_candidate_sha256") != FROZEN_PHASE3_CANDIDATE_SHA256)
    errors["upstream_mutation_count"] = int(errors["source_candidate_hash_violation_count"] or candidate_audit.get("passed") is not True)
    expected = _audit_replay(candidate["records"])
    actual = data.get("records", [])
    errors["record_alignment_violation_count"] = int([row.get("month") for row in actual] != [row["month"] for row in expected] or len(actual) != len(expected))
    for left, right in zip(actual, expected):
        if left.get("month") != right["month"] or left.get("basis_trade_date") != right["basis_trade_date"] or left.get("core_ready") != right["core_ready"] or left.get("raw_candidate_state") != right["raw_candidate_state"] or left.get("raw_reason_codes") != right["raw_reason_codes"]:
            errors["record_alignment_violation_count"] += 1
        if left.get("stable_state") != right["stable_state"]:
            errors["stable_state_violation_count"] += 1
            errors["confirmation_rule_violation_count"] += 1
        if left.get("initialized") != right["initialized"]:
            errors["initialization_violation_count"] += 1
        if left.get("pending_target") != right["pending_target"] or left.get("pending_count") != right["pending_count"] or left.get("pending_gap_months") != right["pending_gap_months"]:
            errors["pending_state_violation_count"] += 1
        if left.get("transition_status") != right["transition_status"] or left.get("transition_from") != right["transition_from"] or left.get("transition_to") != right["transition_to"]:
            errors["transition_metadata_violation_count"] += 1
        if left.get("stable_reason_codes") != right["stable_reason_codes"] or left.get("source_candidate_sha256") != FROZEN_PHASE3_CANDIDATE_SHA256:
            errors["transition_metadata_violation_count"] += 1
        if left.get("raw_candidate_state") == "ambiguous" and left.get("stable_state") != right.get("stable_state"):
            errors["ambiguous_hold_violation_count"] += 1
        if left.get("transition_status") == "pending_expired" and right.get("transition_status") != "pending_expired":
            errors["pending_expiry_violation_count"] += 1
        if left.get("macro_alignment") != right.get("macro_alignment"):
            errors["macro_core_leakage_count"] += 1
        if left.get("sentiment_overlay") != right.get("sentiment_overlay"):
            errors["sentiment_core_leakage_count"] += 1
    expected_diag = _diagnostics(expected)
    diagnostics = data.get("diagnostics", {})
    if diagnostics.get("raw_vs_stable") != expected_diag["raw_vs_stable"]:
        errors["stability_improvement_violation_count"] += 1
    if diagnostics.get("ambiguous") != expected_diag["ambiguous"] or diagnostics.get("stable_state_distribution") != expected_diag["stable_state_distribution"] or diagnostics.get("raw_to_stable_matrix") != expected_diag["raw_to_stable_matrix"]:
        errors["stable_diagnostics_violation_count"] += 1
    if diagnostics.get("transitions") != expected_diag["transitions"] or diagnostics.get("pending") != expected_diag["pending"]:
        errors["transition_diagnostics_violation_count"] += 1
    errors["stability_improvement_violation_count"] += int((expected_diag["raw_vs_stable"]["stable_monthly_state_change_rate"] or 0) >= (expected_diag["raw_vs_stable"]["raw_monthly_state_change_rate"] or 0))
    errors["forbidden_output_violation_count"] = int(_contains_forbidden(data))
    errors["future_information_dependency_count"] = int(_contains_future_marker(data))
    return {"schema": "cycle_engine_state_machine_audit_v1", "record_count": len(expected), **errors, "passed": not any(errors.values())}


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    candidate, candidate_audit = load_sources()
    output = build(candidate)
    result = audit(output, candidate, candidate_audit)
    if not result["passed"]:
        raise RuntimeError("state machine audit failed: " + json.dumps(result, ensure_ascii=False))
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
