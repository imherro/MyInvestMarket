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
CURRENT_REPORT_TYPE = "1"
PRIOR_REPORT_TYPES = ("4", "1")


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


def expected_financial_periods(as_of: date, start_year: int = 2009) -> list[str]:
    """Return report periods whose statutory A-share disclosure deadline has passed."""
    required: list[str] = []
    for year in range(start_year, as_of.year + 1):
        deadlines = ((f"{year}0331", date(year, 4, 30)), (f"{year}0630", date(year, 8, 31)), (f"{year}0930", date(year, 10, 31)), (f"{year}1231", date(year + 1, 4, 30)))
        required.extend(period for period, deadline in deadlines if deadline <= as_of)
    return required


def audit_cache_freshness(income: pd.DataFrame, metadata: dict[str, Any], as_of: date, start_year: int = 2009, refresh_error: str | None = None) -> dict[str, Any]:
    required = expected_financial_periods(as_of, start_year)
    covered = sorted(set(income["end_date"].astype(str))) if not income.empty else []
    missing = [period for period in required if period not in set(covered)]
    refreshed = parse_date(metadata.get("last_successful_refresh_date") or metadata.get("last_refresh_date"))
    return {"required_periods": required, "covered_periods": covered, "missing_expected_periods": missing, "latest_required_period": required[-1] if required else None, "latest_cached_period": covered[-1] if covered else None, "stale": bool(missing), "last_refresh_date": iso(refreshed), "last_successful_refresh_date": iso(refreshed), "refresh_lag_days": (as_of - refreshed).days if refreshed else None, "refresh_error": refresh_error if refresh_error is not None else metadata.get("refresh_error")}


def normalise_income(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "n_income_attr_p", "update_flag"]
    result = frame.reindex(columns=columns).copy()
    for column in ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "update_flag"):
        result[column] = result[column].fillna("").astype(str)
    result["n_income_attr_p"] = pd.to_numeric(result["n_income_attr_p"], errors="coerce")
    final_ann = pd.to_datetime(result["f_ann_date"], errors="coerce")
    announced = pd.to_datetime(result["ann_date"], errors="coerce")
    result["_effective_ann"] = final_ann.fillna(announced).dt.date
    result = result.dropna(subset=["_effective_ann", "n_income_attr_p"])
    result = result.loc[(result["ts_code"] != "") & (result["end_date"] != "")].copy()
    result["_effective_ann_str"] = result["_effective_ann"].map(lambda value: value.strftime("%Y%m%d"))
    identity = ["ts_code", "end_date", "report_type", "_effective_ann_str", "update_flag"]
    result["_ambiguous_source_conflict"] = result.groupby(identity)["n_income_attr_p"].transform("nunique").gt(1)
    return result.sort_values(["end_date", "ts_code", "report_type", "_effective_ann_str", "update_flag", "n_income_attr_p"], kind="stable").reset_index(drop=True)


