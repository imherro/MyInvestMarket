from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


TRADING_DAYS_PER_YEAR = 244


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def mean(values: Iterable[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def sample_std(values: Iterable[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    avg = sum(clean) / len(clean)
    variance = sum((value - avg) ** 2 for value in clean) / (len(clean) - 1)
    return math.sqrt(variance)


def nav_from_returns(returns: Iterable[float], start_nav: float = 1.0) -> list[float]:
    nav = [float(start_nav)]
    current = float(start_nav)
    for value in returns:
        if not math.isfinite(value):
            continue
        current *= 1 + value
        nav.append(current)
    return nav


def cagr(nav_curve: Iterable[float | dict[str, Any]], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    values = _nav_values(nav_curve)
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return 0.0
    periods = len(values) - 1
    return (values[-1] / values[0]) ** (periods_per_year / periods) - 1


def sharpe_ratio(
    returns: Iterable[float],
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    clean = [value for value in returns if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    daily_rf = risk_free_rate / periods_per_year
    excess = [value - daily_rf for value in clean]
    vol = sample_std(excess)
    if vol == 0:
        return 0.0
    avg = mean(excess) or 0.0
    return avg / vol * math.sqrt(periods_per_year)


def max_drawdown(nav_curve: Iterable[float | dict[str, Any]]) -> float:
    values = _nav_values(nav_curve)
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def calmar_ratio(cagr_value: float, max_drawdown_value: float) -> float:
    if max_drawdown_value <= 0:
        return 0.0
    return cagr_value / max_drawdown_value


def turnover(position_series: Iterable[float | dict[str, Any]], *, include_initial: bool = True) -> float:
    values = []
    for item in position_series:
        if isinstance(item, dict):
            value = as_float(item.get("applied_position"))
        else:
            value = as_float(item)
        if value is not None:
            values.append(value)
    if not values:
        return 0.0
    previous = 0.0 if include_initial else values[0]
    total = 0.0
    for value in values:
        total += abs(value - previous)
        previous = value
    return total


def win_rate(returns: Iterable[float]) -> float:
    clean = [value for value in returns if math.isfinite(value)]
    if not clean:
        return 0.0
    return sum(1 for value in clean if value > 0) / len(clean)


def performance_summary(
    nav_curve: Iterable[float | dict[str, Any]],
    returns: Iterable[float],
    position_series: Iterable[float | dict[str, Any]],
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> dict[str, float]:
    clean_returns = [value for value in returns if math.isfinite(value)]
    nav_values = _nav_values(nav_curve)
    cagr_value = cagr(nav_values, periods_per_year=periods_per_year)
    mdd = max_drawdown(nav_values)
    return {
        "total_return": (nav_values[-1] / nav_values[0] - 1) if len(nav_values) >= 2 and nav_values[0] else 0.0,
        "cagr": cagr_value,
        "sharpe_ratio": sharpe_ratio(clean_returns, periods_per_year=periods_per_year),
        "max_drawdown": mdd,
        "calmar_ratio": calmar_ratio(cagr_value, mdd),
        "turnover": turnover(position_series),
        "win_rate": win_rate(clean_returns),
        "period_count": float(len(clean_returns)),
    }


def group_return_map(rows: Iterable[dict[str, Any]], group_key: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = str(row.get(group_key) or "unknown")
        value = as_float(row.get("strategy_return"))
        if value is not None:
            grouped[key].append(value)
    result: dict[str, dict[str, float]] = {}
    for key, values in sorted(grouped.items()):
        result[key] = {
            "count": float(len(values)),
            "avg_return": mean(values) or 0.0,
            "hit_rate": win_rate(values),
            "total_return_proxy": sum(values),
        }
    return result


def regime_hit_return_map(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return group_return_map(rows, "market_regime")


def trend_state_alpha_contribution(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    all_returns = [value for row in rows if (value := as_float(row.get("strategy_return"))) is not None]
    baseline = mean(all_returns) or 0.0
    grouped = group_return_map(rows, "trend_state")
    for item in grouped.values():
        item["alpha_vs_all_avg"] = item["avg_return"] - baseline
    return {
        "overall_avg_return": baseline,
        "by_trend_state": grouped,
    }


def risk_cap_reduction_effect(rows: Iterable[dict[str, Any]], *, high_risk_threshold: float = 40.0) -> dict[str, Any]:
    high_risk_rows = [
        row
        for row in rows
        if (as_float(row.get("risk_penalty_score")) or 0.0) >= high_risk_threshold
        or (as_float(row.get("risk_cap_count")) or 0.0) > 0
    ]
    actual_returns = [as_float(row.get("strategy_return")) or 0.0 for row in high_risk_rows]
    baseline_returns = [
        (as_float(row.get("benchmark_return")) or 0.0) * (as_float(row.get("baseline_position")) or 0.0)
        for row in high_risk_rows
    ]
    actual_mdd = max_drawdown(nav_from_returns(actual_returns))
    baseline_mdd = max_drawdown(nav_from_returns(baseline_returns))
    reduction = (baseline_mdd - actual_mdd) / baseline_mdd if baseline_mdd > 0 else 0.0
    return {
        "sample_count": len(high_risk_rows),
        "actual_max_drawdown": actual_mdd,
        "baseline_max_drawdown": baseline_mdd,
        "drawdown_reduction": max(0.0, reduction),
        "actual_return_sum": sum(actual_returns),
        "baseline_return_sum": sum(baseline_returns),
    }


def _nav_values(nav_curve: Iterable[float | dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for item in nav_curve:
        if isinstance(item, dict):
            value = as_float(item.get("nav"))
        else:
            value = as_float(item)
        if value is not None:
            values.append(value)
    return values
