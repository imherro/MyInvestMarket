from __future__ import annotations

"""Point-in-time, aggregate market ROE(TTM) for Cycle Dataset v1."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

import cycle_earnings


SOURCE = "Tushare.balancesheet_vip"
EQUITY_FIELD = "total_hldr_eqy_exc_min_int"
MIN_MATCHED_COVERAGE = cycle_earnings.MIN_MATCHED_COVERAGE


def normalise_balance(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", EQUITY_FIELD, "update_flag"]
    result = frame.reindex(columns=columns).copy()
    for column in ("ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", "update_flag"):
        result[column] = result[column].fillna("").astype(str)
    result[EQUITY_FIELD] = pd.to_numeric(result[EQUITY_FIELD], errors="coerce")
    announced = pd.to_datetime(result["ann_date"], errors="coerce")
    final_announced = pd.to_datetime(result["f_ann_date"], errors="coerce")
    result["_effective_ann"] = final_announced.fillna(announced).dt.date
    result = result.dropna(subset=["_effective_ann", EQUITY_FIELD])
    result = result.loc[(result["ts_code"] != "") & (result["end_date"] != "")].copy()
    result["_effective_ann_str"] = result["_effective_ann"].map(lambda value: value.strftime("%Y%m%d"))
    identity = ["ts_code", "end_date", "report_type", "_effective_ann_str", "update_flag"]
    result["_ambiguous_source_conflict"] = result.groupby(identity)[EQUITY_FIELD].transform("nunique").gt(1)
    return result.sort_values(["end_date", "ts_code", "report_type", "_effective_ann_str", "update_flag", EQUITY_FIELD], kind="stable").reset_index(drop=True)


def source_conflicts(balance: pd.DataFrame) -> list[dict[str, Any]]:
    identity = ["ts_code", "end_date", "report_type", "_effective_ann_str", "update_flag"]
    conflicts: list[dict[str, Any]] = []
    for keys, group in balance.groupby(identity, dropna=False, sort=True):
        values = sorted(float(value) for value in group[EQUITY_FIELD].dropna().unique())
        if len(values) > 1:
            conflicts.append({"identity": dict(zip(identity, keys)), "value_count": len(values), "values": values})
    return conflicts


def cache_metadata(balance: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    periods = sorted(set(balance["end_date"].astype(str))) if not balance.empty else []
    metadata = dict(existing or {})
    successful = cycle_earnings.iso(refreshed_at) if refreshed_at else metadata.get("last_successful_refresh_date") or metadata.get("last_refresh_date")
    metadata.update({"covered_periods": periods, "latest_period": periods[-1] if periods else None, "last_successful_refresh_date": successful, "last_refresh_date": successful, "record_count": int(len(balance)), "conflict_count": len(conflicts), "refresh_error": metadata.get("refresh_error")})
    return metadata


def cache_payload(balance: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = balance.drop(columns=[column for column in balance.columns if column.startswith("_")], errors="ignore")
    return {"schema_version": 1, "source": SOURCE, "equity_field": EQUITY_FIELD, "metadata": cache_metadata(balance, conflicts, refreshed_at, metadata), "balance_records": rows.to_dict(orient="records"), "conflicts": conflicts}


def load_cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1 or payload.get("equity_field") != EQUITY_FIELD:
        raise ValueError("unsupported cycle ROE balance-sheet cache schema")
    return payload


def load_cache(path: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]] | None:
    payload = load_cache_payload(path)
    if payload is None:
        return None
    balance = normalise_balance(pd.DataFrame(payload.get("balance_records", [])))
    return balance, source_conflicts(balance)


def load_cache_metadata(path: Path) -> dict[str, Any]:
    payload = load_cache_payload(path)
    if payload is None:
        return cache_metadata(pd.DataFrame(columns=["end_date"]), [], None)
    balance = normalise_balance(pd.DataFrame(payload.get("balance_records", [])))
    return cache_metadata(balance, source_conflicts(balance), existing=payload.get("metadata", {}))


def fetch_balance_periods(pro: Any, periods: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    fields = f"ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,{EQUITY_FIELD},update_flag"
    for period in periods:
        frame = pro.balancesheet_vip(period=period, fields=fields)
        if not frame.empty:
            frames.append(frame)
    return normalise_balance(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())


def append_balance(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    columns = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type", EQUITY_FIELD, "update_flag"]
    combined = pd.concat([existing.reindex(columns=columns), fresh.reindex(columns=columns)], ignore_index=True).drop_duplicates(columns, keep="first")
    return normalise_balance(combined)


def source_from_cache_or_api_status(pro: Any, cache_path: Path, start_year: int, end_year: int, as_of: date, refresh: bool = True, refresh_date: date | None = None) -> tuple[pd.DataFrame | None, list[dict[str, Any]], dict[str, Any], str | None]:
    expected = [period for period in cycle_earnings.quarter_ends(start_year, end_year) if cycle_earnings.period_date(period) <= as_of]
    payload, cached = load_cache_payload(cache_path), load_cache(cache_path)
    existing_metadata = dict((payload or {}).get("metadata", {}))
    if cached is None:
        try:
            balance = fetch_balance_periods(pro, expected)
        except Exception as exc:
            return None, [{"source_error": str(exc)}], cache_metadata(pd.DataFrame(columns=["end_date"]), [], None), str(exc)
        conflicts = source_conflicts(balance)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_payload(balance, conflicts, refresh_date or date.today()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return balance, conflicts, load_cache_metadata(cache_path), None
    balance, cached_conflicts = cached
    if not refresh:
        return balance, cached_conflicts, load_cache_metadata(cache_path), None
    try:
        missing = [period for period in expected if period not in set(balance["end_date"].astype(str))]
        newest = expected[-1:] if expected else []
        balance = append_balance(balance, fetch_balance_periods(pro, sorted(set(missing + newest))))
        conflicts = source_conflicts(balance)
    except Exception as exc:
        return balance, cached_conflicts, load_cache_metadata(cache_path), str(exc)
    cache_path.write_text(json.dumps(cache_payload(balance, conflicts, refresh_date or date.today(), existing_metadata), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return balance, conflicts, load_cache_metadata(cache_path), None


def audit_cache_freshness(balance: pd.DataFrame, metadata: dict[str, Any], as_of: date, refresh_error: str | None = None) -> dict[str, Any]:
    # Balance sheets follow the same statutory quarterly deadline contract as income.
    return cycle_earnings.audit_cache_freshness(balance, metadata, as_of, 2008, refresh_error)


def prepare_balance_by_period(balance: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {str(period): group.reset_index(drop=True) for period, group in balance.groupby("end_date", sort=False)}


def latest_visible_version(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    visible = frame.loc[(frame["_effective_ann"] <= basis) & ~frame["_ambiguous_source_conflict"]].copy()
    return visible.sort_values(["ts_code", "report_type", "_effective_ann_str", "update_flag", EQUITY_FIELD], kind="stable") if not visible.empty else visible


def select_current_statement(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    return latest_visible_version(frame, basis).loc[lambda rows: rows["report_type"] == cycle_earnings.CURRENT_REPORT_TYPE].drop_duplicates("ts_code", keep="last").reset_index(drop=True)


def select_prior_comparable_statement(frame: pd.DataFrame, basis: date) -> pd.DataFrame:
    visible, selected = latest_visible_version(frame, basis), []
    remaining = set(visible["ts_code"])
    for report_type in cycle_earnings.PRIOR_REPORT_TYPES:
        candidates = visible.loc[(visible["report_type"] == report_type) & visible["ts_code"].isin(remaining)].drop_duplicates("ts_code", keep="last")
        selected.append(candidates)
        remaining -= set(candidates["ts_code"])
    return pd.concat(selected, ignore_index=True) if selected else visible.iloc[0:0].copy()


def ttm_profit_by_code(income_by_period: dict[str, pd.DataFrame], report_period: str, basis: date) -> tuple[pd.Series, dict[str, pd.DataFrame]]:
    year, suffix = int(report_period[:4]), report_period[4:]
    required = [report_period] if suffix == "1231" else [report_period, f"{year - 1}1231", f"{year - 1}{suffix}"]
    if any(period not in income_by_period for period in required):
        return pd.Series(dtype=float), {}
    statements = {period: cycle_earnings.select_current_statement(income_by_period[period], basis).set_index("ts_code") for period in required}
    codes = set.intersection(*(set(frame.index) for frame in statements.values())) if statements else set()
    if not codes:
        return pd.Series(dtype=float), statements
    current = statements[report_period].loc[sorted(codes), "n_income_attr_p"]
    if suffix == "1231":
        return current, statements
    return current + statements[f"{year - 1}1231"].loc[sorted(codes), "n_income_attr_p"] - statements[f"{year - 1}{suffix}"].loc[sorted(codes), "n_income_attr_p"], statements


def _unavailable(basis: date, report_period: str | None, reason: str) -> dict[str, Any]:
    return {"value": None, "observation_date": None, "announcement_date": None, "source": f"derived:{cycle_earnings.SOURCE},{SOURCE}", "lag_days": None, "available": False, "pit_safe": False, "report_period": report_period, "ttm_parent_profit": None, "current_parent_equity": None, "prior_year_parent_equity": None, "average_parent_equity": None, "eligible_stock_count": 0, "matched_stock_count": 0, "all_a_eligible_stock_count": 0, "classified_nonfinancial_eligible_stock_count": 0, "unknown_comp_type_count": 0, "matched_coverage_rate": 0.0, "current_equity_coverage_rate": 0.0, "prior_equity_coverage_rate": 0.0, "classification_coverage_rate": 0.0, "current_statement_report_type": None, "prior_equity_report_types_used": [], "reason": reason}


def roe_snapshot(income_by_period: dict[str, pd.DataFrame], balance_by_period: dict[str, pd.DataFrame], stocks: pd.DataFrame, basis: date, report_period: str | None) -> dict[str, Any]:
    if not report_period:
        unavailable = _unavailable(basis, None, "no Cycle earnings report period available")
        return {"all_a": unavailable, "nonfinancial_a": dict(unavailable)}
    prior_period = cycle_earnings.prior_year_period(report_period)
    if report_period not in balance_by_period or prior_period not in balance_by_period:
        unavailable = _unavailable(basis, report_period, "required balance-sheet report period unavailable")
        return {"all_a": unavailable, "nonfinancial_a": dict(unavailable)}
    ttm, profit_statements = ttm_profit_by_code(income_by_period, report_period, basis)
    if ttm.empty:
        unavailable = _unavailable(basis, report_period, "required TTM income statements unavailable at basis")
        return {"all_a": unavailable, "nonfinancial_a": dict(unavailable)}
    current_equity = select_current_statement(balance_by_period[report_period], basis).set_index("ts_code")
    prior_equity = select_prior_comparable_statement(balance_by_period[prior_period], basis).set_index("ts_code")
    universe = cycle_earnings.eligible_universe(stocks, report_period)
    current_profit = profit_statements[report_period]
    # Classification is deliberately applied after the historical all-A
    # universe is fixed. A later IPO can have backfilled statements in the
    # source, but must not enter a pre-listing Cycle observation.
    classified = set(current_profit.loc[current_profit["comp_type"] != ""].index) & universe
    nonfinancial_universe = set(current_profit.loc[current_profit["comp_type"] == "1"].index) & universe
    unknown_comp_type_count = len(universe - classified)

    def aggregate(nonfinancial: bool) -> dict[str, Any]:
        eligible = nonfinancial_universe if nonfinancial else universe
        valid_codes = sorted(set(ttm.index) & set(current_equity.index) & set(prior_equity.index) & set(eligible))
        current_eq_codes = set(current_equity.index) & set(eligible)
        prior_eq_codes = set(prior_equity.index) & set(eligible)
        coverage = len(valid_codes) / len(eligible) if eligible else 0.0
        profit = float(ttm.loc[valid_codes].sum()) if valid_codes else None
        current_total = float(current_equity.loc[valid_codes, EQUITY_FIELD].sum()) if valid_codes else None
        prior_total = float(prior_equity.loc[valid_codes, EQUITY_FIELD].sum()) if valid_codes else None
        average = (current_total + prior_total) / 2 if current_total is not None and prior_total is not None else None
        announcements = []
        for statement in profit_statements.values():
            dates = statement.loc[statement.index.intersection(valid_codes), "_effective_ann"]
            if not dates.empty:
                announcements.append(dates.max())
        for statement in (current_equity, prior_equity):
            dates = statement.loc[statement.index.intersection(valid_codes), "_effective_ann"]
            if not dates.empty:
                announcements.append(dates.max())
        latest_ann = max(announcements) if announcements else None
        reason, value = None, None
        if coverage < MIN_MATCHED_COVERAGE:
            reason = f"matched coverage below {MIN_MATCHED_COVERAGE:.0%}"
        elif average is None or average <= 0:
            reason = "non-positive aggregate average equity"
        else:
            value = profit / average * 100
        return {"value": round(value, 4) if value is not None else None, "observation_date": None, "announcement_date": cycle_earnings.iso(latest_ann), "source": f"derived:{cycle_earnings.SOURCE},{SOURCE}", "lag_days": (basis - latest_ann).days if latest_ann else None, "available": value is not None and latest_ann is not None and latest_ann <= basis, "pit_safe": latest_ann <= basis if latest_ann else False, "report_period": report_period, "ttm_parent_profit": round(profit, 2) if profit is not None else None, "current_parent_equity": round(current_total, 2) if current_total is not None else None, "prior_year_parent_equity": round(prior_total, 2) if prior_total is not None else None, "average_parent_equity": round(average, 2) if average is not None else None, "eligible_stock_count": len(eligible), "matched_stock_count": len(valid_codes), "all_a_eligible_stock_count": len(universe), "classified_nonfinancial_eligible_stock_count": len(nonfinancial_universe), "unknown_comp_type_count": unknown_comp_type_count, "matched_coverage_rate": round(coverage * 100, 4), "current_equity_coverage_rate": round(len(current_eq_codes) / len(eligible) * 100, 4) if eligible else 0.0, "prior_equity_coverage_rate": round(len(prior_eq_codes) / len(eligible) * 100, 4) if eligible else 0.0, "classification_coverage_rate": round(len(classified) / len(universe) * 100, 4) if universe else 0.0, "current_statement_report_type": cycle_earnings.CURRENT_REPORT_TYPE, "prior_equity_report_types_used": sorted(set(prior_equity.loc[prior_equity.index.intersection(valid_codes), "report_type"])), "reason": reason}

    return {"all_a": aggregate(False), "nonfinancial_a": aggregate(True)}
