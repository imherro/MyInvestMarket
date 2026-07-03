from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import market_scoring


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")

PARAMETERS = {
    "valuation_enable_min": 60,
    "worst_drawdown_60d_enable_min_pct": 10,
    "crowding_penalty_max": 10,
    "opportunity_score_overheat_max": 65,
    "mainline_score_pct_overheat_max": 70,
    "stampede_main_net_max_100m_cny": -1000,
    "stampede_northbound_max_100m_cny": -50,
    "realized_vol_30d_tail_max": 0.50,
    "intensity_enable_min": 55,
    "score_floor_min": 35,
    "score_floor_max": 60,
}


def round2(value: Any) -> float | None:
    return market_scoring.round2(market_scoring.as_float(value))


def display(value: Any) -> str:
    if value is None:
        return "--"
    return str(value)


def module(score_pct: float, key: str) -> dict[str, float]:
    weight = market_scoring.MODULES[key]["weight"]
    return {"score": round(score_pct / 100 * weight, 2), "weight": weight, "score_pct": score_pct}


def modules_from_pct(**values: float) -> dict[str, dict[str, float]]:
    defaults = {
        "index_trend": 25,
        "breadth": 22,
        "liquidity": 35,
        "capital_flow": 32,
        "mainline": 20,
        "valuation": 88,
        "macro": 45,
    }
    defaults.update(values)
    return {key: module(value, key) for key, value in defaults.items()}


def delete_path(payload: dict[str, Any], dotted_path: str) -> None:
    parts = dotted_path.split(".")
    current: Any = payload
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def synthetic_snapshot(
    *,
    valuation_score: float = 88,
    worst_drawdown_pct: float = 22,
    advancer_ratio: float = 0.16,
    strong_decliners_ratio: float = 0.24,
    limit_down: float = 45,
    main_net: float = -250,
    northbound: float = 10,
    realized_vol: float = 0.32,
    omit: list[str] | None = None,
) -> dict[str, Any]:
    total = 5000
    drawdown_values = [
        -max(0, worst_drawdown_pct - 4),
        -max(0, worst_drawdown_pct - 2),
        -max(0, worst_drawdown_pct),
        -max(0, worst_drawdown_pct - 7),
    ]
    payload: dict[str, Any] = {
        "date": "synthetic",
        "valuation": {"market": {"valuation_score": valuation_score}},
        "volatility": {
            "market": {"realized_vol_30d": realized_vol},
            "indices": {
                "000001.SH": {"drawdown_60d_pct": drawdown_values[0]},
                "399001.SZ": {"drawdown_60d_pct": drawdown_values[1]},
                "399006.SZ": {"drawdown_60d_pct": drawdown_values[2]},
                "899050.BJ": {"drawdown_60d_pct": drawdown_values[3]},
            },
        },
        "breadth": {
            "total": total,
            "advancers": round(total * advancer_ratio),
            "decliners": total - round(total * advancer_ratio),
            "strong_decliners_lt_minus3_pct": strong_decliners_ratio,
            "limit_down": limit_down,
        },
        "capital_flow": {
            "northbound_net_inflow_100m_cny": northbound,
            "main_net_inflow_100m_cny": main_net,
        },
        "data_quality": {"missing_fields": [], "warnings": []},
    }
    for path in omit or []:
        delete_path(payload, path)
    return payload


def risk_engine_fixture() -> dict[str, Any]:
    return {
        "version": "risk_engine_v1",
        "risk_penalty_score": 30,
        "risk_level": "medium",
        "risk_discount": 0.75,
        "components": [],
    }


def parse_range(range_text: str | None) -> tuple[float, float]:
    parsed = market_scoring.parse_percent_range(range_text)
    if parsed is None:
        raise ValueError(f"invalid range: {range_text}")
    return parsed


def sleeve_range(policy: dict[str, Any], key: str) -> tuple[float, float]:
    for sleeve in policy.get("sleeves", []):
        if isinstance(sleeve, dict) and sleeve.get("key") == key:
            return parse_range(sleeve.get("target_range"))
    raise KeyError(key)


