from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import backtest_engine


DEFAULT_RECENT_WINDOW = 20
DEFAULT_REFERENCE_WINDOW = 120
DRIFT_TYPE_THRESHOLD = 30.0


def detect_drift(
    records: list[dict[str, Any]],
    *,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    reference_window: int = DEFAULT_REFERENCE_WINDOW,
) -> dict[str, Any]:
    ordered = _sort_records(records)
    reference, recent = _split_windows(ordered, recent_window=recent_window, reference_window=reference_window)
    if not reference or not recent:
        return {
            "available": False,
            "drift_score": 0.0,
            "drift_type": [],
            "severity": "low",
            "reason": "not enough records for drift detection",
            "components": {},
            "sample": {"reference_count": len(reference), "recent_count": len(recent)},
        }

    regime_score = categorical_shift(reference, recent, "market_regime_code", fallback_key="market_regime")
    trend_state_score = categorical_shift(reference, recent, "trend_state")
    trend_transition_score = transition_shift(reference, recent, "trend_state")
    trend_score = max(trend_state_score, trend_transition_score)
    risk_score = numeric_distribution_shift(reference, recent, "risk_penalty_score")
    drift_score = round(_clamp(regime_score * 0.4 + trend_score * 0.3 + risk_score * 0.3, 0, 100), 2)
    components = {
        "regime": round(regime_score, 2),
        "trend": round(trend_score, 2),
        "trend_state": round(trend_state_score, 2),
        "trend_transition": round(trend_transition_score, 2),
        "risk": round(risk_score, 2),
    }
    drift_type = [key for key in ["regime", "trend", "risk"] if components[key] >= DRIFT_TYPE_THRESHOLD]
    return {
        "available": True,
        "version": "drift_detector_v1",
        "drift_score": drift_score,
        "drift_type": drift_type,
        "severity": severity(drift_score),
        "components": components,
        "sample": {
            "reference_count": len(reference),
            "recent_count": len(recent),
            "recent_window": recent_window,
            "reference_window": reference_window,
        },
    }


def categorical_shift(
    reference: list[dict[str, Any]],
    recent: list[dict[str, Any]],
    key: str,
    *,
    fallback_key: str | None = None,
) -> float:
    reference_values = [_category(record, key, fallback_key=fallback_key) for record in reference]
    recent_values = [_category(record, key, fallback_key=fallback_key) for record in recent]
    return jensen_shannon_score(Counter(reference_values), Counter(recent_values))


def transition_shift(reference: list[dict[str, Any]], recent: list[dict[str, Any]], key: str) -> float:
    reference_values = [_category(record, key) for record in reference]
    recent_values = [_category(record, key) for record in recent]
    return jensen_shannon_score(Counter(_transitions(reference_values)), Counter(_transitions(recent_values)))


def numeric_distribution_shift(reference: list[dict[str, Any]], recent: list[dict[str, Any]], key: str) -> float:
    reference_values = [value for record in reference if (value := backtest_engine.as_float(record.get(key))) is not None]
    recent_values = [value for record in recent if (value := backtest_engine.as_float(record.get(key))) is not None]
    if not reference_values or not recent_values:
        return 0.0
    reference_mean = sum(reference_values) / len(reference_values)
    recent_mean = sum(recent_values) / len(recent_values)
    reference_std = _std(reference_values)
    recent_std = _std(recent_values)
    mean_score = abs(recent_mean - reference_mean) * 1.5
    std_score = abs(recent_std - reference_std)
    return _clamp(mean_score + std_score, 0, 100)


def jensen_shannon_score(left: Counter[str], right: Counter[str]) -> float:
    keys = sorted(set(left) | set(right))
    if not keys:
        return 0.0
    left_total = sum(left.values())
    right_total = sum(right.values())
    if not left_total or not right_total:
        return 0.0
    p = [(left.get(key, 0) + 1e-9) / (left_total + 1e-9 * len(keys)) for key in keys]
    q = [(right.get(key, 0) + 1e-9) / (right_total + 1e-9 * len(keys)) for key in keys]
    m = [(a + b) / 2 for a, b in zip(p, q)]
    jsd = (_kl_divergence(p, m) + _kl_divergence(q, m)) / 2
    return _clamp(jsd * 100, 0, 100)


def severity(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _split_windows(
    records: list[dict[str, Any]],
    *,
    recent_window: int,
    reference_window: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(records) < 2:
        return [], records
    recent_size = min(max(1, recent_window), max(1, len(records) // 3))
    recent = records[-recent_size:]
    reference_pool = records[:-recent_size]
    if not reference_pool:
        return [], recent
    reference = reference_pool[-reference_window:]
    return reference, recent


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [record for record in records if isinstance(record, dict)],
        key=lambda row: (_parse_date(row.get("basis_trade_date")) or date.min, str(row.get("scored_at", ""))),
    )


def _category(record: dict[str, Any], key: str, *, fallback_key: str | None = None) -> str:
    value = record.get(key)
    if (value is None or value == "") and fallback_key:
        value = record.get(fallback_key)
    return str(value or "unknown")


def _transitions(values: list[str]) -> list[str]:
    if len(values) < 2:
        return ["no_transition"]
    return [f"{left}->{right}" for left, right in zip(values, values[1:])]


def _kl_divergence(p: list[float], q: list[float]) -> float:
    total = 0.0
    for left, right in zip(p, q):
        if left > 0 and right > 0:
            total += left * math.log2(left / right)
    return total


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect MyInvestMarket model drift.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(detect_drift(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
