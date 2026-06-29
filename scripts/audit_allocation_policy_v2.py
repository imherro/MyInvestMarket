from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import market_scoring


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
RISK_SLEEVE_KEYS = ["beta_core", "alpha_active", "defensive_factor"]
EXPECTED_SLEEVE_KEYS = [*RISK_SLEEVE_KEYS, "liquidity"]


def module(score_pct: float, weight: float = 10) -> dict[str, float]:
    return {"score": round(score_pct / 100 * weight, 2), "weight": weight, "score_pct": score_pct}


def modules_from_pct(**values: float) -> dict[str, dict[str, float]]:
    weights = {key: meta["weight"] for key, meta in market_scoring.MODULES.items()}
    defaults = {
        "index_trend": 50,
        "breadth": 50,
        "liquidity": 50,
        "capital_flow": 50,
        "mainline": 50,
        "valuation": 50,
        "macro": 50,
    }
    defaults.update(values)
    return {key: module(value, weights[key]) for key, value in defaults.items()}


def risk_cap(reason: str, score_cap: float = 35, severity: str = "medium") -> dict[str, Any]:
    return {"reason": reason, "score_cap": score_cap, "severity": severity, "message": reason}


def range_bounds(range_text: str | None) -> tuple[float, float]:
    parsed = market_scoring.parse_percent_range(range_text)
    if parsed is None:
        raise ValueError(f"invalid percent range: {range_text}")
    return parsed


def midpoint(range_text: str | None) -> float:
    low, high = range_bounds(range_text)
    return round((low + high) / 2, 2)


def sleeve_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {sleeve["key"]: sleeve for sleeve in policy.get("sleeves", []) if isinstance(sleeve, dict)}


def sleeve_mid(policy: dict[str, Any], key: str) -> float:
    return midpoint(sleeve_map(policy)[key]["target_range"])


def sleeve_upper(policy: dict[str, Any], key: str) -> float:
    return range_bounds(sleeve_map(policy)[key]["target_range"])[1]


def sleeve_lower(policy: dict[str, Any], key: str) -> float:
    return range_bounds(sleeve_map(policy)[key]["target_range"])[0]


def base_checks(policy: dict[str, Any]) -> list[dict[str, Any]]:
    sleeves = sleeve_map(policy)
    checks: list[dict[str, Any]] = []
    keys = list(sleeves.keys())
    checks.append(
        {
            "name": "four_expected_sleeves",
            "ok": keys == EXPECTED_SLEEVE_KEYS,
            "detail": f"actual={keys}",
        }
    )
    liquidity_low, liquidity_high = range_bounds(sleeves["liquidity"]["target_range"])
    risk_low, risk_high = range_bounds(policy["total_risk_asset_range"])
    checks.append(
        {
            "name": "liquidity_is_complement",
            "ok": abs(liquidity_low - (100 - risk_high)) <= 0.01 and abs(liquidity_high - (100 - risk_low)) <= 0.01,
            "detail": f"liquidity={liquidity_low}-{liquidity_high}, risk={risk_low}-{risk_high}",
        }
    )
    risk_mid_sum = round(sum(sleeve_mid(policy, key) for key in RISK_SLEEVE_KEYS), 2)
    risk_mid = midpoint(policy["total_risk_asset_range"])
    checks.append(
        {
            "name": "risk_sleeve_midpoints_match_total",
            "ok": abs(risk_mid_sum - risk_mid) <= 3,
            "detail": f"risk_mid_sum={risk_mid_sum}, total_mid={risk_mid}",
        }
    )
    return checks