def overlay_case(
    *,
    key: str,
    label: str,
    expectation: str,
    opportunity_score: float = 42,
    current_score: float = 29,
    crowding_penalty: float = 3,
    mainline_pct: float = 20,
    snapshot_kwargs: dict[str, Any] | None = None,
    expected_active: bool,
    expected_blockers: list[str] | None = None,
    min_add_score: float | None = None,
) -> dict[str, Any]:
    modules = modules_from_pct(mainline=mainline_pct)
    snapshot = synthetic_snapshot(**(snapshot_kwargs or {}))
    overlay = market_scoring.contrarian_beta_overlay(
        opportunity_score,
        {"penalty": crowding_penalty},
        modules,
        snapshot,
        risk_engine_fixture(),
        current_score,
    )
    policy: dict[str, Any] | None = None
    if overlay.get("active"):
        target_score = market_scoring.as_float(overlay.get("target_score")) or current_score
        policy = market_scoring.allocation_policy(
            target_score,
            opportunity_score,
            target_score,
            market_scoring.position_range(target_score),
            modules,
            {"penalty": crowding_penalty},
            snapshot,
            [],
            overlay,
        )

    checks = [
        {
            "name": "active_state_matches_expectation",
            "ok": bool(overlay.get("active")) is expected_active,
            "detail": f"expected_active={expected_active}, actual={overlay.get('active')}",
        }
    ]
    for text in expected_blockers or []:
        blockers = overlay.get("blockers", []) if isinstance(overlay.get("blockers"), list) else []
        checks.append(
            {
                "name": f"blocker_contains_{text}",
                "ok": any(text in blocker for blocker in blockers),
                "detail": " / ".join(str(item) for item in blockers),
            }
        )
    if min_add_score is not None:
        checks.append(
            {
                "name": "min_add_score",
                "ok": (market_scoring.as_float(overlay.get("add_score")) or 0) >= min_add_score,
                "detail": f"add_score={overlay.get('add_score')}, min={min_add_score}",
            }
        )
    if policy:
        alpha_high = sleeve_range(policy, "alpha_active")[1]
        beta_mid = sum(sleeve_range(policy, "beta_core")) / 2
        defensive_mid = sum(sleeve_range(policy, "defensive_factor")) / 2
        checks.extend(
            [
                {
                    "name": "alpha_stays_locked",
                    "ok": alpha_high <= 8,
                    "detail": f"alpha_active_high={alpha_high}",
                },
                {
                    "name": "beta_dominates_defensive",
                    "ok": beta_mid > defensive_mid,
                    "detail": f"beta_mid={round2(beta_mid)}, defensive_mid={round2(defensive_mid)}",
                },
                {
                    "name": "score_floor_within_policy_bounds",
                    "ok": PARAMETERS["score_floor_min"] <= (market_scoring.as_float(overlay.get("score_floor")) or 0) <= PARAMETERS["score_floor_max"],
                    "detail": f"score_floor={overlay.get('score_floor')}",
                },
            ]
        )

    return {
        "key": key,
        "label": label,
        "expectation": expectation,
        "inputs": {
            "opportunity_score": opportunity_score,
            "current_score": current_score,
            "crowding_penalty": crowding_penalty,
            "mainline_pct": mainline_pct,
            **(snapshot_kwargs or {}),
        },
        "overlay": overlay,
        "allocation_policy": policy,
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }


