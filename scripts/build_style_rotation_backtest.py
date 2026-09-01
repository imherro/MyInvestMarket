from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "web" / "data" / "style-rotation-history.json"
CSINDEX_PERFORMANCE_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
DEFAULT_START_DATE = "20140101"
DEFAULT_END_DATE = "20241231"

SERIES = {
    "cashflow": {"code": "932365", "name": "中证全指自由现金流"},
    "technology": {"code": "931696", "name": "中证科技优势成长50策略"},
    "a500": {"code": "000510", "name": "中证A500"},
    "csi300": {"code": "000300", "name": "沪深300"},
}


def fetch_daily_closes(code: str, start_date: str, end_date: str) -> dict[str, float]:
    params = {
        "indexCode": code,
        "startDate": start_date,
        "endDate": end_date,
    }
    url = f"{CSINDEX_PERFORMANCE_URL}?{urlencode(params)}"
    completed = subprocess.run(
        [
            "curl", "-sS", "--retry", "3", "--connect-timeout", "15",
            "-H", "Referer: https://www.csindex.com.cn/",
            "-H", "X-Requested-With: XMLHttpRequest",
            "-H", "User-Agent: Mozilla/5.0 MyInvestMarket/1.0",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)
    observations = payload.get("data") or []
    if not observations:
        raise RuntimeError(f"No index data returned for {code}")
    result: dict[str, float] = {}
    for row in observations:
        date = str(row["tradeDate"]).replace("-", "")
        normalized_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        result[normalized_date] = float(row["close"])
    return result


def build_payload(start_date: str = DEFAULT_START_DATE, end_date: str = DEFAULT_END_DATE) -> dict[str, object]:
    closes = {key: fetch_daily_closes(meta["code"], start_date, end_date) for key, meta in SERIES.items()}
    common_dates = sorted(set.intersection(*(set(values) for values in closes.values())))
    if len(common_dates) < 100:
        raise RuntimeError(f"Common history is too short: {len(common_dates)} sessions")
    observations = [
        {
            "date": date,
            **{key: round(values[date], 4) for key, values in closes.items()},
        }
        for date in common_dates
    ]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "provider": "中证指数有限公司历史行情接口",
            "url": CSINDEX_PERFORMANCE_URL,
            "price_type": "收盘价格指数",
            "backfilled_index_warning": "部分指数晚于样本起点发布，历史序列包含回溯计算，存在指数设计与幸存者偏差。",
        },
        "series": SERIES,
        "sample": {
            "first_date": common_dates[0],
            "last_date": common_dates[-1],
            "sessions": len(common_dates),
        },
        "observations": observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build data for the cash-flow / technology rotation page")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    args = parser.parse_args()
    payload = build_payload(args.start_date, args.end_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    sample = payload["sample"]
    print(f"Wrote {args.output} ({sample['first_date']} to {sample['last_date']}, {sample['sessions']} sessions)")


if __name__ == "__main__":
    main()