def audit_scenario(
    *,
    key: str,
    label: str,
    position_score: float,
    opportunity_score: float,
    pre_cap_score: float,
    crowding_penalty: float,
    modules: dict[str, dict[str, float]],
    risk_caps: list[dict[str, Any]],
    thesis: str,
    expectations: list[tuple[str, Callable[[dict[str, Any]], bool]]],
) -> dict[str, Any]:
    recommended_range = market_scoring.position_range(position_score)
    policy = market_scoring.allocation_policy(
        position_score,
        opportunity_score,
        pre_cap_score,
        recommended_range,
        modules,
        {"penalty": crowding_penalty},
        {},
        risk_caps,
    )
    checks = base_checks(policy)
    checks.extend({"name": name, "ok": bool(check(policy)), "detail": thesis} for name, check in expectations)
    return {
        "key": key,
        "label": label,
        "thesis": thesis,
        "inputs": {
            "position_score": position_score,
            "opportunity_score": opportunity_score,
            "pre_cap_score": pre_cap_score,
            "crowding_penalty": crowding_penalty,
            "recommended_range": recommended_range,
            "risk_cap_reasons": [cap["reason"] for cap in risk_caps],
        },
        "policy": policy,
        "sleeve_ranges": {
            key: sleeve_map(policy)[key]["target_range"]
            for key in EXPECTED_SLEEVE_KEYS
        },
        "midpoints": {
            key: sleeve_mid(policy, key)
            for key in EXPECTED_SLEEVE_KEYS
        },
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }


def scenarios() -> list[dict[str, Any]]:
    return [
        audit_scenario(
            key="bear_bottom_repair",
            label="熊末低估但趋势未确认",
            position_score=32,
            opportunity_score=48,
            pre_cap_score=34,
            crowding_penalty=4,
            modules=modules_from_pct(index_trend=35, breadth=35, liquidity=38, capital_flow=30, mainline=25, valuation=90, macro=55),
            risk_caps=[],
            thesis="底部便宜不等于直接满仓，优先提高 beta 和防御，alpha 仍小。",
            expectations=[
                ("liquidity_still_high", lambda policy: sleeve_lower(policy, "liquidity") >= 60),
                ("beta_above_alpha", lambda policy: sleeve_mid(policy, "beta_core") > sleeve_mid(policy, "alpha_active")),
                ("alpha_not_open", lambda policy: sleeve_upper(policy, "alpha_active") <= 8),
            ],
        ),
        audit_scenario(
            key="healthy_impulse_trend",
            label="健康主升共振",
            position_score=88,
            opportunity_score=88,
            pre_cap_score=88,
            crowding_penalty=2,
            modules=modules_from_pct(index_trend=90, breadth=85, liquidity=82, capital_flow=82, mainline=88, valuation=55, macro=60),
            risk_caps=[],
            thesis="趋势、宽度、资金、主线共振且不拥挤时，风险资产可接近满仓，alpha 打开。",
            expectations=[
                ("liquidity_low", lambda policy: sleeve_upper(policy, "liquidity") <= 10),
                ("alpha_open", lambda policy: sleeve_mid(policy, "alpha_active") >= 35),
                ("defensive_small", lambda policy: sleeve_upper(policy, "defensive_factor") <= 12),
            ],
        ),
        audit_scenario(
            key="bubble_top",
            label="牛末泡沫冲顶",
            position_score=35,
            opportunity_score=68,
            pre_cap_score=65,
            crowding_penalty=22,
            modules=modules_from_pct(index_trend=92, breadth=75, liquidity=90, capital_flow=45, mainline=88, valuation=8, macro=45),
            risk_caps=[
                risk_cap("bubble_top_combo", 35, "high"),
                risk_cap("high_crowding_extreme", 45, "high"),
                risk_cap("high_volatility", 55, "medium"),
            ],
            thesis="机会分仍高但估值、拥挤和波动压仓位，优先压 alpha、抬流动性。",
            expectations=[
                ("alpha_capped", lambda policy: sleeve_upper(policy, "alpha_active") <= 8),
                ("liquidity_high", lambda policy: sleeve_lower(policy, "liquidity") >= 60),
                ("defensive_at_least_alpha", lambda policy: sleeve_mid(policy, "defensive_factor") > sleeve_mid(policy, "alpha_active")),
            ],
        ),
        audit_scenario(
            key="top_rebound",
            label="顶部反抽但风控压制",
            position_score=38,
            opportunity_score=62,
            pre_cap_score=58,
            crowding_penalty=14,
            modules=modules_from_pct(index_trend=78, breadth=38, liquidity=65, capital_flow=42, mainline=48, valuation=22, macro=45),
            risk_caps=[
                risk_cap("high_crowding", 45, "medium"),
                risk_cap("strong_index_weak_breadth", 50, "medium"),
            ],
            thesis="反抽能抬高机会分，但宽度弱和高位风险未解除，alpha 不应快速扩张。",
            expectations=[
                ("alpha_capped", lambda policy: sleeve_upper(policy, "alpha_active") <= 12),
                ("liquidity_buffer", lambda policy: sleeve_lower(policy, "liquidity") >= 40),
                ("beta_above_alpha", lambda policy: sleeve_mid(policy, "beta_core") > sleeve_mid(policy, "alpha_active")),
            ],
        ),
        audit_scenario(
            key="extreme_selloff",
            label="极端杀跌",
            position_score=12,
            opportunity_score=25,
            pre_cap_score=20,
            crowding_penalty=8,
            modules=modules_from_pct(index_trend=12, breadth=10, liquidity=20, capital_flow=8, mainline=8, valuation=70, macro=35),
            risk_caps=[
                risk_cap("capital_outflow_combo", 20, "high"),
                risk_cap("high_volatility", 35, "medium"),
            ],
            thesis="极端下跌时便宜也不能替代趋势确认，保持高流动性和极低 alpha。",
            expectations=[
                ("liquidity_very_high", lambda policy: sleeve_lower(policy, "liquidity") >= 80),
                ("alpha_near_zero", lambda policy: sleeve_upper(policy, "alpha_active") <= 2),
                ("defensive_above_beta", lambda policy: sleeve_mid(policy, "defensive_factor") >= sleeve_mid(policy, "beta_core")),
            ],
        ),
    ]


