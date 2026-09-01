"""Reduce the frozen Evidence Vector into PIT-safe domain states.

This layer is descriptive and deliberately does not emit a market score,
regime, allocation, position, or trading signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVIDENCE_PATH = DATA / "cycle_engine_features_v1.json"
EVIDENCE_AUDIT_PATH = DATA / "cycle_engine_features_audit_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_domain_signals_v1.json"
AUDIT_PATH = DATA / "cycle_engine_domain_signals_audit_v1.json"
MIN_HISTORY = 36
HORIZONS = (6, 12, 24)
INDEXES = ("csi300", "csi500", "csi1000")
FROZEN_PHASE1_EVIDENCE_SHA256 = "d617e0226f9957a696f202800fb7034c665e541eabb632891904d12f6aed8d23"
FROZEN_EVIDENCE_SHA256 = FROZEN_PHASE1_EVIDENCE_SHA256

FORBIDDEN_OUTPUT_KEYS = {
    "cycle_score", "market_score", "bull_bear_score", "regime", "cycle_regime",
    "cycle_state", "recommended_position", "equity_position", "allocation",
    "buy_signal", "sell_signal", "trade_signal", "position", "weight",
}


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def load_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    audit = json.loads(EVIDENCE_AUDIT_PATH.read_text(encoding="utf-8"))
    return evidence, audit


def feature(row: dict[str, Any], path: str) -> dict[str, Any]:
    return row.get("features", {}).get(path, {})


def raw(row: dict[str, Any], path: str) -> Any:
    return feature(row, path).get("raw_value")


def rank(row: dict[str, Any], path: str) -> float | None:
    value = feature(row, path).get("expanding_rank_pct")
    return float(value) if value is not None else None


def ready(row: dict[str, Any], path: str) -> bool:
    return feature(row, path).get("normalization_history_ready") is True


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + mon - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def band(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value <= 30:
        return "cheap"
    if value >= 70:
        return "expensive"
    return "neutral"


def erp_band(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value >= 70:
        return "cheap"
    if value <= 30:
        return "expensive"
    return "neutral"


def component(path: str, row: dict[str, Any]) -> dict[str, Any]:
    value = rank(row, path)
    is_ready = value is not None and ready(row, path)
    state = "unavailable" if value is None else (band(value) if is_ready else "insufficient_history")
    return {"available": value is not None, "rank": value, "ready": is_ready, "state": state}


def valuation(row: dict[str, Any]) -> dict[str, Any]:
    components = {
        "csi300": {"pe": component("valuation.indices.csi300.pe_ttm.percentile_expanding", row), "pb": component("valuation.indices.csi300.pb.percentile_expanding", row)},
        "csi500": {"pe": component("valuation.indices.csi500.pe_ttm.percentile_expanding", row), "pb": component("valuation.indices.csi500.pb.percentile_expanding", row)},
        "csi1000": {"available": False, "state": "unavailable", "reason_code": "frozen_valuation_unavailable_no_proxy"},
        "erp": component("valuation.csi300_erp_pct.value", row),
    }
    states = []
    for name in ("csi300", "csi500"):
        values = [item["rank"] for item in components[name].values() if item["rank"] is not None]
        complete = len(values) == 2
        component_ready = complete and all(components[name][field]["ready"] for field in ("pe", "pb"))
        state = band(sum(values) / 2) if component_ready else ("unavailable" if not complete else "insufficient_history")
        components[name]["state"] = state
        components[name]["available"] = complete
        components[name]["ready"] = component_ready
        states.append(state)
    components["erp"]["state"] = erp_band(components["erp"]["rank"])
    if not components["erp"]["available"]:
        components["erp"]["state"] = "unavailable"
    elif not ready(row, "valuation.csi300_erp_pct.value"):
        components["erp"]["state"] = "insufficient_history"
    components["erp"]["ready"] = components["erp"]["available"] and ready(row, "valuation.csi300_erp_pct.value")
    states.append(components["erp"]["state"])
    participating = [name for name in ("csi300", "csi500", "erp") if components[name]["ready"]]
    unavailable = ["csi1000"] + [name for name in ("csi300", "csi500", "erp") if not components[name]["ready"]]
    formal_states = [components[name]["state"] for name in participating]
    cheap = formal_states.count("cheap")
    expensive = formal_states.count("expensive")
    model_ready = all(components[name]["ready"] for name in ("csi300", "csi500", "erp"))
    state = "insufficient_history" if not model_ready else ("cheap" if cheap >= 2 else ("expensive" if expensive >= 2 else "neutral"))
    return {"state": state, "ready": model_ready, "cheap_count": cheap, "neutral_count": formal_states.count("neutral"), "expensive_count": expensive, "disagreement": len(set(formal_states)) > 1, "participating_components": participating, "unavailable_components": unavailable, "components": components, "reason_codes": [f"{name}_{value}" for name, value in zip(("csi300", "csi500", "erp"), states)] + (["valuation_inputs_ready"] if model_ready else ["insufficient_history"])}


def earnings(row: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    growth_paths = ("earnings.all_a_net_profit_yoy_pct.value", "earnings.nonfinancial_a_net_profit_yoy_pct.value")
    quality_paths = ("earnings.all_a_roe_ttm_pct.value", "earnings.nonfinancial_a_roe_ttm_pct.value")
    prior = rows.get(shift_month(row["month"], -3))

    def pair(paths: tuple[str, str], name: str) -> dict[str, Any]:
        current_ranks = [rank(row, path) for path in paths]
        current_raw = [raw(row, path) for path in paths]
        prior_ranks = [rank(prior, path) if prior else None for path in paths]
        rank_ok = all(value is not None for value in current_ranks)
        change = (sum(current_ranks) / 2 - sum(prior_ranks) / 2) if rank_ok and all(value is not None for value in prior_ranks) else None
        return {"raw_level": sum(current_raw) / 2 if all(isinstance(value, (int, float)) for value in current_raw) else None, "rank": sum(current_ranks) / 2 if rank_ok else None, "rank_change_3m": change, "ready": all(ready(row, path) for path in paths), "reason_codes": [f"{name}_t_minus_3_natural_month" if change is not None else f"{name}_change_unavailable"]}

    growth, quality = pair(growth_paths, "growth"), pair(quality_paths, "quality")
    state = "insufficient_history"
    if growth["ready"] and quality["ready"]:
        if growth["rank_change_3m"] is not None and quality["rank_change_3m"] is not None:
            if growth["rank_change_3m"] < 0 and quality["rank_change_3m"] < 0:
                state = "deterioration"
            elif growth["raw_level"] is not None and growth["raw_level"] > 0 and growth["rank"] >= 50 and quality["rank"] >= 50 and growth["rank_change_3m"] >= 0 and quality["rank_change_3m"] >= 0:
                state = "expansion"
            elif growth["raw_level"] is not None and growth["raw_level"] > 0 and growth["rank_change_3m"] > 0 and quality["rank_change_3m"] >= 0:
                state = "recovery"
            elif growth["raw_level"] is not None and growth["raw_level"] <= 0 and growth["rank_change_3m"] > 0 and quality["rank_change_3m"] >= 0:
                state = "bottoming"
            else:
                state = "mixed"
    return {"state": state, "ready": growth["ready"] and quality["ready"], "growth_raw_level": growth["raw_level"], "growth_rank": growth["rank"], "growth_rank_change_3m": growth["rank_change_3m"], "quality_rank": quality["rank"], "quality_rank_change_3m": quality["rank_change_3m"], "reason_codes": growth["reason_codes"] + quality["reason_codes"]}


def macro_confirmation(row: dict[str, Any]) -> dict[str, Any]:
    paths = ("earnings.pmi.above_50", "earnings.pmi.change_1m", "earnings.pmi.change_3m")
    available = all(raw(row, path) is not None for path in paths)
    model_ready = all(ready(row, path) for path in paths)
    above, one, three = (raw(row, path) for path in paths)
    state = "insufficient_data"
    if available and model_ready:
        if above is True and (one > 0 or three > 0):
            state = "positive"
        elif above is False and (one < 0 or three < 0):
            state = "negative"
        else:
            state = "mixed"
    return {"state": state, "ready": model_ready, "reason_codes": ["pmi_confirmation_only", "insufficient_data" if not available else "pmi_inputs_present"]}


def trend_index(row: dict[str, Any], index: str) -> dict[str, Any]:
    prefix = f"trend.indices.{index}."
    paths = {"deviation": prefix + "ma250_deviation_pct.value", "above": prefix + "above_ma250.value", "slope": prefix + "ma250_slope_3m_pct.value", "return_6m": prefix + "return_6m_pct.value", "return_12m": prefix + "return_12m_pct.value", "drawdown": prefix + "drawdown_12m_high_pct.value"}
    model_ready = all(ready(row, path) for path in paths.values())
    unavailable = [name for name, path in paths.items() if raw(row, path) is None]
    state = "insufficient_history"
    if model_ready and not unavailable:
        if raw(row, paths["above"]) is True and raw(row, paths["slope"]) > 0 and raw(row, paths["return_12m"]) > 0 and (rank(row, paths["deviation"]) >= 80 or rank(row, paths["return_12m"]) >= 80):
            state = "extended"
        elif raw(row, paths["above"]) is True and raw(row, paths["slope"]) > 0 and raw(row, paths["return_12m"]) > 0:
            state = "up"
        elif raw(row, paths["above"]) is False and raw(row, paths["slope"]) > 0 and raw(row, paths["return_6m"]) > 0:
            state = "bottoming"
        elif raw(row, paths["above"]) is False and raw(row, paths["slope"]) <= 0 and (raw(row, paths["return_12m"]) < 0 or rank(row, paths["drawdown"]) <= 20):
            state = "damaged"
        else:
            state = "mixed"
    return {"state": state, "ready": model_ready and not unavailable, "unavailable_features": unavailable, "reason_codes": [f"{index}_six_feature_reduction"]}


def trend(row: dict[str, Any]) -> dict[str, Any]:
    indexes = {index: trend_index(row, index) for index in INDEXES}
    participating = [index for index, item in indexes.items() if item["ready"]]
    if "csi300" not in participating or "csi500" not in participating:
        state = "insufficient_history"
    else:
        states = [indexes[index]["state"] for index in participating]
        damaged = states.count("damaged")
        extended = states.count("extended")
        up = sum(value in ("up", "extended") for value in states)
        bottoming = sum(value in ("bottoming", "up") for value in states)
        if damaged >= 2:
            state = "damaged"
        elif extended >= 2:
            state = "extended"
        elif up >= 2:
            state = "up"
        elif bottoming >= 2 and "bottoming" in states and damaged < 2:
            state = "bottoming"
        else:
            state = "mixed"
    return {"state": state, "ready": state != "insufficient_history", "participating_indices": participating, "index_states": {index: item["state"] for index, item in indexes.items()}, "dispersion": len({indexes[index]["state"] for index in participating}), "unavailable_indices": [index for index, item in indexes.items() if not item["ready"]], "csi300": indexes["csi300"], "csi500": indexes["csi500"], "csi1000": indexes["csi1000"], "reason_codes": ["six_features_to_index_state", "index_states_to_broad_state"]}


def sentiment(row: dict[str, Any]) -> dict[str, Any]:
    path = "sentiment.a_fear.fear_score"
    value = raw(row, path)
    if value is None:
        state = "unavailable"
    elif value < 20:
        state = "calm"
    elif value < 40:
        state = "normal"
    elif value < 60:
        state = "watch"
    elif value < 80:
        state = "high_fear"
    else:
        state = "extreme_fear"
    observations = feature(row, path).get("normalization_history_observations")
    return {"state": state, "score": value, "available": value is not None, "observations": observations, "normalization_history_observations": observations, "model_ready": ready(row, path), "role": "overlay_only"}


def reduction_policy(paths: set[str]) -> dict[str, str]:
    policy = {}
    for index in ("csi300", "csi500", "csi1000"):
        for field in ("pe_ttm", "pb"):
            policy[f"valuation.indices.{index}.{field}.percentile_expanding"] = "valuation_index_component"
    policy["valuation.csi300_erp_pct.value"] = "valuation_erp_component"
    for field in ("all_a_net_profit_yoy_pct", "nonfinancial_a_net_profit_yoy_pct"):
        policy[f"earnings.{field}.value"] = "earnings_growth_component"
    for field in ("all_a_roe_ttm_pct", "nonfinancial_a_roe_ttm_pct"):
        policy[f"earnings.{field}.value"] = "earnings_quality_component"
    for field in ("value", "change_1m", "change_3m", "above_50"):
        policy[f"earnings.pmi.{field}"] = "macro_confirmation_component"
    for index in INDEXES:
        for field in ("ma250_deviation_pct", "above_ma250", "ma250_slope_3m_pct", "return_6m_pct", "return_12m_pct", "drawdown_12m_high_pct"):
            policy[f"trend.indices.{index}.{field}.value"] = "trend_index_component"
    policy["sentiment.a_fear.fear_score"] = "sentiment_overlay"
    return {path: policy[path] for path in sorted(paths) if path in policy}


def forbidden(value: Any) -> int:
    if isinstance(value, dict):
        return sum((1 if str(key).lower() in FORBIDDEN_OUTPUT_KEYS else 0) + forbidden(item) for key, item in value.items())
    if isinstance(value, list):
        return sum(forbidden(item) for item in value)
    return 0


def keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [item for child in value.values() for item in keys(child)]
    if isinstance(value, list):
        return [item for child in value for item in keys(child)]
    return []


def contains_sentiment_core_input(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            token = str(key).lower()
            if any(part in token for part in ("a_fear", "fear_score", "sentiment_overlay")):
                return True
            if contains_sentiment_core_input(child):
                return True
    elif isinstance(value, list):
        return any(contains_sentiment_core_input(child) for child in value)
    return False


def reduce_record(row: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"month": row["month"], "basis_trade_date": row["basis_trade_date"], "source_evidence_sha256": rows["__meta__"]["source_sha"], "valuation": valuation(row), "earnings": earnings(row, rows), "macro_confirmation": macro_confirmation(row), "trend": trend(row), "sentiment_overlay": sentiment(row)}


# These replay functions intentionally duplicate the decision rules. The audit
# must be able to catch a production reducer that is internally self-consistent
# but wrong, so it cannot call the production reducers above.
def audit_expected_valuation(row: dict[str, Any]) -> dict[str, Any]:
    def component_audit(path: str, reverse: bool = False) -> dict[str, Any]:
        value = rank(row, path)
        is_ready = value is not None and ready(row, path)
        formal = "cheap" if (value <= 30 if not reverse else value >= 70) else ("expensive" if (value >= 70 if not reverse else value <= 30) else "neutral")
        state = "unavailable" if value is None else (formal if is_ready else "insufficient_history")
        return {"available": value is not None, "rank": value, "ready": is_ready, "state": state}

    c300pe = component_audit("valuation.indices.csi300.pe_ttm.percentile_expanding")
    c300pb = component_audit("valuation.indices.csi300.pb.percentile_expanding")
    c500pe = component_audit("valuation.indices.csi500.pe_ttm.percentile_expanding")
    c500pb = component_audit("valuation.indices.csi500.pb.percentile_expanding")
    erp = component_audit("valuation.csi300_erp_pct.value", reverse=True)

    def index_audit(pe: dict[str, Any], pb: dict[str, Any]) -> dict[str, Any]:
        values = [item["rank"] for item in (pe, pb) if item["rank"] is not None]
        complete = len(values) == 2
        component_ready = complete and pe["ready"] and pb["ready"]
        state = "unavailable" if not complete else (("cheap" if sum(values) / 2 <= 30 else ("expensive" if sum(values) / 2 >= 70 else "neutral")) if component_ready else "insufficient_history")
        return {"pe": pe, "pb": pb, "state": state, "available": complete, "ready": component_ready}

    c300 = index_audit(c300pe, c300pb)
    c500 = index_audit(c500pe, c500pb)
    components = {"csi300": c300, "csi500": c500, "csi1000": {"available": False, "state": "unavailable", "reason_code": "frozen_valuation_unavailable_no_proxy"}, "erp": erp}
    votes = [("csi300", c300), ("csi500", c500), ("erp", erp)]
    participating = [name for name, item in votes if item["available"] and item["ready"]]
    unavailable = ["csi1000"] + [name for name, item in votes if not item["ready"]]
    model_ready = len(participating) == 3
    formal_states = [item["state"] for _, item in votes if item["ready"]]
    cheap = formal_states.count("cheap")
    expensive = formal_states.count("expensive")
    state = "insufficient_history" if not model_ready else ("cheap" if cheap >= 2 else ("expensive" if expensive >= 2 else "neutral"))
    return {"state": state, "ready": model_ready, "cheap_count": cheap, "neutral_count": formal_states.count("neutral"), "expensive_count": expensive, "disagreement": len(set(formal_states)) > 1, "participating_components": participating, "unavailable_components": unavailable, "components": components, "reason_codes": [f"{name}_{item['state']}" for name, item in votes] + (["valuation_inputs_ready"] if model_ready else ["insufficient_history"])}


def audit_expected_earnings(row: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prior = rows.get(shift_month(row["month"], -3))
    def pair_audit(paths: tuple[str, str], label: str) -> dict[str, Any]:
        current_ranks = [rank(row, path) for path in paths]
        current_raw = [raw(row, path) for path in paths]
        prior_ranks = [rank(prior, path) if prior else None for path in paths]
        rank_ok = all(value is not None for value in current_ranks)
        change = sum(current_ranks) / 2 - sum(prior_ranks) / 2 if rank_ok and all(value is not None for value in prior_ranks) else None
        raw_level = sum(current_raw) / 2 if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in current_raw) else None
        return {"raw_level": raw_level, "rank": sum(current_ranks) / 2 if rank_ok else None, "rank_change_3m": change, "ready": all(ready(row, path) for path in paths), "reason_codes": [f"{label}_t_minus_3_natural_month" if change is not None else f"{label}_change_unavailable"]}
    growth = pair_audit(("earnings.all_a_net_profit_yoy_pct.value", "earnings.nonfinancial_a_net_profit_yoy_pct.value"), "growth")
    quality = pair_audit(("earnings.all_a_roe_ttm_pct.value", "earnings.nonfinancial_a_roe_ttm_pct.value"), "quality")
    state = "insufficient_history"
    if growth["ready"] and quality["ready"] and growth["rank_change_3m"] is not None and quality["rank_change_3m"] is not None:
        if growth["rank_change_3m"] < 0 and quality["rank_change_3m"] < 0:
            state = "deterioration"
        elif growth["raw_level"] is not None and growth["raw_level"] > 0 and growth["rank"] >= 50 and quality["rank"] >= 50 and growth["rank_change_3m"] >= 0 and quality["rank_change_3m"] >= 0:
            state = "expansion"
        elif growth["raw_level"] is not None and growth["raw_level"] > 0 and growth["rank_change_3m"] > 0 and quality["rank_change_3m"] >= 0:
            state = "recovery"
        elif growth["raw_level"] is not None and growth["raw_level"] <= 0 and growth["rank_change_3m"] > 0 and quality["rank_change_3m"] >= 0:
            state = "bottoming"
        else:
            state = "mixed"
    return {"state": state, "ready": growth["ready"] and quality["ready"], "growth_raw_level": growth["raw_level"], "growth_rank": growth["rank"], "growth_rank_change_3m": growth["rank_change_3m"], "quality_rank": quality["rank"], "quality_rank_change_3m": quality["rank_change_3m"], "reason_codes": growth["reason_codes"] + quality["reason_codes"]}


def audit_expected_macro(row: dict[str, Any]) -> dict[str, Any]:
    above, one, three = (raw(row, path) for path in ("earnings.pmi.above_50", "earnings.pmi.change_1m", "earnings.pmi.change_3m"))
    available = above is not None and one is not None and three is not None
    model_ready = all(ready(row, path) for path in ("earnings.pmi.above_50", "earnings.pmi.change_1m", "earnings.pmi.change_3m"))
    state = "insufficient_data"
    if available and model_ready:
        state = "positive" if above is True and (one > 0 or three > 0) else ("negative" if above is False and (one < 0 or three < 0) else "mixed")
    return {"state": state, "ready": model_ready, "reason_codes": ["pmi_confirmation_only", "insufficient_data" if not available else "pmi_inputs_present"]}


def audit_expected_trend_index(row: dict[str, Any], index: str) -> dict[str, Any]:
    prefix = f"trend.indices.{index}."
    paths = {"deviation": prefix + "ma250_deviation_pct.value", "above": prefix + "above_ma250.value", "slope": prefix + "ma250_slope_3m_pct.value", "return_6m": prefix + "return_6m_pct.value", "return_12m": prefix + "return_12m_pct.value", "drawdown": prefix + "drawdown_12m_high_pct.value"}
    complete = all(ready(row, path) for path in paths.values())
    unavailable = [name for name, path in paths.items() if raw(row, path) is None]
    state = "insufficient_history"
    if complete and not unavailable:
        above, slope, r6, r12, deviation_rank, drawdown_rank = raw(row, paths["above"]), raw(row, paths["slope"]), raw(row, paths["return_6m"]), raw(row, paths["return_12m"]), rank(row, paths["deviation"]), rank(row, paths["drawdown"])
        if above is True and slope > 0 and r12 > 0 and (deviation_rank >= 80 or rank(row, paths["return_12m"]) >= 80): state = "extended"
        elif above is True and slope > 0 and r12 > 0: state = "up"
        elif above is False and slope > 0 and r6 > 0: state = "bottoming"
        elif above is False and slope <= 0 and (r12 < 0 or drawdown_rank <= 20): state = "damaged"
        else: state = "mixed"
    return {"state": state, "ready": complete and not unavailable, "unavailable_features": unavailable, "reason_codes": [f"{index}_six_feature_reduction"]}


def audit_expected_trend(row: dict[str, Any]) -> dict[str, Any]:
    indexes = {index: audit_expected_trend_index(row, index) for index in INDEXES}
    participating = [index for index in INDEXES if indexes[index]["ready"]]
    if "csi300" not in participating or "csi500" not in participating:
        state = "insufficient_history"
    else:
        states = [indexes[index]["state"] for index in participating]
        damaged, extended = states.count("damaged"), states.count("extended")
        up = sum(value in ("up", "extended") for value in states)
        bottoming = sum(value in ("bottoming", "up") for value in states)
        state = "damaged" if damaged >= 2 else ("extended" if extended >= 2 else ("up" if up >= 2 else ("bottoming" if bottoming >= 2 and "bottoming" in states and damaged < 2 else "mixed")))
    return {"state": state, "ready": state != "insufficient_history", "participating_indices": participating, "index_states": {index: indexes[index]["state"] for index in INDEXES}, "dispersion": len({indexes[index]["state"] for index in participating}), "unavailable_indices": [index for index in INDEXES if not indexes[index]["ready"]], "csi300": indexes["csi300"], "csi500": indexes["csi500"], "csi1000": indexes["csi1000"], "reason_codes": ["six_features_to_index_state", "index_states_to_broad_state"]}


def audit_expected_sentiment(row: dict[str, Any]) -> dict[str, Any]:
    value = raw(row, "sentiment.a_fear.fear_score")
    state = "unavailable" if value is None else ("calm" if value < 20 else ("normal" if value < 40 else ("watch" if value < 60 else ("high_fear" if value < 80 else "extreme_fear"))))
    observations = feature(row, "sentiment.a_fear.fear_score").get("normalization_history_observations")
    return {"state": state, "score": value, "available": value is not None, "observations": observations, "normalization_history_observations": observations, "model_ready": ready(row, "sentiment.a_fear.fear_score"), "role": "overlay_only"}


def audit_expected_record(row: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"month": row["month"], "basis_trade_date": row["basis_trade_date"], "valuation": audit_expected_valuation(row), "earnings": audit_expected_earnings(row, rows), "macro_confirmation": audit_expected_macro(row), "trend": audit_expected_trend(row), "sentiment_overlay": audit_expected_sentiment(row)}


def build(evidence: dict[str, Any]) -> dict[str, Any]:
    source_sha = canonical_sha(evidence)
    rows = {row["month"]: row for row in evidence["records"]}
    rows["__meta__"] = {"source_sha": source_sha}
    records = [reduce_record(row, rows) for row in evidence["records"]]
    return {"schema": "cycle_engine_domain_signals_v1", "description": "PIT-safe domain reduction; no global score, regime, allocation, position, or trading signal.", "source_evidence_sha256": source_sha, "record_count": len(records), "start_month": records[0]["month"], "end_month": records[-1]["month"], "reduction_policy": reduction_policy(set(evidence["records"][-1]["features"])), "records": records}


def audit(data: dict[str, Any], evidence: dict[str, Any], evidence_audit: dict[str, Any]) -> dict[str, Any]:
    errors = {name: 0 for name in ("source_evidence_audit_violation_count", "source_evidence_hash_violation_count", "record_alignment_violation_count", "unauthorized_feature_use_count", "noncandidate_decision_use_count", "readiness_violation_count", "valuation_reduction_violation_count", "earnings_reduction_violation_count", "macro_confirmation_violation_count", "trend_index_reduction_violation_count", "trend_domain_reduction_violation_count", "sentiment_overlay_violation_count", "sentiment_core_leakage_count", "natural_month_change_violation_count", "future_information_dependency_count", "forbidden_output_violation_count", "upstream_mutation_count")}
    errors["source_evidence_audit_violation_count"] = int(evidence_audit.get("passed") is not True)
    evidence_sha = canonical_sha(evidence)
    errors["source_evidence_hash_violation_count"] = int(evidence_sha != FROZEN_PHASE1_EVIDENCE_SHA256 or data.get("source_evidence_sha256") != evidence_sha)
    expected_months = [item["month"] for item in evidence["records"]]
    actual_records = data.get("records", [])
    errors["record_alignment_violation_count"] = int(data.get("record_count") != len(expected_months) or [item.get("month") for item in actual_records] != expected_months)
    candidate_paths = {path for path, item in evidence["records"][-1]["features"].items() if item.get("model_candidate")}
    errors["unauthorized_feature_use_count"] = int(set(data.get("reduction_policy", {})) != candidate_paths)
    errors["noncandidate_decision_use_count"] = int(any(key in json.dumps(data, ensure_ascii=False) for key in ("valuation.csi300_earnings_yield_pct.value", "valuation.china_10y_government_bond_yield_pct.value", "valuation.indices.csi300.pe_ttm.value", "valuation.indices.csi300.pb.value", "valuation.indices.csi500.pe_ttm.value", "valuation.indices.csi500.pb.value")))
    errors["forbidden_output_violation_count"] = forbidden(data)
    rows = {row["month"]: row for row in evidence["records"]}
    for actual, source_row_value in zip(actual_records, evidence["records"]):
        wanted = audit_expected_record(source_row_value, rows)
        if actual.get("month") != wanted["month"] or actual.get("basis_trade_date") != wanted["basis_trade_date"]:
            errors["record_alignment_violation_count"] += 1
        if actual.get("source_evidence_sha256") != evidence_sha:
            errors["source_evidence_hash_violation_count"] += 1
        for section in ("valuation", "earnings", "macro_confirmation", "trend", "sentiment_overlay"):
            if actual.get(section) != wanted.get(section):
                errors[{"valuation": "valuation_reduction_violation_count", "earnings": "earnings_reduction_violation_count", "macro_confirmation": "macro_confirmation_violation_count", "trend": "trend_domain_reduction_violation_count", "sentiment_overlay": "sentiment_overlay_violation_count"}[section]] += 1
        if actual.get("sentiment_overlay", {}).get("state") != "unavailable" and actual.get("sentiment_overlay", {}).get("role") != "overlay_only":
            errors["sentiment_core_leakage_count"] += 1
        if any(contains_sentiment_core_input(actual.get(section, {})) for section in ("valuation", "earnings", "macro_confirmation", "trend")):
            errors["sentiment_core_leakage_count"] += 1
        for section in ("valuation", "earnings", "macro_confirmation", "trend", "sentiment_overlay"):
            if actual.get(section, {}).get("ready", actual.get(section, {}).get("model_ready")) != wanted.get(section, {}).get("ready", wanted.get(section, {}).get("model_ready")):
                errors["readiness_violation_count"] += 1
        for index in INDEXES:
            if actual.get("trend", {}).get(index, {}).get("ready") != wanted.get("trend", {}).get(index, {}).get("ready"):
                errors["readiness_violation_count"] += 1
        actual_earnings = actual.get("earnings", {})
        wanted_earnings = wanted.get("earnings", {})
        for field in ("growth_rank_change_3m", "quality_rank_change_3m"):
            if actual_earnings.get(field) != wanted_earnings.get(field):
                errors["natural_month_change_violation_count"] += 1
        for index in INDEXES:
            if actual.get("trend", {}).get(index, {}).get("state") != wanted.get("trend", {}).get(index, {}).get("state"):
                errors["trend_index_reduction_violation_count"] += 1
        if actual.get("earnings", {}).get("ready") and actual.get("earnings", {}).get("state") == "insufficient_history":
            errors["readiness_violation_count"] += 1
    lower_keys = [key.lower() for key in keys(data)]
    errors["future_information_dependency_count"] = int(any(any(token in key for token in ("future", "forward", "target")) for key in lower_keys))
    errors["upstream_mutation_count"] = int(evidence_sha != FROZEN_PHASE1_EVIDENCE_SHA256 or evidence_audit.get("passed") is not True)
    result = {"schema": "cycle_engine_domain_signals_audit_v1", "record_count": len(expected_months), "start_month": expected_months[0], "end_month": expected_months[-1], **errors, "passed": not any(errors.values())}
    return result


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    evidence, evidence_audit = load_sources()
    if evidence_audit.get("passed") is not True:
        raise RuntimeError("Phase 1 Evidence audit did not pass")
    source_sha = canonical_sha(evidence)
    if source_sha != FROZEN_EVIDENCE_SHA256:
        raise RuntimeError(f"Phase 1 Evidence source gate failed: {source_sha}")
    output = build(evidence)
    result = audit(output, evidence, evidence_audit)
    if not result["passed"]:
        raise RuntimeError("Phase 2 domain audit failed: " + json.dumps(result, ensure_ascii=False))
    return output, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    output, result = generate()
    if args.generate:
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        AUDIT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
