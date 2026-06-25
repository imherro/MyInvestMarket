from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import backtest_engine
import drift_detector
import rolling_monitor


REGIME_ORDER = {"accumulation": 0, "expansion": 1, "distribution": 2, "contraction": 3}
TREND_ORDER = {"early_trend": 0, "strong_trend": 1, "late_trend": 2, "weakening_trend": 3}


def compute_model_health(records: list[dict[str, Any]]) -> dict[str, Any]:
    drift = drift_detector.detect_drift(records)
    backtest = backtest_engine.run_backtest(records)
    monitor = rolling_monitor.monitor_backtest(backtest)
    performance = performance_score(backtest.get("metrics", {}))
    stability = stability_score(records)
    drift_score = backtest_engine.as_float(drift.get("drift_score")) or 0.0
    drift_component = 100.0 - drift_score
    health_score = _clamp(0.4 * performance + 0.3 * stability + 0.3 * drift_component, 0, 100)
    if monitor.get("sharpe_decay"):
        health_score = _clamp(health_score - 10, 0, 100)
    return {
        "available": True,
        "version": "model_health_v1",
        "health_score": round(health_score, 2),
        "status": health_status(health_score),
        "components": {
            "backtest_performance": round(performance, 2),
            "stability_score": round(stability, 2),
            "drift_component": round(drift_component, 2),
        },
        "drift": drift,
        "rolling_monitor": monitor,
        "backtest_metrics": backtest.get("metrics", {}),
        "notes": health_notes(health_score, drift, monitor),
    }


def performance_score(backtest_metrics: dict[str, Any]) -> float:
    sharpe = backtest_engine.as_float(backtest_metrics.get("sharpe_ratio")) or 0.0
    max_drawdown = backtest_engine.as_float(backtest_metrics.get("max_drawdown")) or 0.0
    win_rate = backtest_engine.as_float(backtest_metrics.get("win_rate")) or 0.0
    score = 50.0 + sharpe * 10.0 + (win_rate - 0.5) * 20.0 - max_drawdown * 120.0
    return _clamp(score, 0, 100)


def stability_score(records: list[dict[str, Any]]) -> float:
    ordered = sorted(
        [record for record in records if isinstance(record, dict)],
        key=lambda row: (_parse_date(row.get("basis_trade_date")) or date.min, str(row.get("scored_at", ""))),
    )
    if len(ordered) < 2:
        return 70.0
    bad_jumps = 0
    checked = 0
    for left, right in zip(ordered, ordered[1:]):
        for key, order in [("market_regime_code", REGIME_ORDER), ("trend_state", TREND_ORDER)]:
            left_value = left.get(key)
            right_value = right.get(key)
            if left_value not in order or right_value not in order:
                continue
            checked += 1
            if abs(order[right_value] - order[left_value]) > 1:
                bad_jumps += 1
    if checked == 0:
        return 70.0
    return _clamp(100.0 - bad_jumps / checked * 100.0, 0, 100)


def health_status(score: float) -> str:
    if score >= 70:
        return "healthy"
    if score >= 40:
        return "warning"
    return "degraded"


def health_notes(score: float, drift: dict[str, Any], monitor: dict[str, Any]) -> list[str]:
    notes = []
    if score < 40:
        notes.append("Model health is degraded; freeze automatic parameter changes and review drift sources.")
    elif score < 70:
        notes.append("Model health is in warning state; monitor next post-close update before increasing risk.")
    else:
        notes.append("Model health is acceptable under current validation rules.")
    if drift.get("severity") == "high":
        notes.append("High drift detected; calibration review is required.")
    if monitor.get("sharpe_decay"):
        notes.append("Rolling Sharpe decay detected.")
    return notes


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute MyInvestMarket model health.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(compute_model_health(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