def run_audit() -> dict[str, Any]:
    scenario_results = scenarios()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "allocation_policy_version": market_scoring.ALLOCATION_POLICY_VERSION,
        "scenario_count": len(scenario_results),
        "passed": all(item["passed"] for item in scenario_results),
        "scenarios": scenario_results,
        "summary": {
            item["key"]: {
                "label": item["label"],
                "passed": item["passed"],
                "state": item["policy"].get("state"),
                "total_risk_asset_range": item["policy"].get("total_risk_asset_range"),
                "sleeve_ranges": item["sleeve_ranges"],
            }
            for item in scenario_results
        },
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# allocation_policy_v2 场景审计",
        "",
        f"- 生成时间: {result['generated_at']}",
        f"- 配置策略版本: `{result['allocation_policy_version']}`",
        f"- 场景数量: {result['scenario_count']}",
        f"- 总体结论: {'通过' if result['passed'] else '未通过'}",
        "",
        "## 审计口径",
        "",
        "- 检查四个一级仓位是否固定为 `beta_core / alpha_active / defensive_factor / liquidity`。",
        "- 检查 `流动性仓 = 100% - 风险资产总仓位`。",
        "- 检查 `β核心仓 + α主动仓 + 防御因子仓` 的中位数是否接近风险资产总仓位中位数。",
        "- 针对熊末、主升、牛末、顶部反抽、极端杀跌分别设置直觉约束。",
        "",
        "## 场景结果",
        "",
        "| 场景 | 状态 | 风险资产 | β核心 | α主动 | 防御因子 | 流动性 | 结论 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in result["scenarios"]:
        ranges = item["sleeve_ranges"]
        lines.append(
            f"| {item['label']} | {item['policy'].get('state')} | {item['policy'].get('total_risk_asset_range')} | "
            f"{ranges['beta_core']} | {ranges['alpha_active']} | {ranges['defensive_factor']} | {ranges['liquidity']} | "
            f"{'通过' if item['passed'] else '未通过'} |"
        )
    lines.extend(["", "## 逐项检查", ""])
    for item in result["scenarios"]:
        lines.extend([f"### {item['label']}", "", item["thesis"], ""])
        for check in item["checks"]:
            lines.append(f"- {'通过' if check['ok'] else '未通过'} `{check['name']}`：{check['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(result: dict[str, Any]) -> dict[str, str]:
    timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / f"allocation_policy_v2_scenario_audit_{timestamp}.json"
    md_path = DATA_DIR / f"allocation_policy_v2_scenario_audit_{timestamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    result = run_audit()
    paths = write_artifacts(result)
    print(json.dumps({"passed": result["passed"], "paths": paths, "summary": result["summary"]}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
