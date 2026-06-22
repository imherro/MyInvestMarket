from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_SNAPSHOT_PATH = DATA_DIR / "latest_market_snapshot.json"
DEFAULT_HISTORY_PATH = DATA_DIR / "market_score_history.json"
DEFAULT_AUDIT_LOG_PATH = DATA_DIR / "market_score_history_audit.jsonl"
TZ = ZoneInfo("Asia/Shanghai")
MODEL_VERSION = "a_share_market_score_v1_4"
SCORE_SCHEMA_VERSION = "1.4"
FEATURE_SCHEMA_VERSION = "1.2"
POSITION_POLICY_VERSION = "stock_account_position_policy_v2"
HISTORY_SCHEMA_VERSION = 2
HISTORY_DEDUPE_KEY_FIELDS = (
    "basis_trade_date",
    "snapshot_sha256",
    "model_version",
    "position_policy_version",
)
MIN_ROLLING_SAMPLE_COUNT = 4
REQUIRED_SCORE_RECORD_STRING_FIELDS = (
    "run_id",
    "model_version",
    "position_policy_version",
    "account_scope",
    "scored_at",
    "basis_trade_date",
    "snapshot_sha256",
    "market_regime",
    "confidence",
    "recommended_equity_position_range",
)
REQUIRED_SCORE_RECORD_NUMERIC_RANGES = {
    "market_opportunity_score": (0, 100),
    "crowding_penalty": (0, 30),
    "pre_cap_market_position_score": (0, 100),
    "market_position_score": (0, 100),
}
OPTIONAL_SCORE_RECORD_NUMERIC_RANGES = {
    "opportunity_score": (0, 100),
    "base_market_position_score": (0, 100),
    "legacy_vol_adjusted_market_position_score": (0, 100),
}
SCORE_RECORD_PERCENT_RANGE_FIELDS = (
    "recommended_equity_position_range",
    "base_equity_position_range",
    "equity_position_range",
    "legacy_vol_adjusted_equity_position_range",
)

MODULES = {
    "index_trend": {"label": "指数趋势", "weight": 20},
    "breadth": {"label": "市场宽度", "weight": 15},
    "liquidity": {"label": "成交与流动性", "weight": 10},
    "capital_flow": {"label": "资金与风险偏好", "weight": 15},
    "mainline": {"label": "主线强度", "weight": 15},
    "valuation": {"label": "估值与再定价", "weight": 15},
    "macro": {"label": "宏观与外部环境", "weight": 10},
}


class ScoreRecordValidationError(ValueError):
    pass


class MarketSnapshotValidationError(ValueError):
    pass


def history_audit_log_path(history_path: Path = DEFAULT_HISTORY_PATH) -> Path:
    try:
        if history_path.resolve() == (DATA_DIR / "market_score_history.json").resolve():
            return DEFAULT_AUDIT_LOG_PATH
    except Exception:
        pass
    if history_path == DATA_DIR / "market_score_history.json":
        return DEFAULT_AUDIT_LOG_PATH
    return history_path.with_name(f"{history_path.stem}_audit.jsonl")


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


def cap_score_when_sample_short(score: float | None, max_score: float, sample_count: Any) -> float:
    score_value = as_float(score)
    count = as_float(sample_count)
    if score_value is None:
        return max_score * 0.5
    if count is None or count < MIN_ROLLING_SAMPLE_COUNT:
        return min(score_value, max_score * 0.5)
    return score_value


def penalty_scale(value: float | None, no_penalty: float, full_penalty: float, points: float) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return scale(value, no_penalty, full_penalty, points)


def round2(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 2)


def parse_date_value(value: Any) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.fromisoformat(text[:10]).date()
    except Exception:
        return None


def pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 2)


def parse_percent_range(value: str | None) -> tuple[float, float] | None:
    if not value or "-" not in value:
        return None
    try:
        left, right = value.replace("%", "").split("-", 1)
        return float(left), float(right)
    except Exception:
        return None


def format_percent_range(bounds: tuple[float, float] | None) -> str | None:
    if bounds is None:
        return None
    lower = clamp(bounds[0], 0, 100)
    upper = clamp(bounds[1], 0, 100)
    if lower > upper:
        lower, upper = upper, lower
    return f"{round(lower)}%-{round(upper)}%"


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


def module_strength(score: float, key: str) -> str:
    weight = as_float(MODULES.get(key, {}).get("weight")) or 1
    ratio = clamp((as_float(score) or 0) / weight, 0, 1)
    if ratio >= 0.7:
        return "偏强"
    if ratio <= 0.4:
        return "偏弱"
    return "中性"


def signed_pct_text(value: float | None) -> str:
    number = as_float(value)
    if number is None:
        return "--"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{round2(number)}%"


def market_snapshot_files() -> list[Path]:
    return sorted(DATA_DIR.glob("market_snapshot_*.json"))


def snapshot_sort_key(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("date") or (snapshot.get("market", {}) or {}).get("as_of_trade_date") or "")


def load_market_snapshots_through(basis_trade_date: str | None) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in market_snapshot_files():
        try:
            payload = load_json(path)
        except Exception:
            continue
        date_key = snapshot_sort_key(payload)
        if basis_trade_date and date_key > basis_trade_date:
            continue
        snapshots.append(payload)
    snapshots.sort(key=snapshot_sort_key)
    return snapshots


