from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import backtest_engine


def validate_oos(
    records: list[dict[str, Any]],
    *,
    train_ratio: float = 0.6,
    validation_ratio: float = 0.2,
) -> dict[str, Any]:
    ordered = latest_per_trade_date(_sort_records(records))
    if len(ordered) < 9:
        return {
            "available": False,
            "reason": "at least 9 dated records are required for train/validation/test split",
            "record_count": len(ordered),
            "leakage_check": {"ok": True, "errors": []},
        }
    train, validation, test = split_records(ordered, train_ratio=train_ratio, validation_ratio=validation_ratio)
    train_result = backtest_engine.run_backtest(train, label="train")
    validation_result = backtest_engine.run_backtest(validation, label="validation")
    test_result = backtest_engine.run_backtest(test, label="test")
    leakage = leakage_check(train, validation, test)
    in_sample = _metric(train_result, "sharpe_ratio")
    oos = _metric(test_result, "sharpe_ratio")
    return {
        "available": bool(train_result.get("available") and test_result.get("available")),
        "version": "oos_validator_v1",
        "splits": {
            "train": split_meta(train),
            "validation": split_meta(validation),
            "test": split_meta(test),
        },
        "in_sample_sharpe": in_sample,
        "validation_sharpe": _metric(validation_result, "sharpe_ratio"),
        "oos_sharpe": oos,
        "overfitting_gap": in_sample - oos,
        "leakage_check": leakage,
        "results": {
            "train": train_result.get("metrics", {}),
            "validation": validation_result.get("metrics", {}),
            "test": test_result.get("metrics", {}),
        },
    }


def split_records(
    records: list[dict[str, Any]],
    *,
    train_ratio: float = 0.6,
    validation_ratio: float = 0.2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = latest_per_trade_date(_sort_records(records))
    n = len(ordered)
    train_end = max(1, min(n - 2, int(n * train_ratio)))
    validation_end = max(train_end + 1, min(n - 1, train_end + int(n * validation_ratio)))
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]


def leakage_check(train: list[dict[str, Any]], validation: list[dict[str, Any]], test: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if train and validation and _last_date(train) >= _first_date(validation):
        errors.append("train overlaps validation")
    if validation and test and _last_date(validation) >= _first_date(test):
        errors.append("validation overlaps test")
    if train and test and _last_date(train) >= _first_date(test):
        errors.append("train overlaps test")
    return {"ok": not errors, "errors": errors}


def latest_per_trade_date(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("basis_trade_date") or "")
        if key:
            selected[key] = record
    return [selected[key] for key in sorted(selected.keys())]


def split_meta(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "start": _first_date(records).isoformat() if records else None,
        "end": _last_date(records).isoformat() if records else None,
    }


def _metric(result: dict[str, Any], key: str) -> float:
    return backtest_engine.as_float((result.get("metrics") or {}).get(key)) or 0.0


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [record for record in records if isinstance(record, dict) and _parse_date(record.get("basis_trade_date")) is not None],
        key=lambda row: (_parse_date(row.get("basis_trade_date")) or date.min, str(row.get("scored_at", ""))),
    )


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _first_date(records: list[dict[str, Any]]) -> date:
    return _parse_date(records[0].get("basis_trade_date")) or date.min


def _last_date(records: list[dict[str, Any]]) -> date:
    return _parse_date(records[-1].get("basis_trade_date")) or date.min


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate MyInvestMarket out-of-sample performance.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    print(json.dumps(validate_oos(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
