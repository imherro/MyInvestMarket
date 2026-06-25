from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import metrics


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_HISTORY_PATH = DATA_DIR / "market_score_history.json"
DEFAULT_POSITION_FIELD = "market_position_score"
V2_PROXY_POSITION_FIELD = "pre_cap_market_position_score"
MIN_BACKTEST_RECORDS = 3


def as_float(value: Any) -> float | None:
    return metrics.as_float(value)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def position_score_to_weight(score: Any) -> float:
    value = as_float(score)
    if value is None:
        return 0.0
    return clamp(value / 100.0, 0.0, 1.0)


def load_history_records(history_path: Path = DEFAULT_HISTORY_PATH, *, include_legacy: bool = False) -> list[dict[str, Any]]:
    payload = json.loads(history_path.read_text(encoding="utf-8-sig"))
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    selected = [record for record in records if isinstance(record, dict)]
    if not include_legacy:
        selected = [record for record in selected if record.get("legacy_schema") is not True]
    return selected


def latest_record_per_trade_date(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for record in sorted(records, key=lambda row: str(row.get("scored_at", ""))):
        key = str(record.get("basis_trade_date") or "")
        if key:
            selected[key] = record
    return [selected[key] for key in sorted(selected.keys())]


def latest_prepared_per_trade_date(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("date") or "")
        if key:
            selected[key] = row
    return [selected[key] for key in sorted(selected.keys())]


def prepare_records(records: list[dict[str, Any]], *, position_field: str = DEFAULT_POSITION_FIELD) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        trade_date = parse_date(record.get("basis_trade_date"))
        close = as_float(record.get("shanghai_composite"))
        if trade_date is None or close is None or close <= 0:
            continue
        score = _position_score(record, position_field)
        baseline_score = (
            as_float(record.get("pre_cap_market_position_score"))
            or as_float(record.get("base_market_position_score"))
            or score
            or 0.0
        )
        prepared.append(
            {
                "index": index,
                "date": trade_date.isoformat(),
                "date_value": trade_date,
                "close": close,
                "position_score": score or 0.0,
                "baseline_position_score": baseline_score,
                "record": record,
            }
        )
    prepared.sort(key=lambda row: row["date_value"])
    return prepared


def run_backtest(
    records: list[dict[str, Any]],
    *,
    position_field: str = DEFAULT_POSITION_FIELD,
    label: str = "v3",
    signal_delay_bars: int = 1,
    transaction_cost: float = 0.0,
    periods_per_year: int = metrics.TRADING_DAYS_PER_YEAR,
) -> dict[str, Any]:
    if signal_delay_bars < 1:
        raise ValueError("signal_delay_bars must be at least 1 to avoid lookahead bias")

    prepared = latest_prepared_per_trade_date(prepare_records(records, position_field=position_field))
    if len(prepared) < 2:
        return {
            "available": False,
            "label": label,
            "reason": "at least two dated records with Shanghai Composite close are required",
            "record_count": len(prepared),
            "signal_delay_bars": signal_delay_bars,
            "lookahead_safe": True,
            "nav_curve": [],
            "returns": [],
            "position_series": [],
            "metrics": {},
        }

    nav = 1.0
    nav_curve = [{"date": prepared[0]["date"], "nav": nav, "strategy_return": 0.0, "benchmark_return": 0.0}]
    returns: list[dict[str, Any]] = []
    position_series: list[dict[str, Any]] = []
    previous_position = 0.0
    total_turnover = 0.0

    for index in range(1, len(prepared)):
        current = prepared[index]
        previous = prepared[index - 1]
        signal_index = index - signal_delay_bars
        if signal_index < 0:
            signal = None
            applied_position = 0.0
            position_score = 0.0
            baseline_position = 0.0
            source_date = None
            source_run_id = None
            signal_record: dict[str, Any] = {}
        else:
            signal = prepared[signal_index]
            signal_record = signal["record"]
            applied_position = position_score_to_weight(signal["position_score"])
            position_score = signal["position_score"]
            baseline_position = position_score_to_weight(signal["baseline_position_score"])
            source_date = signal["date"]
            source_run_id = signal_record.get("run_id")

        benchmark_return = current["close"] / previous["close"] - 1
        position_change = abs(applied_position - previous_position)
        cost = transaction_cost * position_change
        strategy_return = benchmark_return * applied_position - cost
        nav *= 1 + strategy_return
        total_turnover += position_change
        previous_position = applied_position

        row = {
            "date": current["date"],
            "from_date": previous["date"],
            "source_signal_date": source_date,
            "source_run_id": source_run_id,
            "signal_lag_bars": index - signal_index if signal_index >= 0 else None,
            "benchmark_return": benchmark_return,
            "strategy_return": strategy_return,
            "applied_position": applied_position,
            "baseline_position": baseline_position,
            "position_score": position_score,
            "market_regime": signal_record.get("market_regime_code") or signal_record.get("market_regime"),
            "trend_state": signal_record.get("trend_state"),
            "risk_penalty_score": signal_record.get("risk_penalty_score"),
            "risk_cap_count": len(signal_record.get("risk_caps", []) or []),
        }
        returns.append(row)
        position_series.append(
            {
                "date": current["date"],
                "source_signal_date": source_date,
                "applied_position": applied_position,
                "position_score": position_score,
            }
        )
        nav_curve.append(
            {
                "date": current["date"],
                "nav": nav,
                "strategy_return": strategy_return,
                "benchmark_return": benchmark_return,
            }
        )

    summary = metrics.performance_summary(
        nav_curve,
        [row["strategy_return"] for row in returns],
        position_series,
        periods_per_year=periods_per_year,
    )
    summary["turnover"] = total_turnover
    result = {
        "available": True,
        "label": label,
        "position_field": position_field,
        "record_count": len(prepared),
        "return_count": len(returns),
        "signal_delay_bars": signal_delay_bars,
        "transaction_cost": transaction_cost,
        "nav_curve": nav_curve,
        "returns": returns,
        "position_series": position_series,
        "metrics": summary,
    }
    validation = validate_no_lookahead(result)
    result["lookahead_safe"] = validation["ok"]
    result["lookahead_validation"] = validation
    result["regime_hit_return_map"] = metrics.regime_hit_return_map(returns)
    result["trend_state_alpha_contribution"] = metrics.trend_state_alpha_contribution(returns)
    result["risk_cap_reduction_effect"] = metrics.risk_cap_reduction_effect(returns)
    return result


def compare_backtests(
    records: list[dict[str, Any]],
    *,
    signal_delay_bars: int = 1,
    transaction_cost: float = 0.0,
) -> dict[str, Any]:
    v3 = run_backtest(
        records,
        position_field=DEFAULT_POSITION_FIELD,
        label="v3",
        signal_delay_bars=signal_delay_bars,
        transaction_cost=transaction_cost,
    )
    v2_proxy = run_backtest(
        records,
        position_field=V2_PROXY_POSITION_FIELD,
        label="v2_proxy_pre_cap",
        signal_delay_bars=signal_delay_bars,
        transaction_cost=transaction_cost,
    )
    return {
        "available": bool(v3.get("available") and v2_proxy.get("available")),
        "v3": v3,
        "v2_proxy": v2_proxy,
        "improvement": _metric_delta(v3.get("metrics", {}), v2_proxy.get("metrics", {})),
        "notes": [
            "v2_proxy uses pre_cap_market_position_score when exact historical v2 records are unavailable.",
            "positions are shifted by at least one bar; same-day score never trades same-day close-to-close return.",
        ],
    }


def validate_no_lookahead(result: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    delay = int(result.get("signal_delay_bars") or 0)
    if delay < 1:
        errors.append("signal_delay_bars must be at least 1")
    for index, row in enumerate(result.get("returns", []) or []):
        current_date = parse_date(row.get("date"))
        source_date = parse_date(row.get("source_signal_date"))
        lag = as_float(row.get("signal_lag_bars"))
        if source_date is None:
            errors.append(f"return row {index} has no source_signal_date")
            continue
        if current_date is not None and source_date >= current_date:
            errors.append(f"return row {index} uses non-prior signal date")
        if lag is None or lag < delay:
            errors.append(f"return row {index} signal lag is below configured delay")
    return {
        "ok": not errors,
        "errors": errors,
        "checked_return_count": len(result.get("returns", []) or []),
        "required_delay_bars": delay,
    }


def _position_score(record: dict[str, Any], position_field: str) -> float | None:
    if position_field == V2_PROXY_POSITION_FIELD:
        return (
            as_float(record.get("pre_cap_market_position_score"))
            or as_float(record.get("base_market_position_score"))
            or as_float(record.get("market_position_score"))
        )
    return as_float(record.get(position_field))


def _metric_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float | None]:
    fields = ["total_return", "cagr", "sharpe_ratio", "max_drawdown", "calmar_ratio", "turnover", "win_rate"]
    result: dict[str, float | None] = {}
    for field in fields:
        left = as_float(candidate.get(field))
        right = as_float(baseline.get(field))
        result[field] = left - right if left is not None and right is not None else None
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MyInvestMarket score-history backtests.")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_history_records(Path(args.history), include_legacy=args.include_legacy)
    result = compare_backtests(records)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    summary = {
        "available": result.get("available"),
        "v3": (result.get("v3") or {}).get("metrics"),
        "v2_proxy": (result.get("v2_proxy") or {}).get("metrics"),
        "improvement": result.get("improvement"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