def rolling_market_features(snapshot: dict[str, Any]) -> dict[str, Any]:
    basis = snapshot.get("date") or (snapshot.get("market", {}) or {}).get("as_of_trade_date")
    snapshots = load_market_snapshots_through(str(basis) if basis else None)
    if not snapshots or snapshot_sort_key(snapshots[-1]) != str(basis):
        snapshots.append(snapshot)
        snapshots.sort(key=snapshot_sort_key)

    def values(key_fn: Any, window: int) -> list[float]:
        result: list[float] = []
        for row in snapshots[-window:]:
            value = as_float(key_fn(row))
            if value is not None:
                result.append(value)
        return result

    def advancer_ratio(row: dict[str, Any]) -> float | None:
        breadth = row.get("breadth", {}) or {}
        total = as_float(breadth.get("total"))
        advancers = as_float(breadth.get("advancers"))
        return advancers / total if total else None

    def top_flow_sum(row: dict[str, Any]) -> float:
        flows = (row.get("sector_rotation", {}) or {}).get("top5_industries_by_capital_inflow", []) or []
        return sum(as_float(item.get("net_amount_100m_cny")) or 0 for item in flows)

    current_flows = (snapshot.get("sector_rotation", {}) or {}).get("top5_industries_by_capital_inflow", []) or []
    current_groups = {theme_group(row.get("industry", "")) for row in current_flows}
    recent_group_hits = 0
    recent_group_total = 0
    basis_key = str(basis) if basis else ""
    prior_rows = [row for row in snapshots if snapshot_sort_key(row) != basis_key][-5:]
    for row in prior_rows:
        groups = {theme_group(item.get("industry", "")) for item in ((row.get("sector_rotation", {}) or {}).get("top5_industries_by_capital_inflow", []) or [])}
        if not groups:
            continue
        recent_group_total += 1
        if current_groups & groups:
            recent_group_hits += 1

    north_5 = values(lambda row: (row.get("capital_flow", {}) or {}).get("northbound_net_inflow_100m_cny"), 5)
    main_5 = values(lambda row: (row.get("capital_flow", {}) or {}).get("main_net_inflow_100m_cny"), 5)
    breadth_5 = values(advancer_ratio, 5)
    top_flow_5 = values(top_flow_sum, 5)

    return {
        "sample_count": len(snapshots),
        "basis_trade_date": basis,
        "capital_flow": {
            "northbound_5d_sum_100m_cny": round2(sum(north_5)) if north_5 else None,
            "main_5d_sum_100m_cny": round2(sum(main_5)) if main_5 else None,
            "northbound_sample_count": len(north_5),
            "main_sample_count": len(main_5),
        },
        "breadth": {
            "advancer_ratio_5d_avg_pct": pct(mean(breadth_5)) if breadth_5 else None,
            "sample_count": len(breadth_5),
        },
        "mainline": {
            "top_flow_5d_sum_100m_cny": round2(sum(top_flow_5)) if top_flow_5 else None,
            "current_group_repeat_ratio_5d": round2(recent_group_hits / recent_group_total) if recent_group_total else None,
            "sample_count": recent_group_total,
        },
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
    strength = module_strength(score, "index_trend")
    summary = f"指数趋势{strength}，{above_count}/{len(rows) or 0}个指数站上MA20，20日平均涨跌{signed_pct_text(avg_ret20)}。"
    return module_result("index_trend", score, summary, evidences, metrics)


def market_breadth(snapshot: dict[str, Any]) -> dict[str, Any]:
    breadth = snapshot.get("breadth", {}) or {}
    advancers = as_float(breadth.get("advancers")) or 0
    decliners = as_float(breadth.get("decliners")) or 0
    total = as_float(breadth.get("total")) or (advancers + decliners)
    advancer_ratio = advancers / total if total else None
    industry_up_ratio = as_float(breadth.get("industry_up_ratio"))
    median_pct_change = as_float(breadth.get("median_pct_change"))
    strong_advancers_ratio = as_float(breadth.get("strong_advancers_gt3_pct"))
    strong_decliners_ratio = as_float(breadth.get("strong_decliners_lt_minus3_pct"))
    strong_spread = (
        strong_advancers_ratio - strong_decliners_ratio
        if strong_advancers_ratio is not None and strong_decliners_ratio is not None
        else None
    )
    limit_up = as_float(breadth.get("limit_up")) or 0
    limit_down = as_float(breadth.get("limit_down")) or 0
    max_streak = as_float(breadth.get("max_limit_up_streak"))

    adv_score = scale(advancer_ratio, 0.2, 0.65, 4)
    industry_score = scale(industry_up_ratio, 0.2, 0.65, 3)
    median_score = scale(median_pct_change, -1.5, 1.5, 2.5)
    strong_score = scale(strong_spread, -0.12, 0.12, 2)
    if limit_down <= 3 and limit_up >= 50:
        limit_score = 2
    else:
        limit_score = scale(limit_up - limit_down * 5, 0, 80, 2)
    streak_score = scale(max_streak, 1, 7, 1)
    consistency_score = 0.5 if (advancer_ratio or 0) >= 0.5 and (industry_up_ratio or 0) >= 0.5 else 0.15

    score = adv_score + industry_score + median_score + strong_score + limit_score + streak_score + consistency_score
    metrics = {
        "advancer_ratio_pct": metric("上涨家数占比", pct(advancer_ratio), "%", True),
        "industry_up_ratio_pct": metric("行业上涨占比", pct(industry_up_ratio), "%", True),
        "median_pct_change": metric("个股中位数涨跌", median_pct_change, "%", True),
        "strong_advancers_gt3_pct": metric("涨幅超过3%占比", pct(strong_advancers_ratio), "%", True),
        "strong_decliners_lt_minus3_pct": metric("跌幅超过3%占比", pct(strong_decliners_ratio), "%", False),
        "strong_spread_pct": metric("强势股-弱势股占比差", pct(strong_spread), "%", True),
        "limit_up": metric("涨停数", limit_up, "家", True),
        "limit_down": metric("跌停数", limit_down, "家", False),
        "max_limit_up_streak": metric("最高连板", max_streak, "板", True),
    }
    evidences = [
        evidence("上涨家数占比", pct(advancer_ratio), "%", adv_score, 4, "宽度不足时，指数上涨容易变成少数主线行情。"),
        evidence("行业上涨占比", pct(industry_up_ratio), "%", industry_score, 3, "行业扩散越充分，行情越健康。"),
        evidence("个股中位数涨跌", median_pct_change, "%", median_score, 2.5, "中位数涨跌能直接衡量多数股票的真实赚钱效应。"),
        evidence("强势股-弱势股占比差", pct(strong_spread), "%", strong_score, 2, "涨幅超3%多于跌幅超3%时，赚钱效应更扎实。"),
        evidence("涨跌停结构", f"{int(limit_up)}/{int(limit_down)}", "涨停/跌停", limit_score, 2, "涨停多且跌停少代表情绪仍可用。"),
        evidence("最高连板", max_streak, "板", streak_score, 1, "连板高度衡量短线风险偏好。"),
        evidence("指数与宽度一致性", "", "", consistency_score, 0.5, "指数强但宽度弱时降分。"),
    ]
    strength = module_strength(score, "breadth")
    if strength == "偏强":
        summary = f"市场宽度偏强，上涨家数占比{pct(advancer_ratio) or '--'}%，个股中位数涨跌{signed_pct_text(median_pct_change)}。"
    elif strength == "偏弱":
        summary = f"市场宽度偏弱，上涨家数占比{pct(advancer_ratio) or '--'}%，赚钱效应扩散不足。"
    else:
        summary = f"市场宽度中性，上涨家数占比{pct(advancer_ratio) or '--'}%，赚钱效应仍偏结构性。"
    return module_result("breadth", score, summary, evidences, metrics)


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
    strength = module_strength(score, "liquidity")
    summary = f"成交与流动性{strength}，指数平均量能比{round2(avg_volume_ratio) or '--'}倍，中小盘成交占比{pct(active_share) or '--'}%。"
    return module_result("liquidity", score, summary, evidences, metrics)


def capital_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    cap = snapshot.get("capital_flow", {}) or {}
    rolling = rolling_market_features(snapshot).get("capital_flow", {}) or {}
    north = as_float(cap.get("northbound_net_inflow_100m_cny"))
    main = as_float(cap.get("main_net_inflow_100m_cny"))
    north_5d = as_float(rolling.get("northbound_5d_sum_100m_cny"))
    main_5d = as_float(rolling.get("main_5d_sum_100m_cny"))
    north_sample_count = rolling.get("northbound_sample_count")
    main_sample_count = rolling.get("main_sample_count")

    north_score = scale(north, -50, 80, 3)
    main_score = scale(main, -800, 300, 4)
    if north is not None and main is not None and north > 0 and main < 0:
        consistency_score = 0.9
    elif north is not None and main is not None and north > 0 and main > 0:
        consistency_score = 3.0
    elif north is not None and main is not None and north < 0 and main < 0:
        consistency_score = 0.5
    else:
        consistency_score = 1.5

    north_5d_raw_score = scale(north_5d, -150, 250, 2)
    main_5d_raw_score = scale(main_5d, -2500, 800, 3)
    north_5d_score = cap_score_when_sample_short(north_5d_raw_score, 2, north_sample_count)
    main_5d_score = cap_score_when_sample_short(main_5d_raw_score, 3, main_sample_count)

    score = north_score + main_score + consistency_score + north_5d_score + main_5d_score
    metrics = {
        "northbound_net_inflow_100m_cny": metric("北向净流入", north, "亿元", True),
        "main_net_inflow_100m_cny": metric("主力净流入", main, "亿元", True),
        "northbound_5d_sum_100m_cny": metric("北向5日净流入", north_5d, "亿元", True),
        "main_5d_sum_100m_cny": metric("主力5日净流入", main_5d, "亿元", True),
        "northbound_5d_sample_count": metric("北向滚动样本数", north_sample_count, "日", True),
        "main_5d_sample_count": metric("主力滚动样本数", main_sample_count, "日", True),
        "flow_direction_pair": {
            "label": "内外资方向",
            "value": "同向流入" if north is not None and main is not None and north > 0 and main > 0 else "分歧或偏弱",
            "unit": "",
            "higher_is_better": True,
        },
    }
    evidences = [
        evidence("北向当日净流入", north, "亿元", north_score, 3, "外资当日方向对风险偏好有边际影响。"),
        evidence("主力当日净流入", main, "亿元", main_score, 4, "主力资金代表内资承接和兑现压力。"),
        evidence("内外资一致性", "", "", consistency_score, 3, "北向和主力同向时更可靠，背离时降分。"),
        evidence("北向5日持续性", north_5d, "亿元", north_5d_score, 2, "样本少于4日时最多按中性持续性计分。"),
        evidence("主力5日持续性", main_5d, "亿元", main_5d_score, 3, "样本少于4日时最多按中性资金确认计分。"),
    ]
    strength = module_strength(score, "capital_flow")
    if north is not None and main is not None and north > 0 and main > 0:
        direction = "内外资同向流入"
    elif north is not None and main is not None and north > 0 and main < 0:
        direction = "北向流入但主力流出"
    elif north is not None and main is not None and north < 0 and main < 0:
        direction = "内外资同向流出"
    else:
        direction = "内外资方向分歧或数据不完整"
    summary = f"资金面{strength}，{direction}，5日样本北向{north_sample_count or 0}日、主力{main_sample_count or 0}日。"
    return module_result("capital_flow", score, summary, evidences, metrics)


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
    rolling = rolling_market_features(snapshot).get("mainline", {}) or {}
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
    repeat_ratio = as_float(rolling.get("current_group_repeat_ratio_5d"))
    top_flow_5d = as_float(rolling.get("top_flow_5d_sum_100m_cny"))
    rolling_sample_count = rolling.get("sample_count")

    return_score = scale(return_avg, 0, 4, 3.5)
    flow_score = scale(top_flow_sum, 0, 250, 3.5)
    alignment_score = scale(overlap_count, 0, 2, 3)
    breadth_score = scale(flow_group_count, 1, 4, 2)
    continuity_raw_score = scale(repeat_ratio, 0.2, 0.8, 3)
    continuity_score = cap_score_when_sample_short(continuity_raw_score, 3, rolling_sample_count)
    score = return_score + flow_score + alignment_score + breadth_score + continuity_score

    metrics = {
        "top5_return_avg_pct": metric("涨幅前五行业均值", return_avg, "%", True),
        "top5_industry_inflow_sum_100m_cny": metric("前五行业净流入合计", top_flow_sum, "亿元", True),
        "top5_industry_inflow_5d_sum_100m_cny": metric("前五行业5日净流入合计", top_flow_5d, "亿元", True),
        "price_flow_overlap_count": metric("价量重合主线数", overlap_count, "组", True),
        "flow_group_count": metric("资金主线组数", flow_group_count, "组", True),
        "current_group_repeat_ratio_5d_pct": metric("当前主线5日重复率", pct(repeat_ratio), "%", True),
        "mainline_rolling_sample_count": metric("主线连续性样本数", rolling_sample_count, "日", True),
        "top_flow_concentration_pct": metric("第一主线资金占比", pct(concentration), "%", False),
    }
    evidences = [
        evidence("涨幅前五行业均值", return_avg, "%", return_score, 3.5, "领涨行业涨幅越强，主线越清晰。"),
        evidence("前五行业净流入合计", top_flow_sum, "亿元", flow_score, 3.5, "资金集中流入说明主线有承接。"),
        evidence("价量重合主线数", overlap_count, "组", alignment_score, 3, "涨幅榜和资金榜重合越高越可靠。"),
        evidence("资金主线组数", flow_group_count, "组", breadth_score, 2, "主线过窄时降低扩仓质量。"),
        evidence("当前主线5日重复率", pct(repeat_ratio), "%", continuity_score, 3, "样本少于4日时最多按中性连续性计分。"),
    ]
    strength = module_strength(score, "mainline")
    if strength == "偏强":
        summary = f"主线强度偏强，价量重合{overlap_count}组，前五行业净流入{round2(top_flow_sum) or 0}亿元。"
    elif strength == "偏弱":
        summary = f"主线强度偏弱，价量重合{overlap_count}组，资金和涨幅共振不足。"
    else:
        summary = f"主线强度中性，价量重合{overlap_count}组，仍以结构性机会为主。"
    return module_result("mainline", score, summary, evidences, metrics)


def valuation(snapshot: dict[str, Any]) -> dict[str, Any]:
    valuation_data = snapshot.get("valuation") or snapshot.get("repricing") or {}
    market = valuation_data.get("market", {}) or {}
    indices = valuation_data.get("indices", {}) or {}
    value_score_pct = as_float(market.get("valuation_score"))
    pe_value_score = as_float(market.get("index_pe_value_score"))
    pb_value_score = as_float(market.get("index_pb_value_score"))
    erp_value_score = as_float(market.get("erp_value_score"))

    if value_score_pct is None:
        score = 7.5
        summary = "估值数据缺失，按中性处理并降低置信度。"
        metrics = {
            "valuation_data_available": metric("估值数据可用", 0, "", True),
            "neutral_valuation_score_pct": metric("中性估值分", 50, "%", None),
            "valuation_index_count": metric("估值指数样本数", len(indices), "个", True),
        }
        evidences = [
            evidence("估值分位", "缺失", "", 7.5, 15, "缺估值时不主观乐观，先给中性分。"),
        ]
    else:
        composite_score = scale(value_score_pct, 0, 100, 6)
        pe_score = scale(pe_value_score, 0, 100, 3)
        pb_score = scale(pb_value_score, 0, 100, 3)
        erp_score = scale(erp_value_score, 0, 100, 3) if erp_value_score is not None else 1.5
        score = composite_score + pe_score + pb_score + erp_score
        if value_score_pct >= 65:
            summary = "宽基估值相对五年历史偏便宜，估值锚对中期仓位有支撑。"
        elif value_score_pct <= 35:
            summary = "宽基估值相对五年历史偏贵，趋势行情需要更强风控约束。"
        else:
            summary = "宽基估值处于中性区间，估值不构成明显加分或减分。"
        metrics = {
            "valuation_data_available": metric("估值数据可用", 1, "", True),
            "market_valuation_score_pct": metric("市场估值便宜度", value_score_pct, "%", True),
            "index_pe_value_score_pct": metric("PE便宜度", pe_value_score, "%", True),
            "index_pb_value_score_pct": metric("PB便宜度", pb_value_score, "%", True),
            "erp_value_score_pct": metric("股债性价比便宜度", erp_value_score, "%", True),
            "valuation_index_count": metric("估值指数样本数", len(indices), "个", True),
        }
        evidences = [
            evidence("综合估值便宜度", value_score_pct, "%", composite_score, 6, "分数越高代表相对五年分位越便宜。"),
            evidence("PE便宜度", pe_value_score, "%", pe_score, 3, "盈利口径估值越低越有安全边际。"),
            evidence("PB便宜度", pb_value_score, "%", pb_score, 3, "净资产口径用于约束泡沫风险。"),
            evidence("股债性价比", erp_value_score if erp_value_score is not None else "缺失", "%", erp_score, 3, "缺少ERP时先给中性，后续可接入股债利差。"),
        ]
    return module_result("valuation", score, summary, evidences, metrics)


def snapshot_basis_date(snapshot: dict[str, Any]) -> date | None:
    return parse_date_value(snapshot.get("date") or (snapshot.get("market", {}) or {}).get("as_of_trade_date"))


def dated_feature_is_future(snapshot: dict[str, Any], row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    basis = snapshot_basis_date(snapshot)
    observation_date = parse_date_value(row.get("date") or row.get("trade_date") or row.get("observation_date"))
    return bool(basis and observation_date and observation_date > basis)


def macro_value_for_scoring(snapshot: dict[str, Any], row: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(row, dict) or dated_feature_is_future(snapshot, row):
        return None
    for key in keys:
        value = as_float(row.get(key))
        if value is not None:
            return value
    return None


def future_dated_feature_warnings(snapshot: dict[str, Any]) -> list[str]:
    basis = snapshot_basis_date(snapshot)
    if basis is None:
        return []
    macro_data = snapshot.get("macro", {}) or {}
    rows: list[tuple[str, Any]] = [
        ("macro.us_10y_treasury_yield_pct", macro_data.get("us_10y_treasury_yield_pct")),
        ("macro.dxy", macro_data.get("dxy")),
        ("macro.usd_cny", macro_data.get("usd_cny")),
        ("macro.china_10y_government_bond_yield_pct", macro_data.get("china_10y_government_bond_yield_pct")),
    ]
    fred_rows = macro_data.get("fred_key_indicators", {}) or {}
    if isinstance(fred_rows, dict):
        rows.extend((f"macro.fred_key_indicators.{key}", value) for key, value in fred_rows.items())

    warnings = []
    for field_name, row in rows:
        if not isinstance(row, dict):
            continue
        observation_date = parse_date_value(row.get("date") or row.get("trade_date") or row.get("observation_date"))
        if observation_date and observation_date > basis:
            warnings.append(
                f"{field_name}: observation date {observation_date.isoformat()} is after "
                f"basis_trade_date {basis.isoformat()}; excluded from scoring"
            )
    return warnings


def rolling_sample_warnings(rolling: dict[str, Any]) -> list[str]:
    checks = [
        (
            "capital_flow.northbound_5d_sum_100m_cny",
            ((rolling.get("capital_flow", {}) or {}).get("northbound_sample_count")),
        ),
        (
            "capital_flow.main_5d_sum_100m_cny",
            ((rolling.get("capital_flow", {}) or {}).get("main_sample_count")),
        ),
        (
            "breadth.advancer_ratio_5d_avg_pct",
            ((rolling.get("breadth", {}) or {}).get("sample_count")),
        ),
        (
            "mainline.current_group_repeat_ratio_5d",
            ((rolling.get("mainline", {}) or {}).get("sample_count")),
        ),
    ]
    warnings = []
    for field_name, sample_count in checks:
        count = as_float(sample_count)
        if count is None or count < MIN_ROLLING_SAMPLE_COUNT:
            shown_count = int(count) if count is not None else 0
            warnings.append(
                f"{field_name}: rolling sample insufficient "
                f"({shown_count}/{MIN_ROLLING_SAMPLE_COUNT}); capped persistence score and lowered confidence"
            )
    return warnings


def macro(snapshot: dict[str, Any]) -> dict[str, Any]:
    macro_data = snapshot.get("macro", {}) or {}
    us10 = macro_value_for_scoring(snapshot, macro_data.get("us_10y_treasury_yield_pct"), "value", "value_pct")
    dxy = macro_value_for_scoring(snapshot, macro_data.get("dxy"), "value", "value_pct")
    usd_cny = macro_value_for_scoring(snapshot, macro_data.get("usd_cny"), "value", "value_pct")
    cn10_row = macro_data.get("china_10y_government_bond_yield_pct") or {}
    cn10 = macro_value_for_scoring(snapshot, cn10_row, "value_pct", "value")

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
    strength = module_strength(score, "macro")
    if strength == "偏强":
        summary = f"宏观与外部环境偏强，中国10Y为{round2(cn10) or '--'}%，美元指数{round2(dxy) or '--'}。"
    elif strength == "偏弱":
        summary = f"宏观与外部环境偏弱，美国10Y为{round2(us10) or '--'}%，美元或汇率压力较高。"
    else:
        summary = f"宏观与外部环境中性，中国10Y为{round2(cn10) or '--'}%，美元指数{round2(dxy) or '--'}。"
    return module_result("macro", score, summary, evidences, metrics)


def crowding_penalty(snapshot: dict[str, Any], modules: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    breadth = snapshot.get("breadth", {}) or {}
    cap = snapshot.get("capital_flow", {}) or {}
    rotation = snapshot.get("sector_rotation", {}) or {}
    indices = snapshot.get("market", {}).get("indices", {}) or {}
    valuation_market = ((snapshot.get("valuation") or snapshot.get("repricing") or {}).get("market", {}) or {})
    volatility_market = (snapshot.get("volatility", {}) or {}).get("market", {}) or {}

    advancers = as_float(breadth.get("advancers")) or 0
    total = as_float(breadth.get("total")) or 0
    advancer_ratio = advancers / total if total else None
    if modules["index_trend"]["score"] >= 12:
        breadth_penalty = penalty_scale(advancer_ratio, 0.45, 0.35, 5)
        if breadth_penalty > 0:
            items.append({"label": "指数强但上涨家数不足", "penalty": round2(breadth_penalty), "basis": f"上涨家数占比 {pct(advancer_ratio)}%"})

    chinext = indices.get("399006.SZ", {})
    chinext_ret5 = as_float(chinext.get("return_5d_pct"))
    chinext_dev = as_float(chinext.get("ma20_deviation_pct"))
    overheat_penalty = max(
        penalty_scale(chinext_ret5, 4, 8, 4),
        penalty_scale(chinext_dev, 3, 7, 4),
    )
    if overheat_penalty > 0:
        items.append({"label": "成长方向短线过热", "penalty": round2(overheat_penalty), "basis": f"创业板5日 {round2(chinext_ret5)}%，MA20偏离 {round2(chinext_dev)}%"})

    north = as_float(cap.get("northbound_net_inflow_100m_cny"))
    main = as_float(cap.get("main_net_inflow_100m_cny"))
    outflow_penalty = penalty_scale(main, -200, -600, 4) if north is not None and north > 0 else 0
    if outflow_penalty > 0:
        items.append({"label": "北向流入但主力大幅流出", "penalty": round2(outflow_penalty), "basis": f"北向 {round2(north)} 亿，主力 {round2(main)} 亿"})

    top_flows = rotation.get("top5_industries_by_capital_inflow", []) or []
    top_flow_sum = sum(as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows)
    top_flow_max = max([as_float(row.get("net_amount_100m_cny")) or 0 for row in top_flows] or [0])
    concentration = top_flow_max / top_flow_sum if top_flow_sum else None
    concentration_penalty = penalty_scale(concentration, 0.55, 0.75, 3)
    if concentration_penalty > 0:
        items.append({"label": "资金过度集中在单一主线", "penalty": round2(concentration_penalty), "basis": f"第一主线资金占比 {pct(concentration)}%"})

    valuation_score = as_float(valuation_market.get("valuation_score"))
    valuation_bubble_penalty = penalty_scale(valuation_score, 35, 15, 5)
    if valuation_bubble_penalty > 0:
        items.append({"label": "全市场估值偏贵", "penalty": round2(valuation_bubble_penalty), "basis": f"估值便宜度 {round2(valuation_score)}%"})

    realized_vol_30d = as_float(volatility_market.get("realized_vol_30d"))
    volatility_penalty = penalty_scale(realized_vol_30d, 0.18, 0.32, 5)
    if volatility_penalty > 0:
        items.append({"label": "市场波动率偏高", "penalty": round2(volatility_penalty), "basis": f"30日年化波动 {pct(realized_vol_30d)}%"})

    avg_volume_ratio = as_float((modules["liquidity"].get("metrics", {}).get("avg_volume_ratio", {}) or {}).get("value"))
    liquidity_starvation_penalty = penalty_scale(avg_volume_ratio, 0.85, 0.65, 3)
    if liquidity_starvation_penalty > 0:
        items.append({"label": "流动性显著萎缩", "penalty": round2(liquidity_starvation_penalty), "basis": f"指数平均量能比 {round2(avg_volume_ratio)}"})

    if valuation_score is None:
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
            "market_valuation_score_pct": metric("市场估值便宜度", valuation_score, "%", True),
            "realized_vol_30d_pct": metric("30日年化波动率", pct(realized_vol_30d), "%", False),
            "avg_volume_ratio": metric("指数平均量能比", avg_volume_ratio, "倍", True),
        },
    }


def position_range(score: float) -> str:
    if score <= 20:
        return "0%-20%"
    if score <= 35:
        return "20%-40%"
    if score <= 50:
        return "40%-60%"
    if score <= 65:
        return "55%-75%"
    if score <= 80:
        return "75%-90%"
    return "90%-100%"


def normalize_annual_vol(value: Any) -> float | None:
    number = as_float(value)
    if number is None:
        return None
    if number > 1:
        return number / 100
    return number


def data_quality_with_warnings(data_quality: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(data_quality or {})
    warnings = result.get("warnings", [])
    if isinstance(warnings, list):
        result["warnings"] = list(warnings)
    elif warnings:
        result["warnings"] = [str(warnings)]
    else:
        result["warnings"] = []
    return result


def add_quality_warning(data_quality: dict[str, Any], warning: str) -> None:
    warnings = data_quality.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def module_score_pct(modules: dict[str, Any], key: str) -> float | None:
    module = modules.get(key, {}) or {}
    score_pct = as_float(module.get("score_pct"))
    if score_pct is not None:
        return score_pct / 100 if score_pct > 1 else score_pct
    score = as_float(module.get("score"))
    weight = as_float(module.get("weight")) or as_float(MODULES.get(key, {}).get("weight"))
    if score is None or not weight:
        return None
    return clamp(score / weight, 0, 1)


def valuation_data_missing(snapshot: dict[str, Any], data_quality: dict[str, Any]) -> bool:
    valuation_market = ((snapshot.get("valuation") or snapshot.get("repricing") or {}).get("market", {}) or {})
    return as_float(valuation_market.get("valuation_score")) is None


def volatility_data_missing(snapshot: dict[str, Any], data_quality: dict[str, Any]) -> bool:
    volatility_market = (snapshot.get("volatility", {}) or {}).get("market", {}) or {}
    return normalize_annual_vol(volatility_market.get("realized_vol_30d")) is None


def risk_cap(reason: str, score_cap: float, severity: str, evidence_data: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "score_cap": round2(score_cap),
        "severity": severity,
        "evidence": evidence_data,
        "message": message,
    }


def evaluate_risk_caps(
    pre_cap_score: float,
    opportunity_score: float,
    crowding_penalty_value: float,
    modules: dict[str, Any],
    snapshot: dict[str, Any],
    data_quality: dict[str, Any],
) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    valuation_score_pct = module_score_pct(modules, "valuation")
    realized_volatility = normalize_annual_vol(((snapshot.get("volatility", {}) or {}).get("market", {}) or {}).get("realized_vol_30d"))
    valuation_missing = valuation_data_missing(snapshot, data_quality)
    volatility_missing = volatility_data_missing(snapshot, data_quality)
    index_trend_score_pct = module_score_pct(modules, "index_trend")
    breadth_score_pct = module_score_pct(modules, "breadth")

    evidence_base = {
        "pre_cap_market_position_score": round2(pre_cap_score),
        "opportunity_score": round2(opportunity_score),
        "crowding_penalty": round2(crowding_penalty_value),
        "valuation_score_pct": round2(valuation_score_pct),
        "realized_volatility_30d": round2(realized_volatility),
    }

    if crowding_penalty_value >= 20:
        caps.append(
            risk_cap(
                "high_crowding_extreme",
                50,
                "high",
                evidence_base,
                "拥挤惩罚达到极高区间，股票账户仓位分上限限制为50。",
            )
        )
    elif crowding_penalty_value >= 15:
        caps.append(
            risk_cap(
                "high_crowding",
                60,
                "medium",
                evidence_base,
                "拥挤惩罚偏高，股票账户仓位分上限限制为60。",
            )
        )

    if valuation_score_pct is not None and valuation_score_pct <= 0.15:
        caps.append(
            risk_cap(
                "extreme_expensive_valuation",
                50,
                "high",
                evidence_base,
                "估值模块得分极低，泡沫估值风险触发仓位分上限。",
            )
        )
    elif valuation_score_pct is not None and valuation_score_pct <= 0.25:
        caps.append(
            risk_cap(
                "expensive_valuation",
                55,
                "medium",
                evidence_base,
                "估值模块得分偏低，股票账户仓位分上限限制为55。",
            )
        )

    if valuation_score_pct is not None and valuation_score_pct <= 0.25 and realized_volatility is not None and realized_volatility >= 0.25:
        caps.append(
            risk_cap(
                "bubble_top_combo",
                35,
                "high",
                evidence_base,
                "估值极贵且波动率偏高，泡沫顶部风险触发强仓位上限。",
            )
        )

    if realized_volatility is not None and realized_volatility >= 0.40:
        caps.append(
            risk_cap(
                "extreme_high_volatility",
                35,
                "high",
                evidence_base,
                "30日年化波动率进入极高区间，股票账户仓位分上限限制为35。",
            )
        )
    elif realized_volatility is not None and realized_volatility >= 0.30:
        caps.append(
            risk_cap(
                "high_volatility",
                55,
                "medium",
                evidence_base,
                "30日年化波动率偏高，股票账户仓位分上限限制为55。",
            )
        )

    if opportunity_score >= 70 and valuation_missing:
        add_quality_warning(data_quality, "valuation data missing; stock account position capped")
        caps.append(
            risk_cap(
                "missing_valuation_data_hot_market",
                65,
                "medium",
                evidence_base,
                "高机会分行情缺少估值数据，股票账户仓位分上限限制为65。",
            )
        )
    if opportunity_score >= 70 and volatility_missing:
        add_quality_warning(data_quality, "volatility data missing; stock account position capped")
        caps.append(
            risk_cap(
                "missing_volatility_data_hot_market",
                65,
                "medium",
                evidence_base,
                "高机会分行情缺少波动率数据，股票账户仓位分上限限制为65。",
            )
        )
    if opportunity_score >= 65 and valuation_missing and volatility_missing:
        add_quality_warning(data_quality, "valuation and volatility data missing; stock account position capped")
        caps.append(
            risk_cap(
                "missing_core_risk_data_hot_market",
                50,
                "high",
                evidence_base,
                "高机会分行情同时缺少估值和波动率，股票账户仓位分上限限制为50。",
            )
        )

    if (
        index_trend_score_pct is not None
        and breadth_score_pct is not None
        and index_trend_score_pct >= 0.75
        and breadth_score_pct <= 0.40
    ):
        caps.append(
            risk_cap(
                "strong_index_weak_breadth",
                60,
                "medium",
                {
                    **evidence_base,
                    "index_trend_score_pct": round2(index_trend_score_pct),
                    "breadth_score_pct": round2(breadth_score_pct),
                },
                "指数趋势强但市场宽度弱，局部抱团风险触发仓位分上限。",
            )
        )

    return caps


def apply_position_policy(
    opportunity_score: float,
    crowding: dict[str, Any],
    modules: dict[str, Any],
    snapshot: dict[str, Any],
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    crowding_penalty_value = as_float(crowding.get("penalty")) or 0
    pre_cap_score = round2(clamp(opportunity_score - crowding_penalty_value, 0, 100)) or 0
    caps = evaluate_risk_caps(pre_cap_score, opportunity_score, crowding_penalty_value, modules, snapshot, data_quality)
    cap_values = [as_float(cap.get("score_cap")) for cap in caps if as_float(cap.get("score_cap")) is not None]
    final_score = round2(clamp(min([pre_cap_score, *cap_values]) if cap_values else pre_cap_score, 0, 100)) or 0
    recommended_range = position_range(final_score)
    return {
        "account_scope": "stock_account",
        "position_policy_version": POSITION_POLICY_VERSION,
        "pre_cap_market_position_score": pre_cap_score,
        "market_position_score": final_score,
        "risk_caps": caps,
        "recommended_equity_position_range": recommended_range,
        "base_equity_position_range": recommended_range,
        "equity_position_range": recommended_range,
    }


def volatility_policy(snapshot: dict[str, Any]) -> dict[str, Any]:
    market = (snapshot.get("volatility", {}) or {}).get("market", {}) or {}
    realized_vol = normalize_annual_vol(market.get("realized_vol_30d"))
    return {
        "mode": "risk_indicator_only",
        "target_annual_vol": None,
        "realized_volatility_30d": round2(realized_vol),
        "status": "available" if realized_vol is not None else "unavailable",
        "note": "股票账户仓位不再按8%年化目标波动率缩放；波动率仅用于风险扣分、风险上限和提示。",
    }


def legacy_volatility_targeting(snapshot: dict[str, Any], base_score: float, base_range: str) -> dict[str, Any]:
    market = (snapshot.get("volatility", {}) or {}).get("market", {}) or {}
    realized_vol = normalize_annual_vol(market.get("realized_vol_30d"))
    target_vol = as_float(market.get("target_annual_vol")) or 0.08
    if realized_vol is None or realized_vol <= 0:
        scale_factor = 1.0
        status = "unavailable"
        note = "旧版8%目标波动率字段，仅供历史兼容，不作为股票账户官方仓位建议。"
    else:
        scale_factor = clamp(target_vol / realized_vol, 0.25, 1.15)
        status = "active"
        note = "旧版8%目标波动率缩放结果已废弃，仅供历史兼容，不作为股票账户官方仓位建议。"

    parsed_range = parse_percent_range(base_range)
    adjusted_range = None
    if parsed_range is not None:
        adjusted_range = (parsed_range[0] * scale_factor, parsed_range[1] * scale_factor)

    return {
        "status": status,
        "target_annual_vol": round2(target_vol),
        "realized_vol_30d": round2(realized_vol),
        "scale_factor": round2(scale_factor),
        "base_position_score": round2(base_score),
        "adjusted_position_score": round2(clamp(base_score * scale_factor, 0, 100)),
        "base_equity_position_range": base_range,
        "adjusted_equity_position_range": format_percent_range(adjusted_range),
        "deprecated": True,
        "note": note,
    }


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


def confidence(snapshot: dict[str, Any], data_quality: dict[str, Any] | None = None) -> str:
    quality = data_quality if data_quality is not None else (snapshot.get("data_quality", {}) or {})
    missing = quality.get("missing_fields", []) or []
    warnings = quality.get("warnings", []) or []
    valuation_market = ((snapshot.get("valuation") or snapshot.get("repricing") or {}).get("market", {}) or {})
    valuation_missing = as_float(valuation_market.get("valuation_score")) is None
    volatility_missing = as_float(((snapshot.get("volatility", {}) or {}).get("market", {}) or {}).get("realized_vol_30d")) is None

    core_prefixes = [
        "market.indices",
        "breadth.",
        "capital_flow.northbound_net_inflow_100m_cny",
        "capital_flow.main_net_inflow_100m_cny",
    ]
    important_prefixes = [
        "capital_flow.turnover_distribution",
        "sector_rotation.",
        "valuation.",
        "volatility.",
        "macro.",
    ]
    auxiliary_prefixes = [
        "qmt_portfolio",
        "data_quality.cross_validation",
    ]

    core_missing = any(any(str(field).startswith(prefix) for prefix in core_prefixes) for field in missing)
    important_missing = any(any(str(field).startswith(prefix) for prefix in important_prefixes) for field in missing)
    auxiliary_only = missing and all(any(str(field).startswith(prefix) for prefix in auxiliary_prefixes) for field in missing)
    rolling_sample_insufficient = any("rolling sample insufficient" in str(warning) for warning in warnings)

    if core_missing:
        return "low"
    if valuation_missing or volatility_missing or important_missing or rolling_sample_insufficient:
        return "medium"
    if auxiliary_only:
        return "high"
    if missing:
        return "medium"
    return "high"


def validate_market_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []

    def err(field: str, message: str) -> None:
        errors.append(f"{field}: {message}")

    def require_object(field: str) -> dict[str, Any]:
        value = snapshot.get(field)
        if not isinstance(value, dict):
            err(field, "required object")
            return {}
        return value

    def require_number(container: dict[str, Any], field: str, label: str) -> None:
        if as_float(container.get(field)) is None:
            err(label, "required numeric value")

    if not isinstance(snapshot, dict):
        raise MarketSnapshotValidationError("market snapshot must be an object")

    trade_date = parse_date_value(snapshot.get("date"))
    if trade_date is None:
        err("date", "required ISO date")

    market = require_object("market")
    market_date = parse_date_value(market.get("as_of_trade_date"))
    if market_date is None:
        err("market.as_of_trade_date", "required ISO date")
    elif trade_date is not None and market_date != trade_date:
        err("market.as_of_trade_date", "must match snapshot date")
    indices = market.get("indices")
    if not isinstance(indices, dict) or not indices:
        err("market.indices", "required non-empty object")
    else:
        for code in ["000001.SH", "399001.SZ", "399006.SZ"]:
            row = indices.get(code)
            if not isinstance(row, dict):
                err(f"market.indices.{code}", "required object")
            else:
                require_number(row, "close", f"market.indices.{code}.close")

    breadth = require_object("breadth")
    for field in ["advancers", "decliners", "total"]:
        require_number(breadth, field, f"breadth.{field}")

    capital_flow = require_object("capital_flow")
    for field in ["northbound_net_inflow_100m_cny", "main_net_inflow_100m_cny"]:
        require_number(capital_flow, field, f"capital_flow.{field}")
    turnover = capital_flow.get("turnover_distribution")
    if not isinstance(turnover, dict):
        err("capital_flow.turnover_distribution", "required object")
    else:
        for bucket in ["large_cap", "mid_cap", "small_cap"]:
            row = turnover.get(bucket)
            if not isinstance(row, dict):
                err(f"capital_flow.turnover_distribution.{bucket}", "required object")
            elif as_float(row.get("share")) is None:
                err(f"capital_flow.turnover_distribution.{bucket}.share", "required numeric value")

    sector_rotation = require_object("sector_rotation")
    for field in ["top5_industries_by_return", "top5_industries_by_capital_inflow"]:
        rows = sector_rotation.get(field)
        if not isinstance(rows, list) or not rows:
            err(f"sector_rotation.{field}", "required non-empty list")
        elif not all(isinstance(row, dict) for row in rows):
            err(f"sector_rotation.{field}", "must contain objects")

    valuation = require_object("valuation")
    if not isinstance(valuation.get("market"), dict):
        err("valuation.market", "required object")

    volatility = require_object("volatility")
    if not isinstance(volatility.get("market"), dict):
        err("volatility.market", "required object")

    macro_data = snapshot.get("macro")
    if not isinstance(macro_data, dict):
        err("macro", "required object")

    data_quality = require_object("data_quality")
    for field in ["missing_fields", "warnings"]:
        if not isinstance(data_quality.get(field), list):
            err(f"data_quality.{field}", "required list")

    if errors:
        raise MarketSnapshotValidationError("; ".join(errors))
    return {
        "ok": True,
        "basis_trade_date": snapshot.get("date"),
        "checked_fields": [
            "date",
            "market.indices",
            "breadth",
            "capital_flow",
            "sector_rotation",
            "valuation.market",
            "volatility.market",
            "macro",
            "data_quality",
        ],
    }


def score_snapshot(snapshot: dict[str, Any], snapshot_path: Path | None = None, snapshot_bytes: bytes | None = None) -> dict[str, Any]:
    snapshot_validation = validate_market_snapshot(snapshot)
    rolling = rolling_market_features(snapshot)
    quality = data_quality_with_warnings(snapshot.get("data_quality", {}))
    for warning in future_dated_feature_warnings(snapshot):
        add_quality_warning(quality, warning)
    for warning in rolling_sample_warnings(rolling):
        add_quality_warning(quality, warning)
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
    position_policy = apply_position_policy(opportunity, crowding, modules, snapshot, quality)
    final_score = position_policy["market_position_score"]
    pre_cap_score = position_policy["pre_cap_market_position_score"]
    recommended_range = position_policy["recommended_equity_position_range"]
    vol_policy = volatility_policy(snapshot)
    legacy_vol_targeting = legacy_volatility_targeting(snapshot, final_score, recommended_range)
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
        "估值分位偏贵时，即使趋势强也要用拥挤惩罚和风险上限约束泡沫风险。",
        "股票账户官方仓位不再按8%目标波动率缩放，波动率仅作为风险扣分、上限和提示。",
    ]
    record = {
        "run_id": f"{datetime.now(TZ).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}",
        "model_version": MODEL_VERSION,
        "score_schema_version": SCORE_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "account_scope": position_policy["account_scope"],
        "position_policy_version": position_policy["position_policy_version"],
        "scored_at": now,
        "basis_trade_date": snapshot.get("date") or (snapshot.get("market", {}) or {}).get("as_of_trade_date"),
        "snapshot_file": snapshot_label,
        "snapshot_sha256": snapshot_hash,
        "market_regime": regime(opportunity, final_score, modules, crowding),
        "market_opportunity_score": opportunity,
        "opportunity_score": opportunity,
        "crowding_penalty": crowding["penalty"],
        "pre_cap_market_position_score": pre_cap_score,
        "market_position_score": final_score,
        "base_market_position_score": final_score,
        "recommended_equity_position_range": recommended_range,
        "confidence": confidence(snapshot, quality),
        "equity_position_range": recommended_range,
        "base_equity_position_range": recommended_range,
        "risk_caps": position_policy["risk_caps"],
        "volatility_policy": vol_policy,
        "vol_adjusted_market_position_score": None,
        "vol_adjusted_equity_position_range": None,
        "legacy_vol_adjusted_market_position_score": legacy_vol_targeting.get("adjusted_position_score"),
        "legacy_vol_adjusted_equity_position_range": legacy_vol_targeting.get("adjusted_equity_position_range"),
        "legacy_vol_adjusted_deprecated": True,
        "sleeve_mix": sleeve_mix(final_score, modules, crowding),
        "shanghai_composite": round2(as_float(shanghai.get("close"))),
        "modules": modules,
        "crowding": crowding,
        "rolling_features": rolling,
        "volatility_targeting": legacy_vol_targeting,
        "factor_changes": [
            "stock account position policy v2 uses recommended_equity_position_range as the official position output",
            "risk_caps can cap final market_position_score for bubble, high volatility, crowding, missing risk data, and strong-index weak-breadth regimes",
            "8% target-volatility scaling is deprecated and no longer changes the official stock-account position range",
            "position ranges now use stock-account exposure and can reach 90%-100% in low-crowding strong trends",
            "capital_flow removed duplicate mid/small turnover and top industry inflow scoring",
            "breadth added median and strong advancer/decliner placeholders when available",
            "crowding penalties changed from hard thresholds to gradients",
            "confidence now distinguishes core, important, and auxiliary missing fields",
            "valuation now scores 5-year index PE/PB percentiles instead of a neutral placeholder",
            "capital flow and mainline modules use rolling persistence features",
        ],
        "key_constraints": key_constraints,
        "data_quality": quality,
        "snapshot_validation": snapshot_validation,
    }
    return record


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "position_policy_version": POSITION_POLICY_VERSION,
            "dedupe_key_fields": list(HISTORY_DEDUPE_KEY_FIELDS),
            "updated_at": None,
            "records": [],
        }
    payload = load_json(path)
    if isinstance(payload, list):
        payload = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "position_policy_version": POSITION_POLICY_VERSION,
            "dedupe_key_fields": list(HISTORY_DEDUPE_KEY_FIELDS),
            "updated_at": None,
            "records": payload,
        }
    try:
        payload["schema_version"] = max(int(payload.get("schema_version", 1)), HISTORY_SCHEMA_VERSION)
    except (TypeError, ValueError):
        payload["schema_version"] = HISTORY_SCHEMA_VERSION
    payload.setdefault("model_version", MODEL_VERSION)
    payload.setdefault("position_policy_version", POSITION_POLICY_VERSION)
    payload["dedupe_key_fields"] = list(HISTORY_DEDUPE_KEY_FIELDS)
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def save_history(history: dict[str, Any], path: Path = DEFAULT_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_history_audit_event(
    event_type: str,
    *,
    record: dict[str, Any] | None = None,
    dedupe_key: dict[str, Any] | None = None,
    appended: bool = False,
    duplicate: bool = False,
    status: str = "ok",
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = record if isinstance(record, dict) else {}
    return {
        "event_time": datetime.now(TZ).isoformat(timespec="seconds"),
        "event_type": event_type,
        "status": status,
        "reason": reason,
        "run_id": record.get("run_id"),
        "dedupe_key": dedupe_key if dedupe_key is not None else history_dedupe_key_payload(record),
        "appended": appended,
        "duplicate": duplicate,
        "schema_version": record.get("score_schema_version") or SCORE_SCHEMA_VERSION,
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "model_version": record.get("model_version"),
        "position_policy_version": record.get("position_policy_version"),
        "details": details or {},
    }


def write_history_audit_event(event: dict[str, Any], audit_path: Path) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def add_validation_error(errors: list[str], field: str, message: str) -> None:
    errors.append(f"{field}: {message}")


def require_non_empty_string(record: dict[str, Any], field: str, errors: list[str]) -> None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        add_validation_error(errors, field, "required non-empty string")


def require_numeric_range(record: dict[str, Any], field: str, low: float, high: float, errors: list[str], *, required: bool = True) -> None:
    value = record.get(field)
    if value is None:
        if required:
            add_validation_error(errors, field, "required number")
        return
    number = as_float(value)
    if number is None:
        add_validation_error(errors, field, "must be numeric")
        return
    if number < low or number > high:
        add_validation_error(errors, field, f"must be between {low} and {high}")


def validate_percent_range_field(record: dict[str, Any], field: str, errors: list[str], *, required: bool = False) -> None:
    value = record.get(field)
    if value in [None, ""]:
        if required:
            add_validation_error(errors, field, "required percent range")
        return
    if not isinstance(value, str):
        add_validation_error(errors, field, "must be a percent range string")
        return
    bounds = parse_percent_range(value)
    if bounds is None:
        add_validation_error(errors, field, "must use a percent range such as 40%-60%")
        return
    lower, upper = bounds
    if lower < 0 or upper > 100 or lower > upper:
        add_validation_error(errors, field, "must stay within 0%-100% and lower must not exceed upper")


def validate_score_modules(modules: Any, errors: list[str]) -> None:
    if not isinstance(modules, dict):
        add_validation_error(errors, "modules", "required object")
        return
    for key, meta in MODULES.items():
        module = modules.get(key)
        field = f"modules.{key}"
        if not isinstance(module, dict):
            add_validation_error(errors, field, "required object")
            continue
        weight = as_float(module.get("weight"))
        expected_weight = as_float(meta.get("weight"))
        if weight is None or weight <= 0:
            add_validation_error(errors, f"{field}.weight", "must be a positive number")
        elif expected_weight is not None and abs(weight - expected_weight) > 0.01:
            add_validation_error(errors, f"{field}.weight", f"must equal configured weight {expected_weight}")
        score = as_float(module.get("score"))
        if score is None:
            add_validation_error(errors, f"{field}.score", "required number")
        elif weight is not None and (score < 0 or score > weight):
            add_validation_error(errors, f"{field}.score", "must be between 0 and module weight")
        score_pct = as_float(module.get("score_pct"))
        if score_pct is None:
            add_validation_error(errors, f"{field}.score_pct", "required number")
        elif score_pct < 0 or score_pct > 100:
            add_validation_error(errors, f"{field}.score_pct", "must be between 0 and 100")


def validate_score_risk_caps(risk_caps: Any, errors: list[str]) -> None:
    if not isinstance(risk_caps, list):
        add_validation_error(errors, "risk_caps", "required list")
        return
    for index, cap in enumerate(risk_caps):
        field = f"risk_caps[{index}]"
        if not isinstance(cap, dict):
            add_validation_error(errors, field, "must be an object")
            continue
        if not isinstance(cap.get("reason"), str) or not cap.get("reason"):
            add_validation_error(errors, f"{field}.reason", "required non-empty string")
        if not isinstance(cap.get("message"), str) or not cap.get("message"):
            add_validation_error(errors, f"{field}.message", "required non-empty string")
        severity = cap.get("severity")
        if severity not in {"low", "medium", "high"}:
            add_validation_error(errors, f"{field}.severity", "must be low, medium, or high")
        score_cap = as_float(cap.get("score_cap"))
        if score_cap is None or score_cap < 0 or score_cap > 100:
            add_validation_error(errors, f"{field}.score_cap", "must be numeric and between 0 and 100")


def validate_score_record(record: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(record, dict):
        raise ScoreRecordValidationError("score record must be an object")

    for field in REQUIRED_SCORE_RECORD_STRING_FIELDS:
        require_non_empty_string(record, field, errors)
    for field, (low, high) in REQUIRED_SCORE_RECORD_NUMERIC_RANGES.items():
        require_numeric_range(record, field, low, high, errors)
    for field, (low, high) in OPTIONAL_SCORE_RECORD_NUMERIC_RANGES.items():
        require_numeric_range(record, field, low, high, errors, required=False)
    for field in SCORE_RECORD_PERCENT_RANGE_FIELDS:
        validate_percent_range_field(record, field, errors, required=field == "recommended_equity_position_range")

    if record.get("confidence") not in {"high", "medium", "low"}:
        add_validation_error(errors, "confidence", "must be high, medium, or low")
    if parse_date_value(record.get("basis_trade_date")) is None:
        add_validation_error(errors, "basis_trade_date", "must be parseable as a date")
    scored_at = record.get("scored_at")
    try:
        datetime.fromisoformat(str(scored_at))
    except Exception:
        add_validation_error(errors, "scored_at", "must be ISO-8601 datetime")

    validate_score_modules(record.get("modules"), errors)
    validate_score_risk_caps(record.get("risk_caps"), errors)
    if not isinstance(record.get("crowding"), dict):
        add_validation_error(errors, "crowding", "required object")
    if not isinstance(record.get("data_quality"), dict):
        add_validation_error(errors, "data_quality", "required object")

    if errors:
        raise ScoreRecordValidationError("; ".join(errors))
    return {
        "ok": True,
        "schema_version": SCORE_SCHEMA_VERSION,
        "checked_required_fields": list(REQUIRED_SCORE_RECORD_STRING_FIELDS)
        + list(REQUIRED_SCORE_RECORD_NUMERIC_RANGES.keys())
        + ["modules", "risk_caps", "crowding", "data_quality"],
    }


def score_record_is_current_schema(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict) or record.get("legacy_schema") is True:
        return False
    if record.get("model_version") != MODEL_VERSION or record.get("position_policy_version") != POSITION_POLICY_VERSION:
        return False
    try:
        validate_score_record(record)
    except ScoreRecordValidationError:
        return False
    return True


def legacy_schema_reason(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return "invalid_record_type"
    if record.get("legacy_schema") is True:
        return str(record.get("legacy_reason") or "legacy_schema")
    if record.get("model_version") != MODEL_VERSION:
        return "legacy_model_version"
    if record.get("position_policy_version") != POSITION_POLICY_VERSION:
        return "legacy_position_policy_version"
    try:
        validate_score_record(record)
    except ScoreRecordValidationError:
        return "invalid_current_schema"
    return "current_schema"


def legacy_record_dedupe_key(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field) or "") for field in HISTORY_DEDUPE_KEY_FIELDS)


def legacy_record_archive_id(record: dict[str, Any]) -> tuple[str, str]:
    return (str(record.get("run_id") or ""), "|".join(legacy_record_dedupe_key(record)))


def mark_legacy_record(record: dict[str, Any], migrated_at: str) -> dict[str, Any]:
    legacy = dict(record)
    legacy["legacy_schema"] = True
    legacy.setdefault("legacy_reason", legacy_schema_reason(record))
    legacy.setdefault("legacy_migrated_at", migrated_at)
    legacy.setdefault("legacy_dedupe_key", history_dedupe_key_payload(record))
    return legacy


def migrate_history_legacy_records(
    history: dict[str, Any],
    *,
    migrated_at: str | None = None,
    archive_duplicates: bool = True,
) -> dict[str, Any]:
    migrated_at = migrated_at or datetime.now(TZ).isoformat(timespec="seconds")
    source_records = history.get("records", [])
    if not isinstance(source_records, list):
        source_records = []
    existing_archive = history.get("legacy_archive", [])
    if not isinstance(existing_archive, list):
        existing_archive = []

    records: list[dict[str, Any]] = []
    archive: list[dict[str, Any]] = list(existing_archive)
    archived_ids = {legacy_record_archive_id(record) for record in archive if isinstance(record, dict)}
    seen_legacy_keys: set[tuple[str, ...]] = set()
    legacy_marked_count = 0
    legacy_archived_count = 0
    current_record_count = 0

    for raw_record in source_records:
        record = raw_record if isinstance(raw_record, dict) else {"raw_record": raw_record}
        if score_record_is_current_schema(record):
            records.append(record)
            current_record_count += 1
            continue

        legacy = mark_legacy_record(record, migrated_at)
        legacy_key = legacy_record_dedupe_key(legacy)
        duplicate_legacy = archive_duplicates and legacy_key in seen_legacy_keys
        if duplicate_legacy:
            archived = dict(legacy)
            archived["archived_reason"] = "duplicate_legacy_record"
            archived.setdefault("legacy_archived_at", migrated_at)
            archive_id = legacy_record_archive_id(archived)
            if archive_id not in archived_ids:
                archive.append(archived)
                archived_ids.add(archive_id)
                legacy_archived_count += 1
            continue

        was_legacy = isinstance(raw_record, dict) and raw_record.get("legacy_schema") is True
        had_legacy_metadata = isinstance(raw_record, dict) and all(
            key in raw_record for key in ["legacy_reason", "legacy_migrated_at", "legacy_dedupe_key"]
        )
        if not was_legacy or not had_legacy_metadata:
            legacy_marked_count += 1
        seen_legacy_keys.add(legacy_key)
        records.append(legacy)

    migrated_history = dict(history)
    migrated_history["schema_version"] = HISTORY_SCHEMA_VERSION
    migrated_history["model_version"] = MODEL_VERSION
    migrated_history["position_policy_version"] = POSITION_POLICY_VERSION
    migrated_history["dedupe_key_fields"] = list(HISTORY_DEDUPE_KEY_FIELDS)
    migrated_history["records"] = records
    migrated_history["record_count"] = len(records)
    migrated_history["legacy_record_count"] = sum(1 for record in records if isinstance(record, dict) and record.get("legacy_schema") is True)
    migrated_history["current_record_count"] = current_record_count
    migrated_history["legacy_archive"] = archive
    migrated_history["legacy_archive_count"] = len(archive)
    if legacy_marked_count or legacy_archived_count:
        migrated_history["updated_at"] = migrated_at
        migrated_history["legacy_migration"] = {
            "migrated_at": migrated_at,
            "legacy_marked_count": legacy_marked_count,
            "legacy_archived_count": legacy_archived_count,
            "archive_duplicates": archive_duplicates,
        }

    audit_event = build_history_audit_event(
        "history_migration",
        appended=False,
        duplicate=False,
        details={
            "changed": migrated_history != history,
            "legacy_marked_count": legacy_marked_count,
            "legacy_archived_count": legacy_archived_count,
            "current_record_count": current_record_count,
            "legacy_record_count": migrated_history["legacy_record_count"],
            "legacy_archive_count": len(archive),
            "archive_duplicates": archive_duplicates,
        },
    )

    return {
        "history": migrated_history,
        "changed": migrated_history != history,
        "legacy_marked_count": legacy_marked_count,
        "legacy_archived_count": legacy_archived_count,
        "current_record_count": current_record_count,
        "legacy_record_count": migrated_history["legacy_record_count"],
        "legacy_archive_count": len(archive),
        "audit_event": audit_event,
    }


def history_dedupe_key(record: dict[str, Any]) -> tuple[str, ...] | None:
    values = []
    for field in HISTORY_DEDUPE_KEY_FIELDS:
        value = record.get(field)
        if value is None or value == "":
            return None
        values.append(str(value))
    return tuple(values)


def history_dedupe_key_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in HISTORY_DEDUPE_KEY_FIELDS}


def find_duplicate_history_record(history: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    candidate_key = history_dedupe_key(record)
    if candidate_key is None:
        return None
    records = history.get("records", [])
    if not isinstance(records, list):
        return None
    for existing in records:
        if isinstance(existing, dict) and history_dedupe_key(existing) == candidate_key:
            return existing
    return None


def append_history_record(history: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    schema_validation = validate_score_record(record)
    history["schema_version"] = HISTORY_SCHEMA_VERSION
    history["model_version"] = MODEL_VERSION
    history["position_policy_version"] = POSITION_POLICY_VERSION
    history["dedupe_key_fields"] = list(HISTORY_DEDUPE_KEY_FIELDS)
    if not isinstance(history.get("records"), list):
        history["records"] = []

    duplicate = find_duplicate_history_record(history, record)
    if duplicate is not None:
        return {
            "appended": False,
            "duplicate": True,
            "record": duplicate,
            "candidate_record": record,
            "dedupe_key": history_dedupe_key_payload(record),
            "duplicate_of_run_id": duplicate.get("run_id"),
            "schema_validation": schema_validation,
            "history": history,
        }

    history["updated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    history["records"].append(record)
    return {
        "appended": True,
        "duplicate": False,
        "record": record,
        "candidate_record": record,
        "dedupe_key": history_dedupe_key_payload(record),
        "duplicate_of_run_id": None,
        "schema_validation": schema_validation,
        "history": history,
    }


def append_score_record(
    record: dict[str, Any],
    history_path: Path = DEFAULT_HISTORY_PATH,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    audit_path = audit_path or history_audit_log_path(history_path)
    history = load_history(history_path)
    try:
        result = append_history_record(history, record)
    except Exception as exc:
        audit_event = build_history_audit_event(
            "history_append_failed",
            record=record if isinstance(record, dict) else {},
            appended=False,
            duplicate=False,
            status="failed",
            reason=str(exc),
        )
        write_history_audit_event(audit_event, audit_path)
        raise
    if result["appended"]:
        save_history(history, history_path)
    audit_event = build_history_audit_event(
        "history_append" if result["appended"] else "history_duplicate",
        record=result.get("record") if isinstance(result.get("record"), dict) else record,
        dedupe_key=result.get("dedupe_key"),
        appended=bool(result.get("appended")),
        duplicate=bool(result.get("duplicate")),
        details={
            "duplicate_of_run_id": result.get("duplicate_of_run_id"),
            "candidate_run_id": (result.get("candidate_record") or {}).get("run_id")
            if isinstance(result.get("candidate_record"), dict)
            else None,
        },
    )
    write_history_audit_event(audit_event, audit_path)
    return {"history_path": str(history_path), "audit_path": str(audit_path), "audit_event": audit_event, **result}


def append_score(snapshot_path: Path = DEFAULT_SNAPSHOT_PATH, history_path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8-sig"))
    record = score_snapshot(snapshot, snapshot_path=snapshot_path, snapshot_bytes=snapshot_bytes)
    return append_score_record(record, history_path)


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
                "pre_cap_market_position_score": record["pre_cap_market_position_score"],
                "market_position_score": record["market_position_score"],
                "recommended_equity_position_range": record["recommended_equity_position_range"],
                "risk_cap_count": len(record.get("risk_caps", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
