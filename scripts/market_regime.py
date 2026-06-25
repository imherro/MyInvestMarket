from __future__ import annotations

from typing import Any


REGIME_LABELS = {
    "accumulation": "底部吸筹",
    "expansion": "主升扩张",
    "distribution": "高位派发",
    "contraction": "下行收缩",
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


def signal(name: str, value: Any, direction: str, scores: dict[str, float], note: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "direction": direction,
        "scores": {key: round2(score) for key, score in scores.items()},
        "note": note,
    }


def compute_market_regime(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify the broad market regime from snapshot-only structural signals.

    This layer is descriptive, not predictive. It intentionally uses only fields
    already present in the market snapshot so the classifier is reproducible in
    historical score records and daily automation runs.
    """

    breadth = snapshot.get("breadth", {}) or {}
    capital_flow = snapshot.get("capital_flow", {}) or {}
    valuation = ((snapshot.get("valuation", {}) or {}).get("market", {}) or {})
    indices = ((snapshot.get("market", {}) or {}).get("indices", {}) or {})
    turnover = capital_flow.get("turnover_distribution", {}) or {}

    advancers = as_float(breadth.get("advancers")) or 0
    decliners = as_float(breadth.get("decliners")) or 0
    total = as_float(breadth.get("total")) or (advancers + decliners)
    advancer_ratio = advancers / total if total else None
    industry_up_ratio = as_float(breadth.get("industry_up_ratio"))
    median_pct_change = as_float(breadth.get("median_pct_change"))
    strong_advancers = as_float(breadth.get("strong_advancers_gt3_pct"))
    strong_decliners = as_float(breadth.get("strong_decliners_lt_minus3_pct"))
    avg_volume_ratio = None
    volume_values = [
        as_float(row.get("volume_ratio_5d"))
        for row in indices.values()
        if isinstance(row, dict) and as_float(row.get("volume_ratio_5d")) is not None
    ]
    if volume_values:
        avg_volume_ratio = sum(value for value in volume_values if value is not None) / len(volume_values)
    mid_share = as_float((turnover.get("mid_cap") or {}).get("share")) or 0
    small_share = as_float((turnover.get("small_cap") or {}).get("share")) or 0
    active_turnover_share = mid_share + small_share
    valuation_score = as_float(valuation.get("valuation_score"))
    northbound = as_float(capital_flow.get("northbound_net_inflow_100m_cny"))
    main_flow = as_float(capital_flow.get("main_net_inflow_100m_cny"))

    scores = {
        "accumulation": 0.0,
        "expansion": 0.0,
        "distribution": 0.0,
        "contraction": 0.0,
    }
    signals: list[dict[str, Any]] = []

    breadth_pressure = 0.0
    if advancer_ratio is not None:
        if advancer_ratio >= 0.58:
            scores["expansion"] += 2.0
            breadth_pressure += 1
        elif advancer_ratio <= 0.35:
            scores["contraction"] += 2.0
            scores["accumulation"] += 0.8
            breadth_pressure -= 1
    if industry_up_ratio is not None:
        if industry_up_ratio >= 0.58:
            scores["expansion"] += 1.5
            breadth_pressure += 1
        elif industry_up_ratio <= 0.30:
            scores["contraction"] += 1.5
            scores["distribution"] += 0.7
            breadth_pressure -= 1
    if median_pct_change is not None:
        if median_pct_change >= 0.6:
            scores["expansion"] += 1.0
        elif median_pct_change <= -0.6:
            scores["contraction"] += 1.0
            scores["accumulation"] += 0.4
    if strong_advancers is not None and strong_decliners is not None:
        strong_spread = strong_advancers - strong_decliners
        if strong_spread >= 0.08:
            scores["expansion"] += 1.0
        elif strong_spread <= -0.08:
            scores["contraction"] += 1.0
    signals.append(
        signal(
            "breadth",
            {
                "advancer_ratio": round2(advancer_ratio),
                "industry_up_ratio": round2(industry_up_ratio),
                "median_pct_change": round2(median_pct_change),
            },
            "positive" if breadth_pressure > 0 else "negative" if breadth_pressure < 0 else "mixed",
            {
                "accumulation": scores["accumulation"],
                "expansion": scores["expansion"],
                "distribution": scores["distribution"],
                "contraction": scores["contraction"],
            },
            "Width expansion supports expansion; weak breadth supports contraction or distribution.",
        )
    )

    before = dict(scores)
    if avg_volume_ratio is not None:
        if 0.95 <= avg_volume_ratio <= 1.25:
            scores["expansion"] += 1.2
        elif avg_volume_ratio < 0.82:
            scores["contraction"] += 1.2
            scores["accumulation"] += 0.5
        elif avg_volume_ratio > 1.45:
            scores["distribution"] += 1.2
    if active_turnover_share >= 0.68:
        scores["expansion"] += 0.8
    elif active_turnover_share <= 0.52:
        scores["contraction"] += 0.7
    liquidity_delta = {key: scores[key] - before[key] for key in scores}
    signals.append(
        signal(
            "liquidity",
            {
                "avg_volume_ratio": round2(avg_volume_ratio),
                "active_turnover_share": round2(active_turnover_share),
            },
            "positive" if liquidity_delta["expansion"] > liquidity_delta["contraction"] else "negative" if liquidity_delta["contraction"] > 0 else "mixed",
            liquidity_delta,
            "Moderate volume and active turnover support expansion; shrinkage supports contraction.",
        )
    )

    before = dict(scores)
    if valuation_score is not None:
        if valuation_score >= 70:
            scores["accumulation"] += 2.0
            if breadth_pressure > 0:
                scores["expansion"] += 0.8
        elif valuation_score <= 25:
            scores["distribution"] += 2.0
        elif valuation_score <= 40:
            scores["distribution"] += 0.8
    valuation_delta = {key: scores[key] - before[key] for key in scores}
    signals.append(
        signal(
            "valuation",
            {"valuation_score": round2(valuation_score)},
            "cheap" if valuation_score is not None and valuation_score >= 70 else "expensive" if valuation_score is not None and valuation_score <= 25 else "neutral",
            valuation_delta,
            "Cheap valuation supports accumulation; expensive valuation supports distribution risk.",
        )
    )

    before = dict(scores)
    if northbound is not None:
        if northbound >= 50:
            scores["expansion"] += 0.7
        elif northbound <= -50:
            scores["contraction"] += 0.7
    if main_flow is not None:
        if main_flow >= 200:
            scores["expansion"] += 1.2
        elif main_flow <= -800:
            scores["distribution"] += 1.0
            scores["contraction"] += 1.2
            if valuation_score is not None and valuation_score <= 25:
                scores["distribution"] += 2.0
    if northbound is not None and main_flow is not None and northbound > 0 and main_flow < 0:
        scores["distribution"] += 1.2
    if avg_volume_ratio is not None and valuation_score is not None and avg_volume_ratio > 1.45 and valuation_score <= 25:
        scores["distribution"] += 1.0
    flow_delta = {key: scores[key] - before[key] for key in scores}
    signals.append(
        signal(
            "capital_flow",
            {
                "northbound_net_inflow_100m_cny": round2(northbound),
                "main_net_inflow_100m_cny": round2(main_flow),
            },
            "positive" if flow_delta["expansion"] > flow_delta["contraction"] + flow_delta["distribution"] else "negative" if flow_delta["contraction"] or flow_delta["distribution"] else "mixed",
            flow_delta,
            "Persistent inflow supports expansion; main outflow or divergence supports distribution/contraction.",
        )
    )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    regime = ranked[0][0]
    top_score = ranked[0][1]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    total_score = sum(scores.values()) or 1.0
    confidence = clamp((top_score - second_score) / max(top_score, 1.0), 0.0, 1.0)
    confidence = round(max(confidence, top_score / total_score * 0.5), 2)

    return {
        "version": "market_regime_v1",
        "regime": regime,
        "label": REGIME_LABELS[regime],
        "confidence": confidence,
        "scores": {key: round2(value) for key, value in scores.items()},
        "signals": signals,
        "inputs": {
            "advancer_ratio": round2(advancer_ratio),
            "industry_up_ratio": round2(industry_up_ratio),
            "median_pct_change": round2(median_pct_change),
            "avg_volume_ratio": round2(avg_volume_ratio),
            "active_turnover_share": round2(active_turnover_share),
            "valuation_score": round2(valuation_score),
            "northbound_net_inflow_100m_cny": round2(northbound),
            "main_net_inflow_100m_cny": round2(main_flow),
        },
    }