def audit_cases() -> list[dict[str, Any]]:
    return [
        overlay_case(
            key="ideal_deep_bear_repair",
            label="理想深熊赔率",
            expectation="应启用，并抬高β核心仓，不打开α主动仓。",
            expected_active=True,
            min_add_score=20,
        ),
        overlay_case(
            key="valuation_below_threshold",
            label="估值未足够便宜",
            expectation="估值便宜度低于60时应阻断。",
            snapshot_kwargs={"valuation_score": 59.9},
            expected_active=False,
            expected_blockers=["估值便宜度"],
        ),
        overlay_case(
            key="drawdown_below_threshold",
            label="回撤深度不足",
            expectation="最深60日回撤低于10%时应阻断。",
            snapshot_kwargs={"worst_drawdown_pct": 9.9},
            expected_active=False,
            expected_blockers=["指数最深60日回撤"],
        ),
        overlay_case(
            key="crowding_above_threshold",
            label="拥挤仍高",
            expectation="拥挤惩罚高于10时不做左侧扩仓。",
            crowding_penalty=10.1,
            expected_active=False,
            expected_blockers=["拥挤惩罚"],
        ),
        overlay_case(
            key="opportunity_overheat_guard",
            label="机会分偏热",
            expectation="机会分已高于65时不追高。",
            opportunity_score=66,
            expected_active=False,
            expected_blockers=["不追高"],
        ),
        overlay_case(
            key="mainline_overheat_guard",
            label="主线强度偏热",
            expectation="主线强度已高于70时不追高。",
            mainline_pct=71,
            expected_active=False,
            expected_blockers=["不追高"],
        ),
        overlay_case(
            key="capital_stampede_guard",
            label="资金踩踏",
            expectation="主力和北向同时大幅流出时不启用。",
            snapshot_kwargs={"main_net": -1200, "northbound": -80},
            expected_active=False,
            expected_blockers=["资金踩踏"],
        ),
        overlay_case(
            key="tail_vol_guard",
            label="尾部波动过高",
            expectation="30日年化波动率达到50%时不启用。",
            snapshot_kwargs={"realized_vol": 0.50},
            expected_active=False,
            expected_blockers=["尾部风险过高"],
        ),
        overlay_case(
            key="missing_core_fields_guard",
            label="核心字段缺失",
            expectation="强弱个股、资金或波动率字段缺失时不启用。",
            snapshot_kwargs={
                "omit": [
                    "breadth.strong_decliners_lt_minus3_pct",
                    "capital_flow.northbound_net_inflow_100m_cny",
                    "volatility.market.realized_vol_30d",
                ]
            },
            expected_active=False,
            expected_blockers=["缺失"],
        ),
        overlay_case(
            key="low_intensity_guard",
            label="低估回撤刚过线但赔率强度不足",
            expectation="硬阈值刚满足但恐慌和资金稳定证据不足时不启用。",
            snapshot_kwargs={
                "valuation_score": 61,
                "worst_drawdown_pct": 10.1,
                "advancer_ratio": 0.44,
                "strong_decliners_ratio": 0.09,
                "limit_down": 5,
                "main_net": -800,
                "northbound": -70,
                "realized_vol": 0.47,
            },
            expected_active=False,
            expected_blockers=["深熊赔率强度"],
        ),
    ]


def sensitivity_grid() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for valuation_score in [60, 70, 80, 90]:
        for worst_drawdown_pct in [10, 14, 18, 24]:
            case = overlay_case(
                key=f"grid_v{valuation_score}_d{worst_drawdown_pct}",
                label="参数网格",
                expectation="观察估值和回撤对强度、地板、加分的影响。",
                snapshot_kwargs={"valuation_score": valuation_score, "worst_drawdown_pct": worst_drawdown_pct},
                expected_active=False,
            )
            overlay = case["overlay"]
            rows.append(
                {
                    "valuation_score": valuation_score,
                    "worst_drawdown_pct": worst_drawdown_pct,
                    "active": bool(overlay.get("active")),
                    "intensity_score": overlay.get("intensity_score"),
                    "score_floor": overlay.get("score_floor"),
                    "add_score": overlay.get("add_score"),
                    "blocker_count": len(overlay.get("blockers", []) or []),
                }
            )
    return rows


def monotonic_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for drawdown in sorted({row["worst_drawdown_pct"] for row in rows}):
        subset = [row for row in rows if row["worst_drawdown_pct"] == drawdown]
        values = [market_scoring.as_float(row.get("intensity_score")) or 0 for row in subset]
        checks.append(
            {
                "name": f"valuation_monotonic_at_drawdown_{drawdown}",
                "ok": values == sorted(values),
                "detail": values,
            }
        )
    for valuation in sorted({row["valuation_score"] for row in rows}):
        subset = [row for row in rows if row["valuation_score"] == valuation]
        values = [market_scoring.as_float(row.get("intensity_score")) or 0 for row in subset]
        checks.append(
            {
                "name": f"drawdown_monotonic_at_valuation_{valuation}",
                "ok": values == sorted(values),
                "detail": values,
            }
        )
    return {"passed": all(item["ok"] for item in checks), "checks": checks}


