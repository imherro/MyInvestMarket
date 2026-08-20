from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import a_fear
import build_market_dataset


INDEX_CODES = {"csi300": "000300.SH", "csi1000": "000852.SH"}
OPTION_FAMILIES = {"io": "IO", "mo": "MO"}


def api_call(call: Callable[..., pd.DataFrame], *args: Any, **kwargs: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            return call(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(str(last_error))


def load_source_cache(path: Path = a_fear.DEFAULT_SOURCE_CACHE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "version": a_fear.VERSION, "observations": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise ValueError("A-FEAR source cache must contain an observations array")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def open_trade_dates(pro: Any, as_of: date, count: int) -> list[str]:
    start = as_of - timedelta(days=max(count * 2 + 60, 120))
    calendar = api_call(
        pro.trade_cal,
        exchange="SSE",
        start_date=build_market_dataset.yyyymmdd(start),
        end_date=build_market_dataset.yyyymmdd(as_of),
        is_open="1",
    )
    if calendar.empty:
        raise RuntimeError("Tushare trade calendar returned no open dates")
    return sorted(calendar["cal_date"].astype(str).tolist())[-count:]


def fetch_index_history(pro: Any, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for name, code in INDEX_CODES.items():
        frame = api_call(pro.index_daily, ts_code=code, start_date=start_date, end_date=end_date)
        if frame.empty:
            raise RuntimeError(f"Tushare.index_daily returned no data for {code}")
        frame = frame.copy()
        frame["trade_date"] = frame["trade_date"].astype(str)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.sort_values("trade_date").dropna(subset=["close"]).reset_index(drop=True)
        frame["return_1d"] = frame["close"].pct_change(fill_method=None)
        frame["loss_1d"] = (-frame["return_1d"]).clip(lower=0)
        frame["loss_5d"] = (-(frame["close"] / frame["close"].shift(5) - 1)).clip(lower=0)
        negative = frame["return_1d"].clip(upper=0)
        frame["downside_vol_20d"] = (negative.pow(2).rolling(20).mean() * 252).pow(0.5)
        result[name] = frame
    return result


def fetch_shibor_history(pro: Any, start_date: str, end_date: str) -> pd.DataFrame:
    frame = api_call(pro.shibor, start_date=start_date, end_date=end_date)
    if frame.empty or "1m" not in frame.columns:
        return pd.DataFrame(columns=["date", "1m"])
    frame = frame.copy()
    frame["date"] = frame["date"].astype(str)
    frame["1m"] = pd.to_numeric(frame["1m"], errors="coerce")
    return frame.sort_values("date").dropna(subset=["1m"]).reset_index(drop=True)


def rate_at_or_before(shibor: pd.DataFrame, trade_date: str) -> tuple[float, str | None, bool]:
    eligible = shibor.loc[shibor["date"] <= trade_date] if not shibor.empty else shibor
    if eligible.empty:
        return 0.015, None, True
    latest = eligible.iloc[-1]
    return float(latest["1m"]) / 100.0, str(latest["date"]), False


def fetch_contracts(pro: Any) -> pd.DataFrame:
    frame = api_call(
        pro.opt_basic,
        exchange="CFFEX",
        fields="ts_code,exchange,call_put,exercise_price,maturity_date,list_date,delist_date",
    )
    if frame.empty:
        raise RuntimeError("Tushare.opt_basic returned no CFFEX contracts")
    frame = frame.copy()
    for column in ("ts_code", "call_put", "maturity_date", "list_date", "delist_date"):
        frame[column] = frame[column].astype(str)
    frame["exercise_price"] = pd.to_numeric(frame["exercise_price"], errors="coerce")
    return frame


def fixed_30d_family_iv(
    chain: pd.DataFrame,
    family_prefix: str,
    basis: date,
    rate: float,
) -> dict[str, Any]:
    family = chain.loc[chain["ts_code"].astype(str).str.startswith(family_prefix)].copy()
    if family.empty:
        return {"available": False, "reason": f"no {family_prefix} option rows"}

    expiry_results: list[dict[str, Any]] = []
    for maturity, group in family.groupby("maturity_date"):
        try:
            expiry = datetime.strptime(str(maturity), "%Y%m%d").date()
        except ValueError:
            continue
        days = (expiry - basis).days
        if days <= 0:
            continue
        result = a_fear.atm_iv_for_expiry(group.to_dict("records"), days / 365.0, rate)
        if result.get("available"):
            expiry_results.append({**result, "maturity_date": expiry.isoformat(), "days_to_expiry": days})

    points = [(item["days_to_expiry"], item["atm_iv"]) for item in expiry_results]
    fixed_iv = a_fear.interpolate_fixed_maturity_iv(points)
    if fixed_iv is None:
        return {
            "available": False,
            "reason": "no valid expiries bracketing 30 calendar days",
            "expiry_results": expiry_results,
        }
    before = max((item for item in expiry_results if item["days_to_expiry"] <= 30), key=lambda item: item["days_to_expiry"], default=None)
    after = min((item for item in expiry_results if item["days_to_expiry"] >= 30), key=lambda item: item["days_to_expiry"], default=None)
    evidence = []
    for item in (before, after):
        if item and item not in evidence:
            evidence.append(item)
    return {
        "available": True,
        "iv_30d": round(fixed_iv, 8),
        "target_days": 30,
        "rate": rate,
        "expiry_evidence": evidence,
    }


def index_row(frame: pd.DataFrame, trade_date: str) -> pd.Series | None:
    rows = frame.loc[frame["trade_date"] == trade_date]
    return rows.iloc[-1] if not rows.empty else None


def build_observation(
    pro: Any,
    trade_date: str,
    contracts: pd.DataFrame,
    index_history: dict[str, pd.DataFrame],
    shibor: pd.DataFrame,
) -> dict[str, Any] | None:
    stock_daily = api_call(pro.daily, trade_date=trade_date)
    option_daily = api_call(
        pro.opt_daily,
        trade_date=trade_date,
        exchange="CFFEX",
        fields="ts_code,trade_date,exchange,close,settle,vol,oi",
    )
    if stock_daily.empty or option_daily.empty:
        return None

    limit_list = api_call(pro.limit_list_d, trade_date=trade_date)
    active_contracts = contracts.loc[
        (contracts["list_date"] <= trade_date) & (contracts["delist_date"] >= trade_date)
    ]
    chain = option_daily.merge(active_contracts, on="ts_code", how="inner", suffixes=("", "_contract"))
    basis = datetime.strptime(trade_date, "%Y%m%d").date()
    rate, rate_date, rate_fallback = rate_at_or_before(shibor, trade_date)
    iv_results = {
        name: fixed_30d_family_iv(chain, prefix, basis, rate)
        for name, prefix in OPTION_FAMILIES.items()
    }

    pct_change = pd.to_numeric(stock_daily.get("pct_chg"), errors="coerce").dropna()
    total = int(len(pct_change))
    if total == 0:
        return None
    decliners = int((pct_change < 0).sum())
    decline_beyond_3pct = int((pct_change <= -3).sum())
    if limit_list.empty or "limit" not in limit_list.columns:
        limit_down = int((pct_change <= -9.5).sum())
        limit_source = "Tushare.daily.pct_chg_fallback"
    else:
        limit_down = int((limit_list["limit"].astype(str).str.upper() == "D").sum())
        limit_source = "Tushare.limit_list_d"

    index_values: dict[str, Any] = {}
    for name, frame in index_history.items():
        row = index_row(frame, trade_date)
        if row is None:
            return None
        index_values[name] = {
            "downside_vol_20d": a_fear.finite_float(row.get("downside_vol_20d"), 8),
            "loss_1d": a_fear.finite_float(row.get("loss_1d"), 8),
            "loss_5d": a_fear.finite_float(row.get("loss_5d"), 8),
            "close": a_fear.finite_float(row.get("close"), 4),
        }

    warnings: list[str] = []
    if rate_fallback:
        warnings.append("One-month SHIBOR unavailable; 1.5% annual rate fallback used.")
    for family, result in iv_results.items():
        if not result.get("available"):
            warnings.append(f"{family.upper()} fixed-30-day IV unavailable: {result.get('reason')}")

    return {
        "basis_trade_date": basis.isoformat(),
        "implied_volatility": {
            "io_iv_30d": iv_results["io"].get("iv_30d"),
            "mo_iv_30d": iv_results["mo"].get("iv_30d"),
        },
        "implied_volatility_details": iv_results,
        "downside_volatility": {
            "csi300_20d": index_values["csi300"]["downside_vol_20d"],
            "csi1000_20d": index_values["csi1000"]["downside_vol_20d"],
        },
        "market_breadth": {
            "decliner_ratio": round(decliners / total, 8),
            "decline_beyond_3pct_ratio": round(decline_beyond_3pct / total, 8),
            "limit_down_ratio": round(limit_down / total, 8),
            "total": total,
            "decliners": decliners,
            "decline_beyond_3pct": decline_beyond_3pct,
            "limit_down": limit_down,
        },
        "tail_loss": {
            "csi300_loss_1d": index_values["csi300"]["loss_1d"],
            "csi300_loss_5d": index_values["csi300"]["loss_5d"],
            "csi1000_loss_1d": index_values["csi1000"]["loss_1d"],
            "csi1000_loss_5d": index_values["csi1000"]["loss_5d"],
        },
        "index_closes": {
            "000300.SH": index_values["csi300"]["close"],
            "000852.SH": index_values["csi1000"]["close"],
        },
        "source_dates": {
            "market": basis.isoformat(),
            "options": basis.isoformat(),
            "shibor_1m": build_market_dataset.iso_date(rate_date) if rate_date else None,
        },
        "sources": [
            "Tushare.opt_basic",
            "Tushare.opt_daily",
            "Tushare.index_daily",
            "Tushare.daily",
            limit_source,
            "Tushare.shibor",
        ],
        "data_quality": {"warnings": warnings},
    }


def merge_scored_history(records: list[dict[str, Any]], history_path: Path, latest_path: Path) -> dict[str, Any]:
    existing = a_fear.load_history(history_path)
    existing_by_date = {
        str(item.get("basis_trade_date")): item
        for item in existing.get("records", [])
        if item.get("version") == a_fear.VERSION
    }
    merged: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for record in records:
        trade_date = str(record["basis_trade_date"])
        previous = existing_by_date.get(trade_date)
        if previous and previous.get("input_hash") == record.get("input_hash"):
            merged.append(previous)
        elif previous and previous.get("confidence") == "unavailable" and record.get("confidence") != "unavailable":
            merged.append(record)
        elif previous:
            conflicts.append(trade_date)
            merged.append(previous)
        else:
            merged.append(record)
    if conflicts:
        raise RuntimeError(f"A-FEAR immutable history conflict on: {', '.join(conflicts)}")
    payload = {"schema_version": a_fear.SCHEMA_VERSION, "version": a_fear.VERSION, "records": merged}
    write_json(history_path, payload)
    if merged:
        write_json(latest_path, merged[-1])
    return {"record_count": len(merged), "latest": merged[-1] if merged else None}


def build(
    as_of: date,
    trading_days: int,
    refresh: bool = False,
    cache_path: Path = a_fear.DEFAULT_SOURCE_CACHE_PATH,
    history_path: Path = a_fear.DEFAULT_HISTORY_PATH,
    latest_path: Path = a_fear.DEFAULT_LATEST_PATH,
) -> dict[str, Any]:
    build_market_dataset.load_dotenv(build_market_dataset.ROOT / ".env")
    pro = build_market_dataset.tushare_client()
    trade_dates = open_trade_dates(pro, as_of, trading_days)
    history_start = datetime.strptime(trade_dates[0], "%Y%m%d").date() - timedelta(days=60)
    start_date = build_market_dataset.yyyymmdd(history_start)
    end_date = trade_dates[-1]
    index_history = fetch_index_history(pro, start_date, end_date)
    shibor = fetch_shibor_history(pro, start_date, end_date)
    contracts = fetch_contracts(pro)

    cache = load_source_cache(cache_path)
    by_date = {str(item.get("basis_trade_date")): item for item in cache["observations"]}
    fetched = 0
    skipped = 0
    for index, trade_date in enumerate(trade_dates, start=1):
        iso_trade_date = build_market_dataset.iso_date(trade_date)
        if iso_trade_date in by_date and not refresh:
            skipped += 1
            continue
        observation = build_observation(pro, trade_date, contracts, index_history, shibor)
        if observation is None:
            continue
        by_date[iso_trade_date] = observation
        fetched += 1
        cache_payload = {
            "schema_version": 1,
            "version": a_fear.VERSION,
            "observations": [by_date[key] for key in sorted(by_date)],
        }
        write_json(cache_path, cache_payload)
        print(f"A-FEAR source {index}/{len(trade_dates)}: {iso_trade_date}", flush=True)

    observations = [by_date[key] for key in sorted(by_date) if key <= build_market_dataset.iso_date(end_date)]
    records = a_fear.score_observation_series(observations)
    persistence = merge_scored_history(records, history_path, latest_path)
    return {
        "version": a_fear.VERSION,
        "requested_trading_days": trading_days,
        "source_observation_count": len(observations),
        "fetched": fetched,
        "skipped_cached": skipped,
        **persistence,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and score the A-FEAR v1 daily dataset")
    parser.add_argument("--as-of", help="Calendar date in YYYY-MM-DD format; defaults to today")
    parser.add_argument("--trading-days", type=int, default=1, help="Number of latest open trading days to ensure")
    parser.add_argument("--refresh", action="store_true", help="Refetch dates already present in the source cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()
    result = build(as_of, max(args.trading_days, 1), refresh=args.refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
