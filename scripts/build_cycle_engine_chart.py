"""Build monthly Cycle Engine chart data with the Shanghai Composite background."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import tushare as ts


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
POLICY_PATH = DATA / "cycle_engine_position_policy_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_chart_v1.json"


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build() -> dict[str, Any]:
    load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy_rows = policy.get("records", [])
    if not policy_rows:
        raise RuntimeError("cycle position policy has no records")
    ts.set_token(token)
    pro = ts.pro_api(token)
    index_rows = pro.index_daily(
        ts_code="000001.SH",
        start_date=f"{policy_rows[0]['month'][:4]}0101",
        end_date=policy_rows[-1]["basis_trade_date"].replace("-", ""),
        fields="trade_date,close",
    )
    if index_rows.empty:
        raise RuntimeError("Tushare returned no Shanghai Composite data")
    index_rows = index_rows.sort_values("trade_date")
    dates = index_rows["trade_date"].astype(str).tolist()
    closes = index_rows["close"].astype(float).tolist()
    rows = []
    cursor = 0
    for policy_row in policy_rows:
        basis = policy_row["basis_trade_date"].replace("-", "")
        while cursor + 1 < len(dates) and dates[cursor + 1] <= basis:
            cursor += 1
        close = closes[cursor] if dates[cursor] <= basis else None
        minimum = policy_row.get("equity_min_pct")
        maximum = policy_row.get("equity_max_pct")
        midpoint = (minimum + maximum) / 2 if minimum is not None and maximum is not None else None
        rows.append(
            {
                "month": policy_row["month"],
                "basis_trade_date": policy_row["basis_trade_date"],
                "stable_state": policy_row["stable_state"],
                "equity_min_pct": minimum,
                "equity_max_pct": maximum,
                "equity_mid_pct": midpoint,
                "recommended_equity_range": f"{minimum}%-{maximum}%" if minimum is not None and maximum is not None else None,
                "shanghai_trade_date": f"{dates[cursor][:4]}-{dates[cursor][4:6]}-{dates[cursor][6:]}" if close is not None else None,
                "shanghai_composite": round(close, 3) if close is not None else None,
            }
        )
    return {
        "schema": "cycle_engine_chart_v1",
        "description": "Monthly stable cycle state and equity range with Shanghai Composite background.",
        "research_only": True,
        "index_code": "000001.SH",
        "index_source": "Tushare.index_daily",
        "record_count": len(rows),
        "records": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    output = build()
    if args.generate:
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"record_count": output["record_count"], "first": output["records"][0], "last": output["records"][-1]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
