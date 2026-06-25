from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import backtest_engine
import metrics


def analyze_causal_impact(
    records: list[dict[str, Any]] | None = None,
    *,
    rows: list[dict[str, Any]] | None = None,
    permutations: int = 200,
    seed: int = 42,
) -> dict[str, Any]:
    if rows is None:
        rows = (backtest_engine.run_backtest(records or []).get("returns", []) if records is not None else [])
    rows = [row for row in rows or [] if isinstance(row, dict)]
    if not rows:
        return {
            "available": False,
            "reason": "return rows are unavailable",
            "regime_causal_effect": {},
            "trend_causal_strength": 0.0,
            "risk_causal_reduction": 0.0,
        }

    regime_effect = group_effect(rows, "market_regime")
    observed_strength = effect_strength(rows, "market_regime")
    p_value = permutation_p_value(rows, "market_regime", permutations=permutations, seed=seed)
    trend_strength = effect_strength(rows, "trend_state")
    risk_effect = metrics.risk_cap_reduction_effect(rows)
    return {
        "available": True,
        "version": "causal_analysis_v1",
        "method": "observational_proxy_permutation_bootstrap_intervention",
        "regime_causal_effect": regime_effect,
        "regime_permutation_p_value": p_value,
        "regime_effect_strength": observed_strength,
        "trend_causal_strength": trend_strength,
        "risk_causal_reduction": risk_effect.get("drawdown_reduction", 0.0),
        "sample_count": len(rows),
        "limitations": [
            "This is a statistical proxy, not a randomized market experiment.",
            "Small samples should be treated as diagnostics rather than proof.",
        ],
    }


def group_effect(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    all_returns = [value for row in rows if (value := metrics.as_float(row.get("strategy_return"))) is not None]
    baseline = metrics.mean(all_returns) or 0.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = metrics.as_float(row.get("strategy_return"))
        if value is not None:
            grouped[str(row.get(key) or "unknown")].append(value)
    return {name: (metrics.mean(values) or 0.0) - baseline for name, values in sorted(grouped.items())}


def effect_strength(rows: list[dict[str, Any]], key: str) -> float:
    values = [metrics.as_float(row.get("strategy_return")) for row in rows]
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return 0.0
    overall = metrics.mean(clean) or 0.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = metrics.as_float(row.get("strategy_return"))
        if value is not None:
            grouped[str(row.get(key) or "unknown")].append(value)
    between = sum(len(group) * ((metrics.mean(group) or 0.0) - overall) ** 2 for group in grouped.values())
    total = sum((value - overall) ** 2 for value in clean)
    return 0.0 if total == 0 else max(0.0, min(1.0, between / total))


def permutation_p_value(
    rows: list[dict[str, Any]],
    key: str,
    *,
    permutations: int = 200,
    seed: int = 42,
) -> float:
    observed = effect_strength(rows, key)
    if observed == 0 or permutations <= 0:
        return 1.0
    rng = random.Random(seed)
    labels = [str(row.get(key) or "unknown") for row in rows]
    count = 0
    for _ in range(permutations):
        shuffled = labels[:]
        rng.shuffle(shuffled)
        candidate = [dict(row, **{key: label}) for row, label in zip(rows, shuffled)]
        if effect_strength(candidate, key) >= observed:
            count += 1
    return (count + 1) / (permutations + 1)


def shuffle_labels(rows: list[dict[str, Any]], key: str, *, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    labels = [str(row.get(key) or "unknown") for row in rows]
    rng.shuffle(labels)
    return [dict(row, **{key: label}) for row, label in zip(rows, labels)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MyInvestMarket causal proxy analysis.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(analyze_causal_impact(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
