from __future__ import annotations

import json
from datetime import date
from typing import Any

import build_market_dataset


def probe(as_of: date | None = None) -> dict[str, Any]:
    basis = as_of or date.today()
    build_market_dataset.load_dotenv(build_market_dataset.ROOT / ".env")
    pro = build_market_dataset.tushare_client()

    contracts = pro.opt_basic(
        exchange="CFFEX",
        fields="ts_code,exchange,call_put,exercise_price,maturity_date,list_date,delist_date",
    )
    shibor = pro.shibor(
        start_date=build_market_dataset.yyyymmdd(basis.replace(day=1)),
        end_date=build_market_dataset.yyyymmdd(basis),
    )

    contract_counts = {
        prefix: int(contracts["ts_code"].astype(str).str.startswith(prefix).sum())
        for prefix in ("IO", "MO")
    }
    return {
        "available": bool(contract_counts["IO"] and contract_counts["MO"] and not shibor.empty),
        "basis_date": basis.isoformat(),
        "sources": {
            "Tushare.opt_basic": {
                "available": not contracts.empty,
                "contract_counts": contract_counts,
            },
            "Tushare.shibor": {
                "available": not shibor.empty,
                "latest_date": str(shibor.iloc[0]["date"]) if not shibor.empty else None,
                "has_1m": "1m" in shibor.columns,
            },
        },
        "secrets_exposed": False,
    }


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
