from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
from typing import Any

import backtest_engine


DEFAULT_GRID = {
    "opportunity_score_scale": [0.95, 1.0, 1.05],
    "risk_discount_shift": [-0.05, 0.0, 0.05],
    "regime_multiplier_shift": [-0.04, 0.0, 0.04],
    "trend_multiplier_shift": [-0.04, 0.0, 0.04],
}


def run_parameter_calibration(
    records: list[dict[str, Any]],
    *,
    parameter_grid: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    grid = parameter_grid or DEFAULT_GRID
    scenarios = []
    best: dict[str, Any] | None = None
    for params in _grid_product(grid):
        adjusted_records = [_adjust_record(record, params) for record in records]
        result = backtest_engine.run_backtest(adjusted_records, label="calibration_candidate")
        metrics = result.get("metrics", {})
        objective = _objective(metrics)
        scenario = {
            "params": params,
            "available": result.get("available"),
            "objective": objective,
            "metrics": metrics,
        }
        scenarios.append(scenario)
        if result.get("available") and (best is None or objective > best["objective"]):
            best = scenario

    best_params = _format_best_params(best["params"] if best else {})
    return {
        "available": bool(best),
        "tested_count": len(scenarios),
        "best_params": best_params,
        "best_metrics": (best or {}).get("metrics", {}),
        "sensitivity": scenarios,
        "guardrail": "This is sensitivity analysis, not automatic live parameter replacement.",
    }


def _grid_product(grid: dict[str, list[float]]) -> list[dict[str, float]]:
    keys = list(grid.keys())
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[key] for key in keys))]


def _adjust_record(record: dict[str, Any], params: dict[str, float]) -> dict[str, Any]:
    adjusted = copy.deepcopy(record)
    position_model = adjusted.get("position_model") if isinstance(adjusted.get("position_model"), dict) else {}
    base_score = (
        backtest_engine.as_float(position_model.get("base_position_score"))
        or backtest_engine.as_float(adjusted.get("base_market_position_score"))
        or backtest_engine.as_float(adjusted.get("market_position_score"))
        or 0.0
    )
    base_score *= params.get("opportunity_score_scale", 1.0)
    trend_multiplier = (
        backtest_engine.as_float(position_model.get("trend_multiplier")) or 1.0
    ) + params.get("trend_multiplier_shift", 0.0)
    regime_multiplier = (
        backtest_engine.as_float(position_model.get("regime_multiplier")) or 1.0
    ) + params.get("regime_multiplier_shift", 0.0)
    risk_discount = (
        backtest_engine.as_float(position_model.get("risk_discount"))
        or backtest_engine.as_float(adjusted.get("risk_discount"))
        or 1.0
    ) + params.get("risk_discount_shift", 0.0)
    trend_multiplier = backtest_engine.clamp(trend_multiplier, 0.5, 1.5)
    regime_multiplier = backtest_engine.clamp(regime_multiplier, 0.5, 1.5)
    risk_discount = backtest_engine.clamp(risk_discount, 0.5, 1.0)
    candidate = backtest_engine.clamp(base_score * trend_multiplier * regime_multiplier * risk_discount, 0.0, 100.0)
    cap = _applied_score_cap(adjusted)
    if cap is not None:
        candidate = min(candidate, cap)
    adjusted["market_position_score"] = round(candidate, 2)
    adjusted["position_model"] = {
        **position_model,
        "base_position_score": round(base_score, 2),
        "trend_multiplier": round(trend_multiplier, 4),
        "regime_multiplier": round(regime_multiplier, 4),
        "risk_discount": round(risk_discount, 4),
        "adjusted_position_score": round(candidate, 2),
        "calibration_params": params,
    }
    return adjusted


def _applied_score_cap(record: dict[str, Any]) -> float | None:
    cap = record.get("applied_cap") if isinstance(record.get("applied_cap"), dict) else None
    if cap:
        return backtest_engine.as_float(cap.get("score_cap"))
    caps = record.get("risk_caps", [])
    if not isinstance(caps, list):
        return None
    values = [value for item in caps if isinstance(item, dict) and (value := backtest_engine.as_float(item.get("score_cap"))) is not None]
    return min(values) if values else None


def _objective(metrics: dict[str, Any]) -> float:
    sharpe = backtest_engine.as_float(metrics.get("sharpe_ratio")) or 0.0
    max_drawdown = backtest_engine.as_float(metrics.get("max_drawdown")) or 0.0
    turnover = backtest_engine.as_float(metrics.get("turnover")) or 0.0
    return sharpe - max_drawdown * 2.0 - turnover * 0.05


def _format_best_params(params: dict[str, float]) -> dict[str, Any]:
    return {
        "weights": {"opportunity_score_scale": params.get("opportunity_score_scale")},
        "risk_curve": {"risk_discount_shift": params.get("risk_discount_shift")},
        "regime_multiplier": {"shift": params.get("regime_multiplier_shift")},
        "trend_multiplier": {"shift": params.get("trend_multiplier_shift")},
    }


def main() -> None:
    records = backtest_engine.load_history_records(backtest_engine.DEFAULT_HISTORY_PATH)
    result = run_parameter_calibration(records)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