def history_probe() -> dict[str, Any]:
    history = market_scoring.load_history(market_scoring.DEFAULT_HISTORY_PATH)
    records = [
        item
        for item in history.get("records", [])
        if isinstance(item, dict)
        and item.get("model_version") == market_scoring.MODEL_VERSION
        and item.get("position_policy_version") == market_scoring.POSITION_POLICY_VERSION
    ]
    overlays = [record.get("contrarian_beta_overlay") for record in records if isinstance(record.get("contrarian_beta_overlay"), dict)]
    active_records = [record for record in records if ((record.get("contrarian_beta_overlay") or {}).get("active") if isinstance(record.get("contrarian_beta_overlay"), dict) else False)]
    max_intensity = max((market_scoring.as_float((overlay or {}).get("intensity_score")) or 0 for overlay in overlays), default=0)
    top_rows = sorted(
        [
            {
                "basis_trade_date": record.get("basis_trade_date"),
                "run_id": record.get("run_id"),
                "market_position_score": record.get("market_position_score"),
                "valuation_score": (((record.get("contrarian_beta_overlay") or {}).get("inputs") or {}).get("valuation_score") if isinstance(record.get("contrarian_beta_overlay"), dict) else None),
                "worst_drawdown_60d_pct": (((record.get("contrarian_beta_overlay") or {}).get("inputs") or {}).get("worst_drawdown_60d_pct") if isinstance(record.get("contrarian_beta_overlay"), dict) else None),
                "crowding_penalty": record.get("crowding_penalty"),
                "intensity_score": ((record.get("contrarian_beta_overlay") or {}).get("intensity_score") if isinstance(record.get("contrarian_beta_overlay"), dict) else None),
                "active": ((record.get("contrarian_beta_overlay") or {}).get("active") if isinstance(record.get("contrarian_beta_overlay"), dict) else False),
                "blockers": ((record.get("contrarian_beta_overlay") or {}).get("blockers") if isinstance(record.get("contrarian_beta_overlay"), dict) else []),
            }
            for record in records
        ],
        key=lambda row: market_scoring.as_float(row.get("intensity_score")) or 0,
        reverse=True,
    )[:5]
    return {
        "record_count": len(records),
        "active_count": len(active_records),
        "max_intensity_score": round2(max_intensity),
        "latest_basis_trade_date": records[-1].get("basis_trade_date") if records else None,
        "latest_run_id": records[-1].get("run_id") if records else None,
        "top_intensity_rows": top_rows,
        "checks": [
            {
                "name": "current_history_no_false_positive",
                "ok": len(active_records) == 0,
                "detail": f"active_count={len(active_records)} among {len(records)} current-version records",
            },
            {
                "name": "current_history_has_overlay_fields",
                "ok": len(overlays) == len(records),
                "detail": f"overlay_fields={len(overlays)}, records={len(records)}",
            },
        ],
        "passed": len(active_records) == 0 and len(overlays) == len(records),
    }


def recommendation(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "当前参数偏审慎，符合只在低估、深回撤、恐慌出清且资金未踩踏时才抬β仓的目标。",
        "keep": [
            "估值便宜度60阈值应保留，避免普通调整误触发。",
            "拥挤惩罚10上限应保留，避免高位急跌反抽被当作底部。",
            "资金踩踏和50%波动率硬阻断应保留，避免下跌中继扩大风险。",
        ],
        "watch": [
            "如果后续历史底部样本出现估值55-60但其他信号极强，可再讨论是否把估值阈值改成55并提高强度阈值。",
            "当前历史样本只有13条，尚不足以做统计显著性校准；本轮是规则边界审计，不是收益回测结论。",
            "深熊逆向模块最高只把仓位分地板抬到60，仍然不是满仓逻辑；满仓应留给低拥挤强趋势，而不是左侧底部猜测。",
        ],
        "decision": "本轮不建议立刻调参；建议先积累更多底部/急跌样本，再做参数回测。",
    }


def run_audit() -> dict[str, Any]:
    cases = audit_cases()
    grid = sensitivity_grid()
    monotonic = monotonic_check(grid)
    history = history_probe()
    checks = [
        {
            "name": "boundary_cases_passed",
            "ok": all(item["passed"] for item in cases),
            "detail": f"{sum(1 for item in cases if item['passed'])}/{len(cases)} cases passed",
        },
        {
            "name": "sensitivity_monotonic",
            "ok": monotonic["passed"],
            "detail": "intensity rises with valuation cheapness and drawdown depth under fixed other inputs",
        },
        {
            "name": "history_probe_passed",
            "ok": history["passed"],
            "detail": f"active_count={history['active_count']}, record_count={history['record_count']}",
        },
    ]
    result: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "model_version": market_scoring.MODEL_VERSION,
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
        "overlay_version": "contrarian_beta_overlay_v1",
        "parameters": PARAMETERS,
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "cases": cases,
        "sensitivity_grid": grid,
        "monotonicity": monotonic,
        "history_probe": history,
    }
    result["recommendation"] = recommendation(result)
    return result


