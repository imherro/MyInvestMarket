from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


TZ = ZoneInfo("Asia/Shanghai")


def configured() -> bool:
    value = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    return bool(value and value != "REPLACE_WITH_YOUR_HITHINK_FINANCE_API_KEY")


def _cli() -> str | None:
    return os.environ.get("HITHINK_FINANCE_CLI") or shutil.which("hithink-finance")


def _run(args: list[str]) -> dict[str, object]:
    cli = _cli()
    if not cli:
        raise RuntimeError("hithink-finance CLI not found")
    completed = subprocess.run(
        [cli, "--source", "remote", "--format", "json", "--no-input", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if not output:
        raise RuntimeError((completed.stderr or "hithink-finance returned no output").strip())
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid hithink-finance JSON: {output[:240]}") from exc
    if completed.returncode != 0 or payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(str(error or completed.stderr or "hithink-finance request failed"))
    return payload


def index_history(thscode: str, start: date, end: date) -> pd.DataFrame:
    start_ms = int(datetime.combine(start, time.min, TZ).timestamp() * 1000)
    end_ms = int(datetime.combine(end, time.max, TZ).timestamp() * 1000)
    payload = _run([
        "index",
        "history",
        "--thscode",
        thscode,
        "--start-ms",
        str(start_ms),
        "--end-ms",
        str(end_ms),
    ])
    data = payload.get("data")
    items = data.get("item", []) if isinstance(data, dict) else []
    rows: list[dict[str, object]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        date_ms = item.get("date_ms")
        if date_ms is None:
            continue
        observed = datetime.fromtimestamp(float(date_ms) / 1000, TZ).date()
        rows.append(
            {
                "trade_date": observed.strftime("%Y%m%d"),
                "open": item.get("open_price"),
                "high": item.get("high_price"),
                "low": item.get("low_price"),
                "close": item.get("close_price"),
                "vol": item.get("volume"),
                "amount": item.get("turnover"),
            }
        )
    return pd.DataFrame(rows)


def special_pool_total(pool: str, trade_date: date) -> int | None:
    date_ms = int(datetime.combine(trade_date, time.min, TZ).timestamp() * 1000)
    payload = _run([
        "special",
        pool,
        "--date-ms",
        str(date_ms),
        "--page",
        "1",
        "--size",
        "1",
    ])
    data = payload.get("data")
    pagination = data.get("pagination") if isinstance(data, dict) else None
    total = pagination.get("total") if isinstance(pagination, dict) else None
    return int(total) if total is not None else None
