from __future__ import annotations

from typing import Any


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


def scale(value: float | None, low: float, high: float, max_score: float = 100) -> float:
    if value is None:
        return max_score / 2
    if high == low:
        return max_score / 2
    return clamp((value - low) / (high - low), 0, 1) * max_score


def normalize_annual_vol(value: Any) -> float | None:
    number = as_float(value)
    if number is None:
        return None
    if number > 1:
        return number / 100
    return number


def module_score_pct(modules: dict[str, Any], key: str) -> float | None:
    module = modules.get(key, {}) if isinstance(modules.get(key), dict) else {}
    score_pct = as_float(module.get("score_pct"))
    if score_pct is not None:
        return score_pct / 100 if score_pct > 1 else score_pct
    score = as_float(module.get("score"))
    weight = as_float(module.get("weight"))
    if score is None or not weight:
        return None
    return clamp(score / weight, 0, 1)


def risk_band(score: float) -> str:
    if score <= 20:
        return "安全"
    if score <= 40:
        return "中性风险"
    if score <= 70:
        return "高风险"
    return "极端风险"


def risk_discount(score: float) -> float:
    if score <= 20:
        return 1.0
    if score <= 40:
        return round2(1.0 - (score - 20) * 0.004) or 1.0
    if score <= 70:
        return round2(0.92 - (score - 40) * 0.004) or 0.92
    return round2(max(0.65, 0.80 - (score - 70) * 0.005)) or 0.65


def risk_component(name: str, score: float, weight: float, evidence: dict[str, Any], note: str) -> dict[str, Any]:
    weighted_score = score * weight
    return {
        "name": name,
        "score": round2(score),
        "weight": weight,
        "weighted_score": round2(weighted_score),
        "evidence": evidence,
        "note": note,
    }


def compute_risk_engine(snapshot: dict[str, Any], modules: dict[str, Any], crowding: dict[str, Any]) -> dict[str, Any]:
    """Compute a continuous risk penalty score before hard risk-cap constraints."""

    valuation_pct = module_score_pct(modules, "valuation")
    valuation_risk = (1 - valuation_pct) * 100 if valuation_pct is not None else 50

    realized_vol = normalize_annual_vol(((snapshot.get("volatility", {}) or {}).get("market", {}) or {}).get("realized_vol_30d"))
    volatility_risk = scale(realized_vol, 0.15, 0.40, 100)

    crowding_penalty = as_float(crowding.get("penalty")) or 0
    crowding_risk = scale(crowding_penalty, 0, 30, 100)

    capital_flow = snapshot.get("capital_flow", {}) or {}
    northbound = as_float(capital_flow.get("northbound_net_inflow_100m_cny"))
    main_flow = as_float(capital_flow.get("main_net_inflow_100m_cny"))
    flow_reversal_risk = 50.0
    if northbound is not None and main_flow is not None:
        if northbound <= -50 and main_flow <= -800:
            flow_reversal_risk = 100.0
        elif northbound > 0 and main_flow <= -800:
            flow_reversal_risk = 88.0
        elif main_flow <= -800:
            flow_reversal_risk = 75.0
        elif northbound < 0 and main_flow < 0:
            flow_reversal_risk = 65.0
        elif northbound > 0 and main_flow > 0:
            flow_reversal_risk = 10.0
        else:
            flow_reversal_risk = 35.0

    components = [
        risk_component(
            "valuation_risk",
            valuation_risk,
            0.35,
            {"valuation_score_pct": round2(valuation_pct)},
            "Valuation risk rises as valuation score falls.",
        ),
        risk_component(
            "volatility_risk",
            volatility_risk,
            0.25,
            {"realized_volatility_30d": round2(realized_vol)},
            "Volatility risk rises with 30-day realized annualized volatility.",
        ),
        risk_component(
            "crowding_risk",
            crowding_risk,
            0.25,
            {"crowding_penalty": round2(crowding_penalty)},
            "Crowding risk reuses the existing gradient crowding penalty as one component.",
        ),
        risk_component(
            "flow_reversal_risk",
            flow_reversal_risk,
            0.15,
            {
                "northbound_net_inflow_100m_cny": round2(northbound),
                "main_net_inflow_100m_cny": round2(main_flow),
            },
            "Flow reversal risk rises when main money or northbound money exits.",
        ),
    ]
    total = round2(sum(as_float(item.get("weighted_score")) or 0 for item in components)) or 0.0
    discount = risk_discount(total)
    return {
        "version": "risk_engine_v1",
        "risk_penalty_score": total,
        "risk_level": risk_band(total),
        "risk_discount": discount,
        "components": components,
        "inputs": {
            "valuation_score_pct": round2(valuation_pct),
            "realized_volatility_30d": round2(realized_vol),
            "crowding_penalty": round2(crowding_penalty),
            "northbound_net_inflow_100m_cny": round2(northbound),
            "main_net_inflow_100m_cny": round2(main_flow),
        },
    }
