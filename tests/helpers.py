from __future__ import annotations

from typing import Any

import market_scoring


def attach_allocation_policy(record: dict[str, Any]) -> dict[str, Any]:
    modules = record.get("modules") if isinstance(record.get("modules"), dict) else {}
    if not modules:
        modules = {
            key: {
                "label": meta["label"],
                "weight": meta["weight"],
                "score": meta["weight"] * 0.5,
                "score_pct": 50,
                "summary": "test",
                "evidence": [],
                "metrics": {},
            }
            for key, meta in market_scoring.MODULES.items()
        }
        record["modules"] = modules

    allocation = market_scoring.allocation_policy(
        record.get("market_position_score", 35),
        record.get("market_opportunity_score", 50),
        record.get("pre_cap_market_position_score", record.get("market_position_score", 35)),
        record.get("recommended_equity_position_range", "20%-40%"),
        modules,
        record.get("crowding", {"penalty": record.get("crowding_penalty", 0)}),
        {},
        record.get("risk_caps", []),
    )
    record["allocation_policy_version"] = market_scoring.ALLOCATION_POLICY_VERSION
    record["allocation_state"] = allocation["state"]
    record["allocation_policy"] = allocation
    record["sleeve_allocation"] = allocation["sleeves"]
    record.setdefault("market_regime_code", "expansion")
    record.setdefault("market_regime_label", "主升扩张")
    record.setdefault(
        "market_regime_layer",
        {
            "version": "market_regime_v1",
            "regime": record["market_regime_code"],
            "label": record["market_regime_label"],
            "confidence": 0.6,
            "scores": {
                "accumulation": 1.0,
                "expansion": 3.0,
                "distribution": 0.5,
                "contraction": 0.5,
            },
            "signals": [
                {
                    "name": "test",
                    "value": None,
                    "direction": "mixed",
                    "scores": {"expansion": 1.0},
                    "note": "test fixture",
                }
            ],
            "inputs": {},
        },
    )
    record.setdefault("trend_state", "early_trend")
    record.setdefault("trend_state_label", "趋势初期")
    record.setdefault("trend_strength", 60.0)
    record.setdefault("trend_duration", 6)
    record.setdefault(
        "market_trend_layer",
        {
            "version": "market_trend_v1",
            "trend_state": record["trend_state"],
            "label": record["trend_state_label"],
            "trend_strength": record["trend_strength"],
            "trend_duration": record["trend_duration"],
            "signals": [
                {
                    "name": "test",
                    "value": None,
                    "score": 1.0,
                    "note": "test fixture",
                }
            ],
            "inputs": {},
        },
    )
    record.setdefault("risk_penalty_score", 25.0)
    record.setdefault("risk_discount", 0.98)
    record.setdefault("risk_adjusted_market_position_score", record.get("pre_cap_market_position_score", record.get("market_position_score", 35)))
    record.setdefault(
        "risk_engine",
        {
            "version": "risk_engine_v1",
            "risk_penalty_score": record["risk_penalty_score"],
            "risk_level": "中性风险",
            "risk_discount": record["risk_discount"],
            "components": [
                {
                    "name": "test",
                    "score": record["risk_penalty_score"],
                    "weight": 1.0,
                    "weighted_score": record["risk_penalty_score"],
                    "evidence": {},
                    "note": "test fixture",
                }
            ],
            "inputs": {},
        },
    )
    return record
