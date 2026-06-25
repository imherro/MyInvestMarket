from __future__ import annotations

from typing import Any


TREND_LABELS = {
    "early_trend": "趋势初期",
    "strong_trend": "强趋势",
    "late_trend": "趋势末期",
    "weakening_trend": "趋势转弱",
}


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def scale(value: float | None, low: float, high: float, max_score: float = 100) -> float:
    if value is None:
        return max_score / 2
    if high == low:
        return max_score / 2
    return clamp((value - low) / (high - low), 0, 1) * max_score


def index_values(snapshot: dict[str, Any], key: str) -> list[float]:
    indices = ((snapshot.get("market", {}) or {}).get("indices", {}) or {})
    return [
        value
        for row in indices.values()
        if isinstance(row, dict) and (value := as_float(row.get(key))) is not None
    ]


def advancer_ratio_pct(snapshot: dict[str, Any]) -> float | None:
    breadth = snapshot.get("breadth", {}) or {}
    total = as_float(breadth.get("total"))
    advancers = as_float(breadth.get("advancers"))
    if not total or advancers is None:
        return None
    return advancers / total * 100


def liquidity_signal(snapshot: dict[str, Any], rolling: dict[str, Any]) -> dict[str, float | None]:
    current_volume_ratio = mean(index_values(snapshot, "volume_ratio_5d"))
    liquidity = rolling.get("liquidity", {}) if isinstance(rolling.get("liquidity"), dict) else {}
    return {
        "avg_volume_ratio": current_volume_ratio,
        "avg_volume_ratio_5d": as_float(liquidity.get("avg_volume_ratio_5d")),
        "avg_volume_ratio_slope_5d": as_float(liquidity.get("avg_volume_ratio_slope_5d")),
    }


def trend_signal(name: str, value: Any, score: float, note: str) -> dict[str, Any]:
    return {"name": name, "value": value, "score": round2(score), "note": note}


