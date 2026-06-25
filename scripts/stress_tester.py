from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import backtest_engine
import metrics


SCENARIOS = {
    "extreme_bull": [0.018, 0.022, 0.025, -0.006, 0.02, 0.015],
    "extreme_bear": [-0.025, -0.03, -0.02, 0.008, -0.035, -0.02],
    "liquidity_crisis": [-0.04, -0.05, 0.01, -0.03, -0.045, 0.005],
    "high_frequency_whipsaw": [0.018, -0.017, 0.016, -0.02, 0.015, -0.018],
}


def run_stress_tests(records: list[dict[str, Any]] | None = None, *, seed: int = 42) -> dict[str, Any]:
    position = latest_position(records or [])
    scenarios = {}
    for name, returns in SCENARIOS.items():
        scenarios[name] = scenario_result(name, returns, position, seed=seed)
    worst_name = max(scenarios, key=lambda key: scenarios[key]["max_drawdown"])
    worst = scenarios[worst_name]
    survival_score = max(0.0, min(100.0, 100.0 - worst["max_drawdown"] * 300.0 - abs(min(0.0, worst["total_return"])) * 100.0))
    return {
        "available": True,
        "version": "stress_tester_v1",
        "position_used": position,
        "worst_regime": worst_name,
        "max_drawdown": worst["max_drawdown"],
        "survival_score": round(survival_score, 2),
        "scenarios": scenarios,
    }


def scenario_result(name: str, returns: list[float], position: float, *, seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed + len(name))
    adjusted = [value + rng.uniform(-0.001, 0.001) for value in returns]
    strategy_returns = [value * position for value in adjusted]
    nav = metrics.nav_from_returns(strategy_returns)
    max_drawdown = metrics.max_drawdown(nav)
    return {
        "triggered": max_drawdown > 0.02 or min(adjusted) < -0.03,
        "total_return": nav[-1] / nav[0] - 1 if nav and nav[0] else 0.0,
        "max_drawdown": max_drawdown,
        "nav_curve": nav,
    }


def latest_position(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.5
    latest = sorted(records, key=lambda row: str(row.get("scored_at", "")))[-1]
    return backtest_engine.position_score_to_weight(latest.get("market_position_score"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MyInvestMarket stress tests.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(run_stress_tests(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
