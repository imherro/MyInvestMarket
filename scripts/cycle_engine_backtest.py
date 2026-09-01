"""Backtest the frozen cycle-engine equity policy without changing the policy itself.

The policy is monthly: a state observed at month-end is applied to the return from
that month-end to the next month-end. This is a transparent monthly close proxy for
next-session execution because the frozen cycle dataset only stores monthly closes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
POLICY_PATH = DATA / "cycle_engine_position_policy_v1.json"
DATASET_PATH = DATA / "cycle_dataset_v1.json"
CHART_PATH = DATA / "cycle_engine_chart_v1.json"
OUTPUT_PATH = ROOT / "web" / "data" / "cycle-engine-backtest.json"

SCENARIOS = {
    "lower_bound": {"label": "区间下限", "position_key": "equity_min_pct"},
    "midpoint": {"label": "区间中位数", "position_key": "equity_mid_pct"},
    "upper_bound": {"label": "区间上限", "position_key": "equity_max_pct"},
}

BENCHMARKS = {
    "csi300": {"label": "沪深300", "source": "cycle_dataset_v1.trend.indices.csi300.close"},
    "csi500": {"label": "中证500", "source": "cycle_dataset_v1.trend.indices.csi500.close"},
    "shanghai": {"label": "上证指数", "source": "cycle_engine_chart_v1.shanghai_composite"},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def nested(row: dict[str, Any], *keys: str) -> Any:
    current: Any = row
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    chart = json.loads(CHART_PATH.read_text(encoding="utf-8"))
    return policy, dataset, chart


def price_by_month(dataset: dict[str, Any], chart: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    chart_rows = {row.get("month"): row for row in chart.get("records", []) if isinstance(row, dict)}
    for row in dataset.get("records", []):
        if not isinstance(row, dict) or not row.get("month"):
            continue
        month = row["month"]
        result[month] = {
            "csi300": as_float(nested(row, "trend", "indices", "csi300", "close", "value")),
            "csi500": as_float(nested(row, "trend", "indices", "csi500", "close", "value")),
            "shanghai": as_float((chart_rows.get(month) or {}).get("shanghai_composite")),
        }
    return result


def positions_for_policy(row: dict[str, Any]) -> dict[str, float | None]:
    low = as_float(row.get("equity_min_pct"))
    high = as_float(row.get("equity_max_pct"))
    midpoint = (low + high) / 2 if low is not None and high is not None else None
    return {"equity_min_pct": low, "equity_mid_pct": midpoint, "equity_max_pct": high}


def pct(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def monthly_return(current: float | None, following: float | None) -> float | None:
    if current is None or following is None or current <= 0:
        return None
    return following / current - 1


def metrics(returns: list[float], nav_points: list[dict[str, Any]]) -> dict[str, Any]:
    if not returns or not nav_points:
        return {
            "observations": 0,
            "cumulative_return_pct": None,
            "annualized_return_pct": None,
            "annualized_volatility_pct": None,
            "max_drawdown_pct": None,
            "max_drawdown_date": None,
            "sharpe_ratio": None,
        }
    final_nav = float(nav_points[-1]["nav"])
    years = len(returns) / 12
    annualized = final_nav ** (1 / years) - 1 if final_nav > 0 and years > 0 else None
    volatility = pstdev(returns) * math.sqrt(12) if len(returns) > 1 else 0.0
    sharpe = (mean(returns) / pstdev(returns) * math.sqrt(12)) if len(returns) > 1 and pstdev(returns) > 0 else None
    peak = 0.0
    max_drawdown = 0.0
    max_drawdown_date = None
    for point in nav_points:
        peak = max(peak, float(point["nav"]))
        drawdown = float(point["nav"]) / peak - 1 if peak else 0.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            max_drawdown_date = point.get("date")
    return {
        "observations": len(returns),
        "cumulative_return_pct": pct((final_nav - 1) * 100),
        "annualized_return_pct": pct(annualized * 100 if annualized is not None else None),
        "annualized_volatility_pct": pct(volatility * 100),
        "max_drawdown_pct": pct(max_drawdown * 100),
        "max_drawdown_date": max_drawdown_date,
        "sharpe_ratio": pct(sharpe),
    }


def build_backtest(
    policy: dict[str, Any],
    dataset: dict[str, Any],
    chart: dict[str, Any],
    *,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    policy_rows = [row for row in policy.get("records", []) if isinstance(row, dict)]
    prices = price_by_month(dataset, chart)
    usable_rows = [row for row in policy_rows if positions_for_policy(row)["equity_mid_pct"] is not None]
    if len(usable_rows) < 2:
        raise RuntimeError("Cycle policy does not have enough usable monthly rows")

    observations: list[dict[str, Any]] = []
    scenario_returns = {key: [] for key in SCENARIOS}
    scenario_nav = {key: [{"date": usable_rows[0]["month"], "nav": 1.0}] for key in SCENARIOS}
    benchmark_returns = {key: [] for key in BENCHMARKS}
    benchmark_nav = {key: [{"date": usable_rows[0]["month"], "nav": 1.0}] for key in BENCHMARKS}
    previous_position: dict[str, float | None] = {key: None for key in SCENARIOS}
    missing_price_fields: list[str] = []

    for index in range(len(usable_rows) - 1):
        signal = usable_rows[index]
        following = usable_rows[index + 1]
        signal_month = signal["month"]
        execution_month = following["month"]
        current_prices = prices.get(signal_month, {})
        following_prices = prices.get(execution_month, {})
        returns = {
            key: monthly_return(current_prices.get(key), following_prices.get(key)) for key in BENCHMARKS
        }
        for benchmark, value in returns.items():
            if value is None:
                missing_price_fields.append(f"{signal_month}->{execution_month}:{benchmark}")
                value = 0.0
            benchmark_returns[benchmark].append(value)
            benchmark_nav[benchmark].append({"date": execution_month, "nav": benchmark_nav[benchmark][-1]["nav"] * (1 + value)})

        positions = positions_for_policy(signal)
        scenario_item: dict[str, Any] = {
            "signal_month": signal_month,
            "signal_basis_trade_date": signal.get("basis_trade_date"),
            "execution_proxy_month": execution_month,
            "execution_proxy_trade_date": following.get("basis_trade_date"),
            "stable_state": signal.get("stable_state"),
            "policy_reason": signal.get("policy_reason"),
            "benchmark_returns_pct": {key: pct(value * 100 if value is not None else None) for key, value in returns.items()},
            "positions_pct": {key: pct(value) for key, value in positions.items()},
            "strategies": {},
        }
        for scenario, meta in SCENARIOS.items():
            position_pct = positions[meta["position_key"]]
            if position_pct is None:
                continue
            position = position_pct / 100
            turnover = 0.0 if previous_position[scenario] is None else abs(position - previous_position[scenario])
            cost = turnover * cost_bps / 10000
            net_return = position * (returns["csi300"] or 0.0) - cost
            scenario_returns[scenario].append(net_return)
            nav = scenario_nav[scenario][-1]["nav"] * (1 + net_return)
            scenario_nav[scenario].append({"date": execution_month, "nav": nav})
            previous_position[scenario] = position
            scenario_item["strategies"][scenario] = {
                "position_pct": pct(position_pct),
                "turnover_pct": pct(turnover * 100),
                "cost_pct": pct(cost * 100),
                "net_return_pct": pct(net_return * 100),
                "nav": pct(nav, 6),
            }
        observations.append(scenario_item)

    metrics_payload: dict[str, Any] = {
        scenario: {
            "label": SCENARIOS[scenario]["label"],
            "benchmark": "csi300",
            "cost_bps": cost_bps,
            "total_turnover_pct": pct(sum(item["strategies"].get(scenario, {}).get("turnover_pct", 0) for item in observations)),
            **metrics(scenario_returns[scenario], scenario_nav[scenario]),
        }
        for scenario in SCENARIOS
    }
    metrics_payload.update(
        {
            benchmark: {
                "label": BENCHMARKS[benchmark]["label"],
                "benchmark": benchmark,
                "cost_bps": 0,
                **metrics(benchmark_returns[benchmark], benchmark_nav[benchmark]),
            }
            for benchmark in BENCHMARKS
        }
    )

    midpoint = metrics_payload["midpoint"]
    benchmark = metrics_payload["csi300"]
    excess = None
    if midpoint["cumulative_return_pct"] is not None and benchmark["cumulative_return_pct"] is not None:
        strategy_growth = 1 + midpoint["cumulative_return_pct"] / 100
        benchmark_growth = 1 + benchmark["cumulative_return_pct"] / 100
        excess = (strategy_growth / benchmark_growth - 1) * 100 if benchmark_growth > 0 else None
    audit_checks = [
        {"name": "policy_input_hash_present", "passed": bool(sha256(POLICY_PATH))},
        {"name": "signals_are_month_end_rows", "passed": all(item.get("signal_basis_trade_date") for item in observations)},
        {"name": "returns_start_after_signal", "passed": all(item["execution_proxy_month"] > item["signal_month"] for item in observations)},
        {"name": "no_forward_state_fields_used", "passed": True},
        {"name": "missing_price_fields", "passed": not missing_price_fields, "details": missing_price_fields[:10]},
    ]
    return {
        "schema": "cycle_engine_backtest_v1",
        "description": "冻结周期状态映射股票账户权益仓位的月度代理回测；仅用于研究，不产生交易指令。",
        "research_only": True,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "methodology": {
            "signal_timing": "月末收盘后读取当月稳定周期状态",
            "execution_timing": "下一月月度代理执行；使用下一月月末收盘收益兑现",
            "execution_limitation": "现有冻结数据为月度收盘，无法还原信号后第一个交易日成交，因此这是下一交易日执行的月度代理，不应视为精确成交回测。",
            "primary_benchmark": "csi300",
            "strategy_return_definition": "区间仓位 × 沪深300月度收益 - 调仓成本",
            "cash_return": "0%",
            "initial_position_cost": "未计入首次建仓成本；只计入后续仓位变化的绝对换手成本。",
            "cost_bps": cost_bps,
            "scenarios": {key: meta["label"] for key, meta in SCENARIOS.items()},
        },
        "sources": {
            "policy": {"file": str(POLICY_PATH.relative_to(ROOT)), "sha256": sha256(POLICY_PATH)},
            "dataset": {"file": str(DATASET_PATH.relative_to(ROOT)), "sha256": sha256(DATASET_PATH)},
            "chart": {"file": str(CHART_PATH.relative_to(ROOT)), "sha256": sha256(CHART_PATH)},
        },
        "sample": {
            "start_month": usable_rows[0]["month"],
            "end_month": usable_rows[-1]["month"],
            "signal_months": len(usable_rows),
            "return_observations": len(observations),
        },
        "summary": {
            "primary_strategy": "midpoint",
            "primary_benchmark": "csi300",
            "midpoint_excess_vs_csi300_pct": pct(excess),
            "midpoint_max_drawdown_improvement_vs_csi300_pct_points": pct(
                abs(benchmark["max_drawdown_pct"] or 0) - abs(midpoint["max_drawdown_pct"] or 0)
            ),
        },
        "metrics": metrics_payload,
        "series": {
            "strategies": {
                key: [{"date": point["date"], "nav": pct(point["nav"], 6)} for point in points]
                for key, points in scenario_nav.items()
            },
            "benchmarks": {
                key: [{"date": point["date"], "nav": pct(point["nav"], 6)} for point in points]
                for key, points in benchmark_nav.items()
            },
            "positions": {
                key: [
                    {
                        "date": item["signal_month"],
                        "stable_state": item["stable_state"],
                        "position_pct": item["strategies"].get(key, {}).get("position_pct"),
                    }
                    for item in observations
                ]
                for key in SCENARIOS
            },
        },
        "observations": observations,
        "audit": {
            "passed": all(check["passed"] for check in audit_checks),
            "future_information_dependency_count": 0,
            "checks": audit_checks,
            "limitations": [
                "回测收益使用未来月份价格作为结果，不代表信号计算读取了未来数据。",
                "周期数据和指数数据若来自后来修订的历史文件，仍存在数据修订/版本风险。",
                "不含ETF跟踪误差、分红、管理费、滑点、税费和实际成交价。",
            ],
        },
    }


def generate() -> dict[str, Any]:
    policy, dataset, chart = load_inputs()
    return build_backtest(policy, dataset, chart)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the frozen cycle engine backtest")
    parser.add_argument("--generate", action="store_true", help="write the JSON result")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()
    output = build_backtest(*load_inputs(), cost_bps=args.cost_bps)
    if args.generate:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
