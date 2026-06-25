from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import backtest_engine
import causal_analysis
import model_health
import oos_validator
import stress_tester


def compute_robustness(records: list[dict[str, Any]]) -> dict[str, Any]:
    causal = causal_analysis.analyze_causal_impact(records)
    oos = oos_validator.validate_oos(records)
    stress = stress_tester.run_stress_tests(records)
    stability = model_health.stability_score(records)
    oos_score = oos_performance_score(oos)
    causal_score = causal_strength_score(causal)
    stress_score = backtest_engine.as_float(stress.get("survival_score")) or 0.0
    score = score_from_components(
        oos_performance=oos_score,
        causal_strength=causal_score,
        stability_score=stability,
        stress_test_score=stress_score,
    )
    gap = backtest_engine.as_float(oos.get("overfitting_gap")) or 0.0
    return {
        "available": True,
        "version": "robustness_score_v1",
        "robustness_score": round(score, 2),
        "grade": grade(score),
        "deployable": bool(score >= 75 and gap < 0.3 and stress_score > 70),
        "components": {
            "oos_performance": round(oos_score, 2),
            "causal_strength": round(causal_score, 2),
            "stability_score": round(stability, 2),
            "stress_test_score": round(stress_score, 2),
        },
        "causal_impact": causal,
        "oos_validation": oos,
        "stress_test": stress,
        "limitations": [
            "Deployable means validation rules passed; it is not an instruction to trade.",
            "Short real histories should keep deployable=false until enough out-of-sample observations exist.",
        ],
    }


def score_from_components(
    *,
    oos_performance: float,
    causal_strength: float,
    stability_score: float,
    stress_test_score: float,
) -> float:
    return _clamp(
        0.3 * oos_performance + 0.3 * causal_strength + 0.2 * stability_score + 0.2 * stress_test_score,
        0,
        100,
    )


def oos_performance_score(oos: dict[str, Any]) -> float:
    if not oos.get("available"):
        return 35.0
    oos_sharpe = backtest_engine.as_float(oos.get("oos_sharpe")) or 0.0
    gap = max(0.0, backtest_engine.as_float(oos.get("overfitting_gap")) or 0.0)
    leakage_ok = bool((oos.get("leakage_check") or {}).get("ok"))
    score = 55.0 + oos_sharpe * 12.0 - gap * 25.0
    if not leakage_ok:
        score -= 40.0
    return _clamp(score, 0, 100)


def causal_strength_score(causal: dict[str, Any]) -> float:
    if not causal.get("available"):
        return 35.0
    regime = backtest_engine.as_float(causal.get("regime_effect_strength")) or 0.0
    trend = backtest_engine.as_float(causal.get("trend_causal_strength")) or 0.0
    risk = backtest_engine.as_float(causal.get("risk_causal_reduction")) or 0.0
    return _clamp((regime * 0.4 + trend * 0.3 + risk * 0.3) * 100.0, 0, 100)


def grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "A-"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute MyInvestMarket strategy robustness.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(compute_robustness(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
