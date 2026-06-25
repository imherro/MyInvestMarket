from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import backtest_engine
import model_health
import parameter_calibration


DRIFT_TRIGGER_THRESHOLD = 60.0
HEALTH_TRIGGER_THRESHOLD = 40.0


def evaluate_calibration_trigger(records: list[dict[str, Any]]) -> dict[str, Any]:
    health = model_health.compute_model_health(records)
    drift = health.get("drift", {})
    monitor = health.get("rolling_monitor", {})
    reasons: list[str] = []
    drift_score = backtest_engine.as_float(drift.get("drift_score")) or 0.0
    health_score = backtest_engine.as_float(health.get("health_score")) or 0.0
    if drift_score > DRIFT_TRIGGER_THRESHOLD:
        reasons.extend([f"{item}_drift" for item in drift.get("drift_type", [])] or ["model_drift"])
    if health_score < HEALTH_TRIGGER_THRESHOLD:
        reasons.append("model_health_degraded")
    if monitor.get("sharpe_decay"):
        reasons.append("sharpe_decay")
    trigger = bool(reasons)
    calibration = parameter_calibration.run_parameter_calibration(records) if trigger else {}
    return {
        "available": True,
        "version": "calibration_trigger_v1",
        "trigger": trigger,
        "reason": sorted(set(reasons)),
        "suggested_params": (calibration.get("best_params") if isinstance(calibration, dict) else {}) or {},
        "model_health": health,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate MyInvestMarket calibration trigger.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(evaluate_calibration_trigger(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