def compute_market_trend(snapshot: dict[str, Any], modules: dict[str, Any], rolling: dict[str, Any]) -> dict[str, Any]:
    """Describe trend maturity from index, breadth persistence, and liquidity slope."""

    index_module = modules.get("index_trend", {}) if isinstance(modules.get("index_trend"), dict) else {}
    breadth_module = modules.get("breadth", {}) if isinstance(modules.get("breadth"), dict) else {}
    liquidity_module = modules.get("liquidity", {}) if isinstance(modules.get("liquidity"), dict) else {}
    rolling_breadth = rolling.get("breadth", {}) if isinstance(rolling.get("breadth"), dict) else {}
    rolling_liquidity = liquidity_signal(snapshot, rolling)

    index_score_pct = as_float(index_module.get("score_pct"))
    breadth_score_pct = as_float(breadth_module.get("score_pct"))
    liquidity_score_pct = as_float(liquidity_module.get("score_pct"))
    ret5 = mean(index_values(snapshot, "return_5d_pct"))
    ret20 = mean(index_values(snapshot, "return_20d_pct"))
    ma20_deviation = mean(index_values(snapshot, "ma20_deviation_pct"))
    current_breadth_pct = advancer_ratio_pct(snapshot)
    breadth_5d_pct = as_float(rolling_breadth.get("advancer_ratio_5d_avg_pct"))
    volume_slope = as_float(rolling_liquidity.get("avg_volume_ratio_slope_5d"))
    avg_volume_ratio = as_float(rolling_liquidity.get("avg_volume_ratio"))

    index_component = scale(index_score_pct, 35, 85, 40)
    breadth_persistence = mean([value for value in [breadth_score_pct, breadth_5d_pct, current_breadth_pct] if value is not None])
    breadth_component = scale(breadth_persistence, 35, 70, 25)
    liquidity_base = liquidity_score_pct if liquidity_score_pct is not None else 50
    liquidity_slope_bonus = scale(volume_slope, -0.18, 0.18, 10)
    liquidity_component = scale(liquidity_base, 35, 85, 15) + liquidity_slope_bonus
    momentum_component = scale(ret20, -5, 8, 15) * 0.65 + scale(ret5, -3, 5, 15) * 0.35
    trend_strength = round2(index_component + breadth_component + liquidity_component + momentum_component) or 0.0

    duration_score = 0
    if ret20 is not None and ret20 > 0:
        duration_score += 8
    if index_score_pct is not None and index_score_pct >= 65:
        duration_score += 6
    if breadth_5d_pct is not None and breadth_5d_pct >= 55:
        duration_score += 4
    if avg_volume_ratio is not None and avg_volume_ratio >= 1.0:
        duration_score += 2
    trend_duration = min(duration_score, 20)

    late_pressure = 0
    if ma20_deviation is not None and ma20_deviation >= 6:
        late_pressure += 1
    if ret5 is not None and ret5 >= 4 and breadth_5d_pct is not None and breadth_5d_pct < 50:
        late_pressure += 1
    if volume_slope is not None and volume_slope < -0.08 and trend_strength >= 60:
        late_pressure += 1

    weakening_pressure = 0
    if ret5 is not None and ret5 < 0:
        weakening_pressure += 1
    if current_breadth_pct is not None and current_breadth_pct < 45:
        weakening_pressure += 1
    if volume_slope is not None and volume_slope < -0.12:
        weakening_pressure += 1

    if weakening_pressure >= 2 and trend_strength < 65:
        trend_state = "weakening_trend"
    elif late_pressure >= 2:
        trend_state = "late_trend"
    elif trend_strength >= 72 and trend_duration >= 12:
        trend_state = "strong_trend"
    elif trend_strength >= 52:
        trend_state = "early_trend"
    else:
        trend_state = "weakening_trend"

    signals = [
        trend_signal(
            "index_trend",
            {"score_pct": round2(index_score_pct), "return_5d_pct": round2(ret5), "return_20d_pct": round2(ret20)},
            index_component,
            "Index trend score and 5/20 day momentum define the trend backbone.",
        ),
        trend_signal(
            "breadth_persistence",
            {
                "current_advancer_ratio_pct": round2(current_breadth_pct),
                "advancer_ratio_5d_avg_pct": round2(breadth_5d_pct),
                "breadth_score_pct": round2(breadth_score_pct),
            },
            breadth_component,
            "Breadth persistence separates broad trend from narrow index movement.",
        ),
        trend_signal(
            "liquidity_slope",
            {
                "avg_volume_ratio": round2(avg_volume_ratio),
                "avg_volume_ratio_slope_5d": round2(volume_slope),
                "liquidity_score_pct": round2(liquidity_score_pct),
            },
            liquidity_component,
            "Liquidity expansion supports early and strong trends; contraction flags weakening.",
        ),
        trend_signal(
            "trend_maturity",
            {"trend_duration": trend_duration, "ma20_deviation_pct": round2(ma20_deviation)},
            momentum_component,
            "Duration and MA20 deviation distinguish early trend from late trend.",
        ),
    ]

    return {
        "version": "market_trend_v1",
        "trend_state": trend_state,
        "label": TREND_LABELS[trend_state],
        "trend_strength": trend_strength,
        "trend_duration": trend_duration,
        "signals": signals,
        "inputs": {
            "index_score_pct": round2(index_score_pct),
            "breadth_score_pct": round2(breadth_score_pct),
            "liquidity_score_pct": round2(liquidity_score_pct),
            "return_5d_pct": round2(ret5),
            "return_20d_pct": round2(ret20),
            "ma20_deviation_pct": round2(ma20_deviation),
            "current_advancer_ratio_pct": round2(current_breadth_pct),
            "breadth_5d_avg_pct": round2(breadth_5d_pct),
            "avg_volume_ratio": round2(avg_volume_ratio),
            "avg_volume_ratio_slope_5d": round2(volume_slope),
        },
    }