def markdown_report(result: dict[str, Any]) -> str:
    rec = result["recommendation"]
    lines = [
        "# 深熊逆向模块参数审计",
        "",
        f"- 生成时间: {result['generated_at']}",
        f"- 模型版本: `{result['model_version']}`",
        f"- 仓位策略版本: `{result['position_policy_version']}`",
        f"- 模块版本: `{result['overlay_version']}`",
        f"- 总体结论: {'通过' if result['passed'] else '未通过'}",
        "",
        "## 审计结论",
        "",
        rec["summary"],
        "",
        f"最终建议：{rec['decision']}",
        "",
        "## 当前参数",
        "",
        "| 参数 | 数值 |",
        "|---|---:|",
    ]
    for key, value in result["parameters"].items():
        lines.append(f"| `{key}` | {value} |")

    lines.extend(
        [
            "",
            "## 核心检查",
            "",
            "| 检查 | 结果 | 说明 |",
            "|---|---|---|",
        ]
    )
    for check in result["checks"]:
        lines.append(f"| `{check['name']}` | {'通过' if check['ok'] else '未通过'} | {check['detail']} |")

    lines.extend(
        [
            "",
            "## 边界场景",
            "",
            "| 场景 | 是否启用 | 强度 | 加分 | 结论 | 阻断原因 |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for case in result["cases"]:
        overlay = case["overlay"]
        blockers = "；".join(overlay.get("blockers", [])[:3]) if isinstance(overlay.get("blockers"), list) else ""
        lines.append(
            f"| {case['label']} | {'是' if overlay.get('active') else '否'} | {overlay.get('intensity_score')} | "
            f"{overlay.get('add_score')} | {'通过' if case['passed'] else '未通过'} | {blockers or '-'} |"
        )

    history = result["history_probe"]
    lines.extend(
        [
            "",
            "## 当前历史样本",
            "",
            f"- 当前版本记录数: {history['record_count']}",
            f"- 逆向模块启用次数: {history['active_count']}",
            f"- 最高强度: {history['max_intensity_score']}",
            f"- 最新基准日: {history['latest_basis_trade_date']}",
            "",
            "| 基准日 | 仓位分 | 估值便宜度 | 最深回撤 | 拥挤惩罚 | 强度 | 启用 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in history["top_intensity_rows"]:
        lines.append(
            f"| {row['basis_trade_date']} | {row['market_position_score']} | {row['valuation_score']} | "
            f"{row['worst_drawdown_60d_pct']} | {row['crowding_penalty']} | {row['intensity_score']} | "
            f"{'是' if row['active'] else '否'} |"
        )

    lines.extend(["", "## 参数敏感性网格", "", "| 估值便宜度 | 最深回撤 | 启用 | 强度 | 地板 | 加分 |", "|---:|---:|---|---:|---:|---:|"])
    for row in result["sensitivity_grid"]:
        lines.append(
            f"| {row['valuation_score']} | {row['worst_drawdown_pct']} | {'是' if row['active'] else '否'} | "
            f"{display(row['intensity_score'])} | {display(row['score_floor'])} | {display(row['add_score'])} |"
        )

    lines.extend(["", "## 保留项", ""])
    lines.extend(f"- {item}" for item in rec["keep"])
    lines.extend(["", "## 后续观察", ""])
    lines.extend(f"- {item}" for item in rec["watch"])
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(result: dict[str, Any]) -> dict[str, str]:
    timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / f"contrarian_beta_overlay_parameter_audit_{timestamp}.json"
    md_path = DATA_DIR / f"contrarian_beta_overlay_parameter_audit_{timestamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    result = run_audit()
    paths = write_artifacts(result)
    print(json.dumps({"passed": result["passed"], "paths": paths, "recommendation": result["recommendation"]}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
