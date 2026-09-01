from __future__ import annotations

"""Point-in-time profit-growth aggregation for Cycle Dataset v1."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE = "Tushare.income_vip"
MIN_CURRENT_COVERAGE = 0.70
MIN_MATCHED_COVERAGE = 0.65


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def quarter_ends(start_year: int, end_year: int) -> list[str]:
    return [f"{year}{suffix}" for year in range(start_year, end_year + 1) for suffix in ("0331", "0630", "0930", "1231")]


def period_date(period: str) -> date:
    return datetime.strptime(period, "%Y%m%d").date()


def prior_year_period(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def normalise_income(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "n_income_attr_p", "update_flag"]
    result = frame.reindex(columns=columns).copy()
    for column in ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "update_flag"):
        result[column] = result[column].fillna("").astype(str)
    result["n_income_attr_p"] = pd.to_numeric(result["n_income_attr_p"], errors="coerce")
    result["_effective_ann"] = result.apply(
        lambda row: parse_date(row["f_ann_date"]) or parse_date(row["ann_date"]), axis=1
    )
    result = result.dropna(subset=["_effective_ann", "n_income_attr_p"])
    result = result.loc[result["ts_code"] != ""].copy()
    result["_effective_ann_str"] = result["_effective_ann"].map(lambda value: value.strftime("%Y%m%d"))
    return result.sort_values(["end_date", "ts_code", "_effective_ann_str", "update_flag"]).reset_index(drop=True)


def cache_payload(income: pd.DataFrame, stocks: pd.DataFrame, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    rows = income.drop(columns=[column for column in income.columns if column.startswith("_")], errors="ignore")
    return {
        "schema_version": 1,
        "source": SOURCE,
        "income_records": rows.to_dict(orient="records"),
        "stock_records": stocks.to_dict(orient="records"),
        "conflicts": conflicts,
    }


def load_cache(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported cycle earnings cache schema")
    return (
        normalise_income(pd.DataFrame(payload.get("income_records", []))),
        normalise_stocks(pd.DataFrame(payload.get("stock_records", []))),
        list(payload.get("conflicts", [])),
    )


def normalise_stocks(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.reindex(columns=["ts_code", "list_date", "delist_date"]).copy()
    for column in result.columns:
        result[column] = result[column].fillna("").astype(str)
    return result.loc[result["ts_code"] != ""].drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def fetch_source(pro: Any, start_year: int, end_year: int) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    for period in quarter_ends(start_year, end_year):
        frame = pro.income_vip(
            period=period,
            fields="ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,n_income_attr_p,update_flag",
        )
        if not frame.empty:
            frames.append(frame)
    income = normalise_income(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    conflicts: list[dict[str, Any]] = []
    identity = ["ts_code", "end_date", "report_type", "_effective_ann_str"]
    for keys, group in income.groupby(identity, dropna=False):
        values = group["n_income_attr_p"].dropna().unique()
        if len(values) > 1:
            conflicts.append({"identity": dict(zip(identity, keys)), "value_count": int(len(values))})
    stock_frames = []
    for status in ("L", "D", "P"):
        frame = pro.stock_basic(exchange="", list_status=status, fields="ts_code,list_date,delist_date")
        if not frame.empty:
            stock_frames.append(frame)
    stocks = normalise_stocks(pd.concat(stock_frames, ignore_index=True) if stock_frames else pd.DataFrame())
    return income, stocks, conflicts


def source_from_cache_or_api(pro: Any, cache_path: Path, start_year: int, end_year: int) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    cached = load_cache(cache_path)
    if cached is not None:
        return cached
    income, stocks, conflicts = fetch_source(pro, start_year, end_year)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache_payload(income, stocks, conflicts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return income, stocks, conflicts


def eligible_universe(stocks: pd.DataFrame, report_period: str) -> set[str]:
    end = period_date(report_period).strftime("%Y%m%d")
    valid = stocks.loc[(stocks["list_date"] <= end) & ((stocks["delist_date"] == "") | (stocks["delist_date"] > end))]
    return set(valid["ts_code"])


def prepare_income_by_period(income: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {str(period): group.reset_index(drop=True) for period, group in income.groupby("end_date", sort=False)}


def visible_deduped(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    frame = frame.loc[frame["_effective_ann"] <= basis].copy()
    if frame.empty:
        return frame
    # prepare_income_by_period preserves the cache's deterministic ts_code/date order.
    # The last visible row is therefore the latest version known on this basis date.
    return frame.drop_duplicates("ts_code", keep="last")


def aggregate_side(current: pd.DataFrame, prior: pd.DataFrame, universe: set[str], nonfinancial: bool, basis: date, current_period: str) -> dict[str, Any]:
    current_all = current.loc[current["ts_code"].isin(universe)].copy()
    prior_all = prior.loc[prior["ts_code"].isin(universe)].copy()
    classified_current_count = int((current_all["comp_type"] != "").sum())
    classification_coverage = classified_current_count / len(universe) if universe else 0.0
    if nonfinancial:
        # Unknown classifications are deliberately excluded, never assumed nonfinancial.
        current = current_all.loc[current_all["comp_type"] == "1"].copy()
        prior = prior_all.loc[prior_all["comp_type"] == "1"].copy()
    else:
        current, prior = current_all, prior_all
    current_by_code = current.set_index("ts_code")["n_income_attr_p"]
    prior_by_code = prior.set_index("ts_code")["n_income_attr_p"]
    matched = sorted(set(current_by_code.index) & set(prior_by_code.index))
    eligible_count = len(universe)
    current_coverage = len(current_by_code) / eligible_count if eligible_count else 0.0
    matched_coverage = len(matched) / eligible_count if eligible_count else 0.0
    current_profit = float(current_by_code.loc[matched].sum()) if matched else None
    prior_profit = float(prior_by_code.loc[matched].sum()) if matched else None
    latest_ann = current.loc[current["ts_code"].isin(matched), "_effective_ann"].max() if matched else None
    if pd.isna(latest_ann):
        latest_ann = None
    reason = None
    yoy = None
    if current_coverage < MIN_CURRENT_COVERAGE:
        reason = f"current period coverage below {MIN_CURRENT_COVERAGE:.0%}"
    elif matched_coverage < MIN_MATCHED_COVERAGE:
        reason = f"matched coverage below {MIN_MATCHED_COVERAGE:.0%}"
    elif prior_profit is None or prior_profit <= 0:
        reason = "non-positive aggregate prior-year profit"
    elif current_profit is not None:
        yoy = (current_profit / prior_profit - 1) * 100
    return {
        "value": round(yoy, 4) if yoy is not None else None,
        "observation_date": None,
        "announcement_date": iso(latest_ann),
        "source": SOURCE,
        "lag_days": (basis - latest_ann).days if latest_ann else None,
        "available": yoy is not None and latest_ann is not None and latest_ann <= basis,
        "pit_safe": latest_ann <= basis if latest_ann else False,
        "reason": reason,
        "current_aggregate_profit": round(current_profit, 2) if current_profit is not None else None,
        "prior_aggregate_profit": round(prior_profit, 2) if prior_profit is not None else None,
        "matched_stock_count": len(matched),
        "eligible_stock_count": eligible_count,
        "current_period_coverage_rate": round(current_coverage * 100, 4),
        "matched_coverage_rate": round(matched_coverage * 100, 4),
        "report_period": current_period,
        "prior_year_report_period": prior_year_period(current_period),
        "classification_coverage_rate": round(classification_coverage * 100, 4),
    }


def profit_growth_snapshot(income_by_period: dict[str, pd.DataFrame], stocks: pd.DataFrame, basis: date) -> dict[str, Any]:
    candidates = [period for period in sorted(income_by_period, reverse=True) if period_date(period) <= basis]
    for period in candidates:
        prior_period = prior_year_period(period)
        if prior_period not in income_by_period:
            continue
        universe = eligible_universe(stocks, period)
        current = visible_deduped(income_by_period[period], basis)
        current_coverage = len(current.loc[current["ts_code"].isin(universe)]) / len(universe) if universe else 0.0
        if current_coverage < MIN_CURRENT_COVERAGE:
            continue
        prior = visible_deduped(income_by_period[prior_period], basis)
        return {
            "all_a": aggregate_side(current, prior, universe, False, basis, period),
            "nonfinancial_a": aggregate_side(current, prior, universe, True, basis, period),
        }
    reason = "no quarterly report period reached current coverage threshold"
    unavailable = {"value": None, "observation_date": None, "announcement_date": None, "source": SOURCE, "lag_days": None, "available": False, "pit_safe": False, "reason": reason, "current_aggregate_profit": None, "prior_aggregate_profit": None, "matched_stock_count": 0, "eligible_stock_count": 0, "current_period_coverage_rate": 0.0, "matched_coverage_rate": 0.0, "report_period": None, "prior_year_report_period": None, "classification_coverage_rate": 0.0}
    return {"all_a": unavailable, "nonfinancial_a": dict(unavailable)}
