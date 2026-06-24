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
    return record
