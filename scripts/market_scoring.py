from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_SNAPSHOT_PATH = DATA_DIR / "latest_market_snapshot.json"
DEFAULT_HISTORY_PATH = DATA_DIR / "market_score_history.json"
TZ = ZoneInfo("Asia/Shanghai")
MODEL_VERSION = "a_share_market_score_v1"

MODULES = {
    "index_trend": {"label": "指数趋势", "weight": 20},
    "breadth": {"label": "市场宽度", "weight": 15},
    "liquidity": {"label": "成交与流动性", "weight": 10},
    "capital_flow": {"label": "资金与风险偏好", "weight": 15},
    "mainline": {"label": "主线强度", "weight": 15},
    "valuation": {"label": "估值与再定价", "weight": 15},
    "macro": {"label": "宏观与外部环境", "weight": 10},
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def mean(values: list[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def scale(value: float | None, low: float, high: float, points: float) -> float:
    if value is None or not math.isfinite(value) or low == high:
        return points * 0.5
    if low < high:
        ratio = (value - low) / (high - low)
    else:
        ratio = (low - value) / (low - high)
    return clamp(ratio, 0.0, 1.0) * points


def round2(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 2)


def pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 2)


def metric(label: str, value: Any, unit: str = "", higher_is_better: bool | None = None) -> dict[str, Any]:
    return {
        "label": label,
        "value": round2(as_float(value)) if as_float(value) is not None else value,
        "unit": unit,
        "higher_is_better": higher_is_better,
    }


def evidence(label: str, value: Any, unit: str, score: float, max_score: float, note: str) -> dict[str, Any]:
    return {
        "label": label,
        "value": round2(as_float(value)) if as_float(value) is not None else value,
        "unit": unit,
        "score": round2(score),
        "max_score": max_score,
        "note": note,
    }


def module_result(
    key: str,
    score: float,
    summary: str,
    evidence_items: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    weight = MODULES[key]["weight"]
    score = clamp(score, 0.0, float(weight))
    return {
        "label": MODULES[key]["label"],
        "weight": weight,
        "score": round2(score),
        "score_pct": round2(score / weight * 100),
        "summary": summary,
        "evidence": evidence_items,
        "metrics": metrics,
    }


def index_trend(snapshot: dict[str, Any]) -> dict[str, Any]:
    indices = snapshot.get("market", {}).get("indices", {}) or {}
    rows = [row for row in indices.values() if row.get("close") is not None]

    above_count = sum(1 for row in rows if row.get("above_ma20") is True)
    ret5_values = [as_float(row.get("return_5d_pct")) for row in rows]
    ret20_values = [as_float(row.get("return_20d_pct")) for row in rows]
    dev_values = [as_float(row.get("ma20_deviation_pct")) for row in rows]
    ret5_clean = [value for value in ret5_values if value is not None]
    ret20_clean = [value for value in ret20_values if value is not None]
    dev_clean = [value for value in dev_values if value is not None]

    avg_ret5 = mean(ret5_clean)
    avg_ret20 = mean(ret20_clean)
    avg_dev = mean(dev_clean)
    above_score = (above_count / len(rows) * 6) if rows else 3
    momentum_score = mean([scale(value, -3, 6, 5) for value in ret5_clean]) if ret5_clean else 2.5
    trend_score = mean([scale(value, -8, 8, 5) for value in ret20_clean]) if ret20_clean else 2.5

    if avg_dev is None:
        deviation_score = 1.0
    elif -1 <= avg_dev <= 5:
        deviation_score = 2.0
    elif avg_dev > 8 or avg_dev < -6:
        deviation_score = 0.6
    else:
        deviation_score = 1.2

    sh = indices.get("000001.SH", {})
    sz = indices.get("399001.SZ", {})
    cy = indices.get("399006.SZ", {})
    sh20 = as_float(sh.get("return_20d_pct"))
    sz20 = as_float(sz.get("return_20d_pct"))
    cy20 = as_float(cy.get("return_20d_pct"))
    if all(value is not None and value > 0 for value in [sh20, sz20, cy20]):
        balance_score = 2.0
    elif sh20 is not None and sz20 is not None and cy20 is not None and (sz20 > 0 or cy20 > 0):
        balance_score = 1.0
    else:
        balance_score = 0.7

    score = above_score + (momentum_score or 0) + (trend_score or 0) + deviation_score + balance_score
    metrics = {
        "shanghai_close": metric("上证收盘", sh.get("close"), "点", True),
        "above_ma20_count": metric("站上MA20指数数", above_count, "个", True),
        "avg_return_5d_pct": metric("指数平均5日涨跌", avg_ret5, "%", True),
        "avg_return_20d_pct": metric("指数平均20日涨跌", avg_ret20, "%", True),
        "avg_ma20_deviation_pct": metric("平均MA20偏离", avg_dev, "%", None),
        "chinext_return_5d_pct": metric("创业板5日涨跌", cy.get("return_5d_pct"), "%", True),
    }
    evidences = [
        evidence("站上MA20指数数", above_count, "个", above_score, 6, "越多越说明指数层面修复更广。"),
        evidence("指数平均5日涨跌", avg_ret5, "%", momentum_score or 0, 5, "短期动量衡量反弹强度。"),
        evidence("指数平均20日涨跌", avg_ret20, "%", trend_score or 0, 5, "20日趋势决定是否从反弹进入趋势。"),
        evidence("平均MA20偏离", avg_dev, "%", deviation_score, 2, "温和站上均线最好，过热或深跌都降分。"),
        evidence("沪深创趋势一致性", "", "", balance_score, 2, "大盘和成长同时走强时更稳。"),
    ]
    return module_result("index_trend", score, "指数层面偏强，但沪深创并未完全同步。", evidences, metrics)


def market_breadth(snapshot: dict[str, Any]) -> dict[str, Any]:
    breadth = snapshot.get("breadth", {}) or {}
    advancers = as_float(breadth.get("advancers")) or 0
    decliners = as_float(breadth.get("decliners")) or 0
    total = as_float(breadth.get("total")) or (advancers + decliners)
    advancer_ratio = advancers / total if total else None
    industry_up_ratio = as_float(breadth.get("industry_up_ratio"))
    limit_up = as_float(breadth.get("limit_up")) or 0
    limit_down = as_float(breadth.get("limit_down")) or 0
    max_streak = as_float(breadth.get("max_limit_up_streak"))

    adv_score = scale(advancer_ratio, 0.2, 0.65, 5)
    industry_score = scale(industry_up_ratio, 0.2, 0.65, 4)
    if limit_down <= 3 and limit_up >= 50:
        limit_score = 3
    else:
        limit_score = scale(limit_up - limit_down * 5, 0, 80, 3)
    streak_score = scale(max_streak, 1, 7, 1.5)
    consistency_score = 1.5 if (advancer_ratio or 0) >= 0.5 and (industry_up_ratio or 0) >= 0.5 else 0.4

    score = adv_score + industry_score + limit_score + streak_score + consistency_score
    metrics = {
        "advancer_ratio_pct": metric("上涨家数占比", pct(advancer_ratio), "%", True),
        "industry_up_ratio_pct": metric("行业上涨占比", pct(industry_up_ratio), "%", True),
        "limit_up": metric("涨停数", limit_up, "家", True),
        "limit_down": metric("跌停数", limit_down, "家", False),
        "max_limit_up_streak": metric("最高连板", max_streak, "板", True),
    }
    evidences = [
        evidence("上涨家数占比", pct(advancer_ratio), "%", adv_score, 5, "宽度不足时，指数上涨容易变成少数主线行情。"),
        evidence("行业上涨占比", pct(industry_up_ratio), "%", industry_score, 4, "行业扩散越充分，行情越健康。"),
        evidence("涨跌停结构", f"{int(limit_up)}/{int(limit_down)}", "涨停/跌停", limit_score, 3, "涨停多且跌停少代表情绪仍可用。"),
        evidence("最高连板", max_streak, "板", streak_score, 1.5, "连板高度衡量短线风险偏好。"),
        evidence("指数与宽度一致性", "", "", consistency_score, 1.5, "指数强但宽度弱时降分。"),
    ]
    return module_result("breadth", score, "市场宽度偏弱，情绪强于赚钱效应。", evidences, metrics)


def liquidity(snapshot: dict[str, Any]) -> dict[str, Any]:
    indices = snapshot.get("market", {}).get("indices", {}) or {}
    volume_values = [
        as_float(row.get("volume_ratio_5d"))
        for row in indices.values()
        if as_float(row.get("volume_ratio_5d")) is not None
    ]
    avg_volume_ratio = mean(volume_values)
    distribution = (snapshot.get("capital_flow", {}) or {}).get("turnover_distribution", {}) or {}
    large_share = as_float((distribution.get("large_cap") or {}).get("share"))
    mid_share = as_float((distribution.get("mid_cap") or {}).get("share")) or 0
    small_share = as_float((distribution.get("small_cap") or {}).get("share")) or 0
    active_share = mid_share + small_share

    if avg_volume_ratio is None:
        volume_score = 2.5
    else:
        volume_score = clamp(1 - abs(avg_volume_ratio - 1.08) / 0.45, 0, 1) * 5
    active_score = scale(active_share, 0.5, 0.82, 3)
    large_score = scale(large_share, 0.12, 0.35, 2)
    score = volume_score + active_score + large_score

    metrics = {
        "avg_volume_ratio": metric("指数平均量能比", avg_volume_ratio, "倍", True),
        "large_turnover_share_pct": metric("大盘成交占比", pct(large_share), "%", True),
        "mid_turnover_share_pct": metric("中盘成交占比", pct(mid_share), "%", None),
        "small_turnover_share_pct": metric("小盘成交占比", pct(small_share), "%", None),
        "mid_small_turnover_share_pct": metric("中小盘成交占比", pct(active_share), "%", True),
    }
    evidences = [
        evidence("指数平均量能比", avg_volume_ratio, "倍", volume_score, 5, "温和放量优于缩量或爆量。"),
        evidence("中小盘成交占比", pct(active_share), "%", active_score, 3, "中小盘活跃代表风险偏好抬升。"),
        evidence("大盘成交占比", pct(large_share), "%", large_score, 2, "大盘承接不足会降低趋势稳定性。"),
    ]
    return module_result("liquidity", score, "成交活跃度尚可，资金更多集中在中小盘。", evidences, metrics)


def capital_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    cap = snapshot.get("capital_flow", {}) or {}
    north = as_float(cap.get("northbound_net_inflow_100m_cny"))
    main = as_float(cap.get("main_net_inflow_100m_cny"))
    distribution = cap.get("turnover_distribution", {}) or {}
    mid_share = as_float((distribution.get("mid_cap") or {}).get("share")) or 0
    small_share = as_float((distribution.get("small_cap") or {}).get("share")) or 0
    active_share = mid_share + small_share
    top_flows = (snapshot.get("sector_rotation", {}) or {}).get("top5_industries_by_capital_inflow", []) or []
    top_flow_sum = sum(as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows)

    north_score = scale(north, -50, 80, 4)
    main_score = scale(main, -800, 300, 5)
    risk_score = scale(active_share, 0.5, 0.82, 3)
    if north is not None and main is not None and north > 0 and main < 0:
        consistency_score = 0.8
    elif north is not None and main is not None and north > 0 and main > 0:
        consistency_score = 2.0
    else:
        consistency_score = 1.0
    sector_flow_score = scale(top_flow_sum, 0, 250, 1)

    score = north_score + main_score + risk_score + consistency_score + sector_flow_score
    metrics = {
        "northbound_net_inflow_100m_cny": metric("北向净流入", north, "亿元", True),
        "main_net_inflow_100m_cny": metric("主力净流入", main, "亿元", True),
        "mid_small_turnover_share_pct": metric("中小盘成交占比", pct(active_share), "%", True),
        "top5_industry_inflow_sum_100m_cny": metric("前五行业净流入合计", top_flow_sum, "亿元", True),
    }
    evidences = [
        evidence("北向净流入", north, "亿元", north_score, 4, "外资流入对风险偏好有支撑。"),
        evidence("主力净流入", main, "亿元", main_score, 5, "主力大幅流出代表内资分歧。"),
        evidence("中小盘成交占比", pct(active_share), "%", risk_score, 3, "风险偏好越高，进攻仓可用性越强。"),
        evidence("内外资一致性", "", "", consistency_score, 2, "北向和主力同向时更可靠，背离时降分。"),
        evidence("行业资金承接", top_flow_sum, "亿元", sector_flow_score, 1, "主线方向有资金承接时加分。"),
    ]
    return module_result("capital_flow", score, "北向流入但主力流出，资金层面是分歧上行。", evidences, metrics)


def theme_group(name: str) -> str:
    text = name or ""
    if any(word in text for word in ["半导体", "电子", "光学", "消费电子"]):
        return "电子半导体"
    if any(word in text for word in ["通信", "计算机", "软件"]):
        return "AI算力"
    if any(word in text for word in ["建筑", "建材"]):
        return "地产链"
    if any(word in text for word in ["煤炭", "钢铁", "有色"]):
        return "周期"
    return text[:4] or "其他"


def mainline(snapshot: dict[str, Any]) -> dict[str, Any]:
    rotation = snapshot.get("sector_rotation", {}) or {}
    top_returns = rotation.get("top5_industries_by_return", []) or []
    top_flows = rotation.get("top5_industries_by_capital_inflow", []) or []
    return_avg = mean([as_float(row.get("pct_change")) or 0 for row in top_returns]) or 0
    top_flow_sum = sum(as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows)
    top_flow_max = max([as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows] or [0])
    concentration = top_flow_max / top_flow_sum if top_flow_sum else None
    return_groups = {theme_group(row.get("industry", "")) for row in top_returns}
    flow_groups = {theme_group(row.get("industry", "")) for row in top_flows}
    overlap_count = len(return_groups & flow_groups)
    flow_group_count = len(flow_groups)

    return_score = scale(return_avg, 0, 4, 4)
    flow_score = scale(top_flow_sum, 0, 250, 4)
    alignment_score = scale(overlap_count, 0, 2, 3)
    breadth_score = scale(flow_group_count, 1, 4, 2)
    continuity_score = 1.0
    score = return_score + flow_score + alignment_score + breadth_score + continuity_score

    metrics = {
        "top5_return_avg_pct": metric("涨幅前五行业均值", return_avg, "%", True),
        "top5_industry_inflow_sum_100m_cny": metric("前五行业净流入合计", top_flow_sum, "亿元", True),
        "price_flow_overlap_count": metric("价量重合主线数", overlap_count, "组", True),
        "flow_group_count": metric("资金主线组数", flow_group_count, "组", True),
        "top_flow_concentration_pct": metric("第一主线资金占比", pct(concentration), "%", False),
    }
    evidences = [
        evidence("涨幅前五行业均值", return_avg, "%", return_score, 4, "领涨行业涨幅越强，主线越清晰。"),
        evidence("前五行业净流入合计", top_flow_sum, "亿元", flow_score, 4, "资金集中流入说明主线有承接。"),
        evidence("价量重合主线数", overlap_count, "组", alignment_score, 3, "涨幅榜和资金榜重合越高越可靠。"),
        evidence("资金主线组数", flow_group_count, "组", breadth_score, 2, "主线过窄时降低扩仓质量。"),
        evidence("连续性数据", "缺少多日行业流向", "", continuity_score, 2, "没有多日主线验证，按中性偏低处理。"),
    ]
    return module_result("mainline", score, "科技成长主线明确，但资金集中度偏高。", evidences, metrics)


def valuation(snapshot: dict[str, Any]) -> dict[str, Any]:
    valuation_data = snapshot.get("valuation") or snapshot.get("repricing")
    if not valuation_data:
        score = 7.5
        summary = "估值数据缺失，按中性处理并降低置信度。"
        metrics = {
            "valuation_data_available": metric("估值数据可用", 0, "", True),
            "neutral_valuation_score_pct": metric("中性估值分", 50, "%", None),
        }
        evidences = [
            evidence("估值分位", "缺失", "", 7.5, 15, "缺估值时不主观乐观，先给中性分。"),
        ]
    else:
        score = 7.5
        summary = "估值数据已接入，但当前模型未识别标准字段，暂按中性处理。"
        metrics = {
            "valuation_data_available": metric("估值数据可用", 1, "", True),
            "neutral_valuation_score_pct": metric("中性估值分", 50, "%", None),
        }
        evidences = [
            evidence("估值字段", "未标准化", "", 7.5, 15, "需要补充指数和行业估值分位字段。"),
        ]
    return module_result("valuation", score, summary, evidences, metrics)


def macro(snapshot: dict[str, Any]) -> dict[str, Any]:
    macro_data = snapshot.get("macro", {}) or {}
    us10 = as_float((macro_data.get("us_10y_treasury_yield_pct") or {}).get("value"))
    dxy = as_float((macro_data.get("dxy") or {}).get("value"))
    usd_cny = as_float((macro_data.get("usd_cny") or {}).get("value"))
    cn10_row = macro_data.get("china_10y_government_bond_yield_pct") or {}
    cn10 = as_float(cn10_row.get("value_pct") if "value_pct" in cn10_row else cn10_row.get("value"))

    cn_score = scale(cn10, 3.0, 1.7, 4)
    us_score = scale(us10, 5.0, 3.5, 2.5)
    dxy_score = scale(dxy, 107, 96, 2)
    cny_score = scale(usd_cny, 7.3, 6.7, 1.5)
    score = cn_score + us_score + dxy_score + cny_score

    metrics = {
        "china_10y_yield_pct": metric("中国10Y国债", cn10, "%", False),
        "us_10y_yield_pct": metric("美国10Y国债", us10, "%", False),
        "dxy": metric("美元指数", dxy, "", False),
        "usd_cny": metric("美元兑人民币", usd_cny, "", False),
    }
    evidences = [
        evidence("中国10Y国债", cn10, "%", cn_score, 4, "国内利率低，对权益流动性有支撑。"),
        evidence("美国10Y国债", us10, "%", us_score, 2.5, "海外利率高会压制成长资产估值。"),
        evidence("美元指数", dxy, "", dxy_score, 2, "美元偏强时风险偏好承压。"),
        evidence("美元兑人民币", usd_cny, "", cny_score, 1.5, "人民币稳定有利于外资和风险偏好。"),
    ]
    return module_result("macro", score, "国内流动性友好，海外利率仍有压制。", evidences, metrics)


def crowding_penalty(snapshot: dict[str, Any], modules: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    breadth = snapshot.get("breadth", {}) or {}
    cap = snapshot.get("capital_flow", {}) or {}
    rotation = snapshot.get("sector_rotation", {}) or {}
    indices = snapshot.get("market", {}).get("indices", {}) or {}

    advancers = as_float(breadth.get("advancers")) or 0
    total = as_float(breadth.get("total")) or 0
    advancer_ratio = advancers / total if total else None
    if modules["index_trend"]["score"] >= 12 and (advancer_ratio or 0) < 0.4:
        items.append({"label": "指数强但上涨家数不足", "penalty": 5, "basis": f"上涨家数占比 {pct(advancer_ratio)}%"})

    chinext = indices.get("399006.SZ", {})
    chinext_ret5 = as_float(chinext.get("return_5d_pct"))
    chinext_dev = as_float(chinext.get("ma20_deviation_pct"))
    if (chinext_ret5 or 0) >= 7 or (chinext_dev or 0) >= 4:
        items.append({"label": "成长方向短线过热", "penalty": 4, "basis": f"创业板5日 {round2(chinext_ret5)}%，MA20偏离 {round2(chinext_dev)}%"})

    north = as_float(cap.get("northbound_net_inflow_100m_cny"))
    main = as_float(cap.get("main_net_inflow_100m_cny"))
    if north is not None and main is not None and north > 0 and main < -300:
        items.append({"label": "北向流入但主力大幅流出", "penalty": 4, "basis": f"北向 {round2(north)} 亿，主力 {round2(main)} 亿"})

    top_flows = rotation.get("top5_industries_by_capital_inflow", []) or []
    top_flow_sum = sum(as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows)
    top_flow_max = max([as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows] or [0])
    concentration = top_flow_max / top_flow_sum if top_flow_sum else None
    if (concentration or 0) >= 0.65:
        items.append({"label": "资金过度集中在单一主线", "penalty": 3, "basis": f"第一主线资金占比 {pct(concentration)}%"})

    if not snapshot.get("valuation") and not snapshot.get("repricing"):
        items.append({"label": "估值字段缺失", "penalty": 2, "basis": "估值与再定价模块按中性处理"})

    penalty = round2(sum(as_float(item["penalty"]) or 0 for item in items)) or 0
    return {
        "penalty": penalty,
        "items": items,
        "metrics": {
            "advancer_ratio_pct": metric("上涨家数占比", pct(advancer_ratio), "%", True),
            "chinext_return_5d_pct": metric("创业板5日涨跌", chinext_ret5, "%", False),
            "main_net_inflow_100m_cny": metric("主力净流入", main, "亿元", True),
            "top_flow_concentration_pct": metric("第一主线资金占比", pct(concentration), "%", False),
        },
    }


def position_range(score: float) -> str:
    if score <= 20:
        return "0%-20%"
    if score <= 35:
        return "20%-35%"
    if score <= 50:
        return "35%-45%"
    if score <= 65:
        return "45%-60%"
    if score <= 80:
        return "60%-75%"
    return "75%-85%"


def sleeve_mix(score: float, modules: dict[str, Any], crowding: dict[str, Any]) -> dict[str, str]:
    breadth_pct = modules["breadth"]["score_pct"] or 0
    penalty = crowding["penalty"]
    if score <= 35:
        return {"core": "20%-30%", "offensive": "0%-15%", "defensive": "55%-75%", "thematic": "0%-5%"}
    if score <= 50:
        return {"core": "35%-45%", "offensive": "15%-25%", "defensive": "25%-40%", "thematic": "0%-8%"}
    if breadth_pct < 45 or penalty >= 14:
        return {"core": "45%-50%", "offensive": "25%-35%", "defensive": "15%-25%", "thematic": "0%-10%"}
    if score <= 65:
        return {"core": "45%-55%", "offensive": "30%-40%", "defensive": "10%-20%", "thematic": "0%-10%"}
    return {"core": "50%-60%", "offensive": "30%-45%", "defensive": "5%-15%", "thematic": "0%-10%"}


def regime(opportunity: float, position: float, modules: dict[str, Any], crowding: dict[str, Any]) -> str:
    breadth_pct = modules["breadth"]["score_pct"] or 0
    if opportunity >= 60 and breadth_pct < 45:
        return "结构性偏强但分歧较大"
    if position <= 35:
        return "防守或弱修复"
    if position <= 50:
        return "中性震荡偏结构"
    if position <= 65:
        return "结构性偏强"
    return "趋势性偏强"


def confidence(snapshot: dict[str, Any]) -> str:
    missing = (snapshot.get("data_quality", {}) or {}).get("missing_fields", []) or []
    valuation_missing = not snapshot.get("valuation") and not snapshot.get("repricing")
    count = len(missing) + (1 if valuation_missing else 0)
    if count >= 5:
        return "low"
    if count >= 1:
        return "medium"
    return "high"


def score_snapshot(snapshot: dict[str, Any], snapshot_path: Path | None = None, snapshot_bytes: bytes | None = None) -> dict[str, Any]:
    modules = {
        "index_trend": index_trend(snapshot),
        "breadth": market_breadth(snapshot),
        "liquidity": liquidity(snapshot),
        "capital_flow": capital_flow(snapshot),
        "mainline": mainline(snapshot),
        "valuation": valuation(snapshot),
        "macro": macro(snapshot),
    }
    opportunity = round2(sum(as_float(module["score"]) or 0 for module in modules.values())) or 0
    crowding = crowding_penalty(snapshot, modules)
    final_score = round2(clamp(opportunity - (crowding["penalty"] or 0), 0, 100)) or 0
    shanghai = (snapshot.get("market", {}).get("indices", {}) or {}).get("000001.SH", {})
    now = datetime.now(TZ).isoformat(timespec="seconds")
    if snapshot_bytes is None and snapshot_path and snapshot_path.exists():
        snapshot_bytes = snapshot_path.read_bytes()
    snapshot_hash = hashlib.sha256(snapshot_bytes or json.dumps(snapshot, ensure_ascii=False).encode("utf-8")).hexdigest()
    snapshot_label = None
    if snapshot_path:
        resolved_snapshot = snapshot_path.resolve()
        try:
            snapshot_label = str(resolved_snapshot.relative_to(ROOT))
        except ValueError:
            snapshot_label = str(resolved_snapshot)

    key_constraints = [
        "上涨家数和行业上涨占比不足时，不把指数强势直接等同于全面加仓。",
        "主力资金持续流出时，进攻仓只做主线，不扩散到弱势行业。",
        "估值字段未接入前，估值模块保持中性，最终置信度不评为高。",
    ]
    record = {
        "run_id": f"{datetime.now(TZ).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}",
        "model_version": MODEL_VERSION,
        "scored_at": now,
        "basis_trade_date": snapshot.get("date") or (snapshot.get("market", {}) or {}).get("as_of_trade_date"),
        "snapshot_file": snapshot_label,
        "snapshot_sha256": snapshot_hash,
        "market_regime": regime(opportunity, final_score, modules, crowding),
        "market_opportunity_score": opportunity,
        "crowding_penalty": crowding["penalty"],
        "market_position_score": final_score,
        "confidence": confidence(snapshot),
        "equity_position_range": position_range(final_score),
        "sleeve_mix": sleeve_mix(final_score, modules, crowding),
        "shanghai_composite": round2(as_float(shanghai.get("close"))),
        "modules": modules,
        "crowding": crowding,
        "key_constraints": key_constraints,
        "data_quality": snapshot.get("data_quality", {}),
    }
    return record


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "model_version": MODEL_VERSION,
            "updated_at": None,
            "records": [],
        }
    payload = load_json(path)
    if isinstance(payload, list):
        payload = {
            "schema_version": 1,
            "model_version": MODEL_VERSION,
            "updated_at": None,
            "records": payload,
        }
    payload.setdefault("schema_version", 1)
    payload.setdefault("model_version", MODEL_VERSION)
    payload.setdefault("records", [])
    return payload


def save_history(history: dict[str, Any], path: Path = DEFAULT_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_score(snapshot_path: Path = DEFAULT_SNAPSHOT_PATH, history_path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8-sig"))
    record = score_snapshot(snapshot, snapshot_path=snapshot_path, snapshot_bytes=snapshot_bytes)
    history = load_history(history_path)
    history["model_version"] = MODEL_VERSION
    history["updated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    history["records"].append(record)
    save_history(history, history_path)
    return {"history_path": str(history_path), "record": record, "history": history}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a MyInvest A-share market snapshot and append history.")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH), help="Snapshot JSON path.")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = append_score(Path(args.snapshot), Path(args.history))
    record = result["record"]
    print(
        json.dumps(
            {
                "history_path": result["history_path"],
                "run_id": record["run_id"],
                "basis_trade_date": record["basis_trade_date"],
                "market_opportunity_score": record["market_opportunity_score"],
                "crowding_penalty": record["crowding_penalty"],
                "market_position_score": record["market_position_score"],
                "equity_position_range": record["equity_position_range"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
