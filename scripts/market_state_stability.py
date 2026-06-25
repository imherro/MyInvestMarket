from __future__ import annotations

from typing import Any


REGIME_CYCLE = ["contraction", "accumulation", "expansion", "distribution"]
TREND_ORDER = ["early_trend", "strong_trend", "late_trend", "weakening_trend"]


def transition_issue(
    *,
    index: int,
    previous: dict[str, Any],
    current: dict[str, Any],
    field: str,
    previous_state: str,
    current_state: str,
    distance: int,
    max_distance: int,
) -> dict[str, Any]:
    return {
        "index": index,
        "field": field,
        "previous_run_id": previous.get("run_id"),
        "current_run_id": current.get("run_id"),
        "previous_basis_trade_date": previous.get("basis_trade_date"),
        "current_basis_trade_date": current.get("basis_trade_date"),
        "previous_state": previous_state,
        "current_state": current_state,
        "distance": distance,
        "max_distance": max_distance,
    }


def cyclic_distance(values: list[str], left: str, right: str) -> int | None:
    if left not in values or right not in values:
        return None
    left_index = values.index(left)
    right_index = values.index(right)
    forward = (right_index - left_index) % len(values)
    backward = (left_index - right_index) % len(values)
    return min(forward, backward)


def linear_distance(values: list[str], left: str, right: str) -> int | None:
    if left not in values or right not in values:
        return None
    return abs(values.index(right) - values.index(left))


def sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda row: (str(row.get("basis_trade_date") or ""), str(row.get("scored_at") or ""), str(row.get("run_id") or "")))


def validate_regime_persistence(records: list[dict[str, Any]], *, max_distance: int = 1) -> dict[str, Any]:
    ordered = sorted_records(records)
    issues: list[dict[str, Any]] = []
    for index in range(1, len(ordered)):
        previous = ordered[index - 1]
        current = ordered[index]
        previous_state = previous.get("market_regime_code")
        current_state = current.get("market_regime_code")
        if not isinstance(previous_state, str) or not isinstance(current_state, str):
            continue
        distance = cyclic_distance(REGIME_CYCLE, previous_state, current_state)
        if distance is not None and distance > max_distance:
            issues.append(
                transition_issue(
                    index=index,
                    previous=previous,
                    current=current,
                    field="market_regime_code",
                    previous_state=previous_state,
                    current_state=current_state,
                    distance=distance,
                    max_distance=max_distance,
                )
            )
    return {"ok": not issues, "checked_count": len(ordered), "issues": issues}


def validate_trend_continuity(records: list[dict[str, Any]], *, max_distance: int = 1) -> dict[str, Any]:
    ordered = sorted_records(records)
    issues: list[dict[str, Any]] = []
    for index in range(1, len(ordered)):
        previous = ordered[index - 1]
        current = ordered[index]
        previous_state = previous.get("trend_state")
        current_state = current.get("trend_state")
        if not isinstance(previous_state, str) or not isinstance(current_state, str):
            continue
        distance = linear_distance(TREND_ORDER, previous_state, current_state)
        if distance is not None and distance > max_distance:
            issues.append(
                transition_issue(
                    index=index,
                    previous=previous,
                    current=current,
                    field="trend_state",
                    previous_state=previous_state,
                    current_state=current_state,
                    distance=distance,
                    max_distance=max_distance,
                )
            )
    return {"ok": not issues, "checked_count": len(ordered), "issues": issues}


def validate_state_stability(records: list[dict[str, Any]]) -> dict[str, Any]:
    regime = validate_regime_persistence(records)
    trend = validate_trend_continuity(records)
    return {
        "ok": bool(regime.get("ok")) and bool(trend.get("ok")),
        "regime": regime,
        "trend": trend,
    }
