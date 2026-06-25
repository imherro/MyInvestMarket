from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import backtest_engine
import metrics


def monitor_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    backtest = backtest_engine.run_backtest(records)
    return monitor_backtest(backtest)


def monitor_backtest(backtest: dict[str, Any]) -> dict[str, Any]:
    rows = backtest.get("returns", []) if isinstance(backtest.get("returns"), list) else []
    if not rows:
        return {
            "available": False,
            "reason": "backtest return rows are unavailable",
            "rolling_sharpe_20d": 0.0,
            "rolling_sharpe_60d": 0.0,
            "sharpe_decay": False,
        }
    returns = [metrics.as_float(row.get("strategy_return")) or 0.0 for row in rows]
    sharpe_20 = rolling_sharpe(returns, 20)
    sharpe_60 = rolling_sharpe(returns, 60)
    drawdown_20 = rolling_max_drawdown(returns, 20)
    drawdown_60 = rolling_max_drawdown(returns, 60)
    regime_hit = rolling_regime_hit_rate(rows, 20)
    sharpe_decay = bool(sharpe_60 > 0 and sharpe_20 < sharpe_60 - 0.5)
    return {
        "available": True,
        "version": "rolling_monitor_v1",
        "return_count": len(rows),
        "rolling_sharpe_20d": sharpe_20,
        "rolling_sharpe_60d": sharpe_60,
        "rolling_max_drawdown_20d": drawdown_20,
        "rolling_max_drawdown_60d": drawdown_60,
        "regime_hit_rate_20d": regime_hit,
        "sharpe_decay": sharpe_decay,
        "series": {
            "rolling_sharpe_20d": rolling_sharpe_series(returns, 20),
            "rolling_sharpe_60d": rolling_sharpe_series(returns, 60),
        },
    }


def rolling_sharpe(returns: list[float], window: int) -> float:
    values = _window(returns, window)
    return metrics.sharpe_ratio(values)


def rolling_max_drawdown(returns: list[float], window: int) -> float:
    values = _window(returns, window)
    return metrics.max_drawdown(metrics.nav_from_returns(values))


def rolling_sharpe_series(returns: list[float], window: int) -> list[float]:
    if not returns:
        return []
    series = []
    for index in range(len(returns)):
        start = max(0, index - window + 1)
        series.append(metrics.sharpe_ratio(returns[start : index + 1]))
    return series


def rolling_regime_hit_rate(rows: list[dict[str, Any]], window: int) -> dict[str, float]:
    selected = rows[-window:] if len(rows) > window else rows
    grouped: dict[str, list[float]] = {}
    for row in selected:
        key = str(row.get("market_regime") or "unknown")
        grouped.setdefault(key, []).append(metrics.as_float(row.get("strategy_return")) or 0.0)
    return {key: metrics.win_rate(values) for key, values in sorted(grouped.items())}


def _window(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    return values[-window:] if len(values) > window else values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor rolling MyInvestMarket model performance.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(monitor_records(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