def normalise_stocks(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.reindex(columns=["ts_code", "list_date", "delist_date"]).copy()
    for column in result.columns:
        result[column] = result[column].fillna("").astype(str)
    return result.loc[result["ts_code"] != ""].drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def source_conflicts(income: pd.DataFrame) -> list[dict[str, Any]]:
    identity = ["ts_code", "end_date", "report_type", "_effective_ann_str", "update_flag"]
    conflicts: list[dict[str, Any]] = []
    for keys, group in income.groupby(identity, dropna=False, sort=True):
        values = sorted(float(value) for value in group["n_income_attr_p"].dropna().unique())
        if len(values) > 1:
            conflicts.append({"identity": dict(zip(identity, keys)), "value_count": len(values), "values": values})
    return conflicts


def cache_metadata(income: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, stock_metadata_conflicts: list[dict[str, Any]] | None = None, refresh_error: str | None = None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    periods = sorted(set(income["end_date"].astype(str))) if not income.empty else []
    metadata = dict(existing or {})
    successful = iso(refreshed_at) if refreshed_at else metadata.get("last_successful_refresh_date") or metadata.get("last_refresh_date")
    metadata.update({"covered_periods": periods, "latest_period": periods[-1] if periods else None, "last_successful_refresh_date": successful, "last_refresh_date": successful, "record_count": int(len(income)), "conflict_count": len(conflicts), "stock_metadata_conflicts": stock_metadata_conflicts if stock_metadata_conflicts is not None else metadata.get("stock_metadata_conflicts", []), "refresh_error": refresh_error if refresh_error is not None else metadata.get("refresh_error")})
    return metadata


def cache_payload(income: pd.DataFrame, stocks: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, stock_metadata_conflicts: list[dict[str, Any]] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = income.drop(columns=[column for column in income.columns if column.startswith("_")], errors="ignore")
    return {"schema_version": 2, "source": SOURCE, "metadata": cache_metadata(income, conflicts, refreshed_at, stock_metadata_conflicts, existing=metadata), "income_records": rows.to_dict(orient="records"), "stock_records": stocks.to_dict(orient="records"), "conflicts": conflicts}


def load_cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") not in (1, 2):
        raise ValueError("unsupported cycle earnings cache schema")
    return payload


def load_cache(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]] | None:
    payload = load_cache_payload(path)
    if payload is None:
        return None
    income = normalise_income(pd.DataFrame(payload.get("income_records", [])))
    return income, normalise_stocks(pd.DataFrame(payload.get("stock_records", []))), source_conflicts(income)


def load_cache_metadata(path: Path) -> dict[str, Any]:
    payload = load_cache_payload(path)
    if payload is None:
        return cache_metadata(pd.DataFrame(columns=["end_date"]), [], None)
    income = normalise_income(pd.DataFrame(payload.get("income_records", [])))
    return cache_metadata(income, source_conflicts(income), existing=payload.get("metadata", {}))


def fetch_income_periods(pro: Any, periods: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for period in periods:
        frame = pro.income_vip(period=period, fields="ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,n_income_attr_p,update_flag")
        if not frame.empty:
            frames.append(frame)
    return normalise_income(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())


def fetch_stocks(pro: Any) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for status in ("L", "D", "P"):
        frame = pro.stock_basic(exchange="", list_status=status, fields="ts_code,list_date,delist_date")
        if not frame.empty:
            frames.append(frame)
    return normalise_stocks(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())


def fetch_source(pro: Any, start_year: int, end_year: int) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    income = fetch_income_periods(pro, quarter_ends(start_year, end_year))
    stocks = fetch_stocks(pro)
    return income, stocks, source_conflicts(income)


def append_income(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    columns = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "n_income_attr_p", "update_flag"]
    combined = pd.concat([existing.reindex(columns=columns), fresh.reindex(columns=columns)], ignore_index=True).drop_duplicates(columns, keep="first")
    return normalise_income(combined)


def append_stocks(existing: pd.DataFrame, fresh: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Append new listings and only enrich blank delist dates for existing codes."""
    existing_by_code = existing.set_index("ts_code").to_dict(orient="index")
    rows, conflicts = [], []
    for row in fresh.to_dict(orient="records"):
        code = row["ts_code"]
        old = existing_by_code.get(code)
        if old is None:
            existing_by_code[code] = row
            continue
        if old["list_date"] and row["list_date"] and old["list_date"] != row["list_date"]:
            conflicts.append({"ts_code": code, "field": "list_date", "cached": old["list_date"], "incoming": row["list_date"]})
        if not old["delist_date"] and row["delist_date"]:
            old["delist_date"] = row["delist_date"]
        elif old["delist_date"] and row["delist_date"] and old["delist_date"] != row["delist_date"]:
            conflicts.append({"ts_code": code, "field": "delist_date", "cached": old["delist_date"], "incoming": row["delist_date"]})
    return normalise_stocks(pd.DataFrame([{"ts_code": code, **row} for code, row in existing_by_code.items()])), conflicts


def source_from_cache_or_api_status(pro: Any, cache_path: Path, start_year: int, end_year: int, as_of: date | None = None, refresh: bool = True, refresh_date: date | None = None) -> tuple[pd.DataFrame | None, pd.DataFrame | None, list[dict[str, Any]], dict[str, Any], str | None]:
    as_of = as_of or date(end_year, 12, 31)
    expected_periods = [period for period in quarter_ends(start_year, end_year) if period_date(period) <= as_of]
    payload = load_cache_payload(cache_path)
    cached = load_cache(cache_path)
    cached_metadata = dict((payload or {}).get("metadata", {}))
    if cached is None:
        try:
            income, stocks, conflicts = fetch_source(pro, start_year, end_year)
        except Exception as exc:
            return None, None, [{"source_error": str(exc)}], cache_metadata(pd.DataFrame(columns=["end_date"]), [], None), str(exc)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_payload(income, stocks, conflicts, refresh_date or date.today()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return income, stocks, conflicts, load_cache_metadata(cache_path), None
    if not refresh:
        # An explicit offline read must not claim a source refresh or touch metadata.
        income, stocks, conflicts = cached
        return income, stocks, conflicts, load_cache_metadata(cache_path), None
    income, stocks, _ = cached
    try:
        missing = [period for period in expected_periods if period not in set(income["end_date"].astype(str))]
        newest = expected_periods[-1:] if expected_periods else []
        income = append_income(income, fetch_income_periods(pro, sorted(set(missing + newest))))
        stocks, stock_conflicts = append_stocks(stocks, fetch_stocks(pro))
        conflicts = source_conflicts(income)
    except Exception as exc:
        # A failed refresh is a run-level status, never a destructive cache write.
        cached_income, cached_stocks, cached_conflicts = cached
        return cached_income, cached_stocks, cached_conflicts, load_cache_metadata(cache_path), str(exc)
    prior_stock_conflicts = cached_metadata.get("stock_metadata_conflicts", [])
    all_stock_conflicts = prior_stock_conflicts + [item for item in stock_conflicts if item not in prior_stock_conflicts]
    cache_path.write_text(json.dumps(cache_payload(income, stocks, conflicts, refresh_date or date.today(), all_stock_conflicts, cached_metadata), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return income, stocks, conflicts, load_cache_metadata(cache_path), None


def source_from_cache_or_api(pro: Any, cache_path: Path, start_year: int, end_year: int, as_of: date | None = None, refresh: bool = True, refresh_date: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    income, stocks, conflicts, _, error = source_from_cache_or_api_status(pro, cache_path, start_year, end_year, as_of, refresh, refresh_date)
    if error and income is None:
        raise RuntimeError(error)
    assert income is not None and stocks is not None
    return income, stocks, conflicts


def eligible_universe(stocks: pd.DataFrame, report_period: str) -> set[str]:
    end = period_date(report_period).strftime("%Y%m%d")
    valid = stocks.loc[(stocks["list_date"] <= end) & ((stocks["delist_date"] == "") | (stocks["delist_date"] > end))]
    return set(valid["ts_code"])


def prepare_income_by_period(income: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {str(period): group.reset_index(drop=True) for period, group in income.groupby("end_date", sort=False)}


def latest_visible_version(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    visible = frame.loc[(frame["_effective_ann"] <= basis) & ~frame["_ambiguous_source_conflict"]].copy()
    return visible.sort_values(["ts_code", "report_type", "_effective_ann_str", "update_flag", "n_income_attr_p"], kind="stable") if not visible.empty else visible


def select_current_statement(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    return latest_visible_version(frame, basis).loc[lambda rows: rows["report_type"] == CURRENT_REPORT_TYPE].drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def select_prior_comparable_statement(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    visible, selected = latest_visible_version(frame, basis), []
    remaining = set(visible["ts_code"])
    for report_type in PRIOR_REPORT_TYPES:
        candidates = visible.loc[(visible["report_type"] == report_type) & visible["ts_code"].isin(remaining)].drop_duplicates("ts_code", keep="last")
        selected.append(candidates)
        remaining -= set(candidates["ts_code"])
    return pd.concat(selected, ignore_index=True) if selected else visible.iloc[0:0].copy()


def visible_deduped(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    return select_current_statement(frame, basis)


def aggregate_side(current: pd.DataFrame, prior: pd.DataFrame, universe: set[str], nonfinancial: bool, basis: date, current_period: str) -> dict[str, Any]:
    current_all, prior_all = current.loc[current["ts_code"].isin(universe)].copy(), prior.loc[prior["ts_code"].isin(universe)].copy()
    classified_codes = set(current_all.loc[current_all["comp_type"] != "", "ts_code"])
    nonfinancial_universe = set(current_all.loc[current_all["comp_type"] == "1", "ts_code"])
    if nonfinancial:
        current, prior, eligible_count = current_all.loc[current_all["ts_code"].isin(nonfinancial_universe)].copy(), prior_all.loc[prior_all["ts_code"].isin(nonfinancial_universe)].copy(), len(nonfinancial_universe)
    else:
        current, prior, eligible_count = current_all, prior_all, len(universe)
    current_by_code, prior_by_code = current.set_index("ts_code")["n_income_attr_p"], prior.set_index("ts_code")["n_income_attr_p"]
    matched = sorted(set(current_by_code.index) & set(prior_by_code.index))
    current_coverage = len(current_by_code) / eligible_count if eligible_count else 0.0
    matched_coverage = len(matched) / eligible_count if eligible_count else 0.0
    current_profit = float(current_by_code.loc[matched].sum()) if matched else None
    prior_profit = float(prior_by_code.loc[matched].sum()) if matched else None
    latest_ann = current.loc[current["ts_code"].isin(matched), "_effective_ann"].max() if matched else None
    latest_ann = None if pd.isna(latest_ann) else latest_ann
    reason, yoy = None, None
    if current_coverage < MIN_CURRENT_COVERAGE:
        reason = f"current period coverage below {MIN_CURRENT_COVERAGE:.0%}"
    elif matched_coverage < MIN_MATCHED_COVERAGE:
        reason = f"matched coverage below {MIN_MATCHED_COVERAGE:.0%}"
    elif prior_profit is None or prior_profit <= 0:
        reason = "non-positive aggregate prior-year profit"
    elif current_profit is not None:
        yoy = (current_profit / prior_profit - 1) * 100
    used_prior_types = sorted(set(prior.loc[prior["ts_code"].isin(matched), "report_type"])) if matched else []
    return {"value": round(yoy, 4) if yoy is not None else None, "observation_date": None, "announcement_date": iso(latest_ann), "source": SOURCE, "lag_days": (basis - latest_ann).days if latest_ann else None, "available": yoy is not None and latest_ann is not None and latest_ann <= basis, "pit_safe": latest_ann <= basis if latest_ann else False, "reason": reason, "current_aggregate_profit": round(current_profit, 2) if current_profit is not None else None, "prior_aggregate_profit": round(prior_profit, 2) if prior_profit is not None else None, "matched_stock_count": len(matched), "eligible_stock_count": eligible_count, "all_a_eligible_stock_count": len(universe), "classified_nonfinancial_eligible_stock_count": len(nonfinancial_universe), "unknown_comp_type_count": len(universe - classified_codes), "current_period_coverage_rate": round(current_coverage * 100, 4), "matched_coverage_rate": round(matched_coverage * 100, 4), "report_period": current_period, "prior_year_report_period": prior_year_period(current_period), "current_statement_report_type": CURRENT_REPORT_TYPE, "prior_comparator_report_types": list(PRIOR_REPORT_TYPES), "prior_comparator_report_types_used": used_prior_types, "classification_coverage_rate": round(len(classified_codes) / len(universe) * 100, 4) if universe else 0.0}


def profit_growth_snapshot(income_by_period: dict[str, pd.DataFrame], stocks: pd.DataFrame, basis: date) -> dict[str, Any]:
    for period in [item for item in sorted(income_by_period, reverse=True) if period_date(item) <= basis]:
        prior_period = prior_year_period(period)
        if prior_period not in income_by_period:
            continue
        universe, current = eligible_universe(stocks, period), select_current_statement(income_by_period[period], basis)
        if (len(current.loc[current["ts_code"].isin(universe)]) / len(universe) if universe else 0.0) < MIN_CURRENT_COVERAGE:
            continue
        prior = select_prior_comparable_statement(income_by_period[prior_period], basis)
        return {"all_a": aggregate_side(current, prior, universe, False, basis, period), "nonfinancial_a": aggregate_side(current, prior, universe, True, basis, period)}
    reason = "no quarterly report period reached current coverage threshold"
    unavailable = {"value": None, "observation_date": None, "announcement_date": None, "source": SOURCE, "lag_days": None, "available": False, "pit_safe": False, "reason": reason, "current_aggregate_profit": None, "prior_aggregate_profit": None, "matched_stock_count": 0, "eligible_stock_count": 0, "all_a_eligible_stock_count": 0, "classified_nonfinancial_eligible_stock_count": 0, "unknown_comp_type_count": 0, "current_period_coverage_rate": 0.0, "matched_coverage_rate": 0.0, "report_period": None, "prior_year_report_period": None, "current_statement_report_type": None, "prior_comparator_report_types": [], "prior_comparator_report_types_used": [], "classification_coverage_rate": 0.0}
    return {"all_a": unavailable, "nonfinancial_a": dict(unavailable)}
