from __future__ import annotations

"""Point-in-time ChinaBond 10-year government yield source for Cycle Dataset."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd


SOURCE = "ChinaBond via AKShare.bond_china_yield"
CURVE_NAME = "\u4e2d\u503a\u56fd\u503a\u6536\u76ca\u7387\u66f2\u7ebf"
DATE_COLUMN = "\u65e5\u671f"
CURVE_COLUMN = "\u66f2\u7ebf\u540d\u79f0"
TEN_YEAR_COLUMN = "10\u5e74"
MAX_STALENESS_DAYS = 10
CHUNK_DAYS = 180


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def normalise_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """Retain only the formal ChinaBond government 10-year series."""
    if frame.empty:
        return pd.DataFrame(columns=["observation_date", "curve_name", "yield_10y_pct", "source", "_observation_date_str", "_ambiguous_source_conflict"])
    if "observation_date" in frame.columns:
        result = frame.reindex(columns=["observation_date", "curve_name", "yield_10y_pct", "source"]).copy()
    else:
        result = pd.DataFrame({
            "observation_date": frame.get(DATE_COLUMN),
            "curve_name": frame.get(CURVE_COLUMN),
            "yield_10y_pct": frame.get(TEN_YEAR_COLUMN),
            "source": SOURCE,
        })
    result["observation_date"] = result["observation_date"].map(parse_date)
    result["curve_name"] = result["curve_name"].fillna("").astype(str)
    result["yield_10y_pct"] = pd.to_numeric(result["yield_10y_pct"], errors="coerce")
    result["source"] = result["source"].fillna(SOURCE).astype(str)
    result = result.loc[(result["curve_name"] == CURVE_NAME) & result["observation_date"].notna() & result["yield_10y_pct"].notna()].copy()
    result["_observation_date_str"] = result["observation_date"].map(lambda value: value.strftime("%Y%m%d"))
    identity = ["_observation_date_str", "curve_name"]
    result["_ambiguous_source_conflict"] = result.groupby(identity)["yield_10y_pct"].transform("nunique").gt(1)
    return result.sort_values(["_observation_date_str", "curve_name", "yield_10y_pct"], kind="stable").reset_index(drop=True)


def source_conflicts(rates: pd.DataFrame) -> list[dict[str, Any]]:
    identity = ["_observation_date_str", "curve_name"]
    conflicts: list[dict[str, Any]] = []
    for keys, group in rates.groupby(identity, dropna=False, sort=True):
        values = sorted(float(value) for value in group["yield_10y_pct"].dropna().unique())
        if len(values) > 1:
            conflicts.append({"identity": {"observation_date": f"{keys[0][:4]}-{keys[0][4:6]}-{keys[0][6:]}", "curve_name": keys[1]}, "value_count": len(values), "values": values})
    return conflicts


def cache_metadata(rates: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, refresh_error: str | None = None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(existing or {})
    dates = sorted(set(rates["_observation_date_str"].astype(str))) if not rates.empty else []
    successful = iso(refreshed_at) if refreshed_at else metadata.get("last_successful_refresh_date") or metadata.get("last_refresh_date")
    metadata.update({
        "first_observation_date": f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}" if dates else None,
        "latest_observation_date": f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}" if dates else None,
        "record_count": int(len(rates)),
        "last_successful_refresh_date": successful,
        "last_refresh_date": successful,
        "conflict_count": len(conflicts),
        "refresh_error": refresh_error,
    })
    return metadata


def cache_payload(rates: pd.DataFrame, conflicts: list[dict[str, Any]], refreshed_at: date | None = None, metadata: dict[str, Any] | None = None, refresh_error: str | None = None) -> dict[str, Any]:
    rows = rates.drop(columns=[column for column in rates.columns if column.startswith("_")], errors="ignore")
    return {"schema_version": 1, "source": SOURCE, "curve_name": CURVE_NAME, "metadata": cache_metadata(rates, conflicts, refreshed_at, refresh_error, metadata), "rate_records": rows.assign(observation_date=rows["observation_date"].map(iso)).to_dict(orient="records"), "conflicts": conflicts}


def load_cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1 or payload.get("source") != SOURCE or payload.get("curve_name") != CURVE_NAME:
        raise ValueError("unsupported China 10Y source cache schema")
    return payload


def load_cache(path: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]] | None:
    payload = load_cache_payload(path)
    if payload is None:
        return None
    rates = normalise_rates(pd.DataFrame(payload.get("rate_records", [])))
    return rates, source_conflicts(rates)


def load_cache_metadata(path: Path) -> dict[str, Any]:
    payload = load_cache_payload(path)
    if payload is None:
        return cache_metadata(pd.DataFrame(columns=["observation_date", "curve_name", "yield_10y_pct", "source"]), [], None)
    rates = normalise_rates(pd.DataFrame(payload.get("rate_records", [])))
    return cache_metadata(rates, source_conflicts(rates), existing=payload.get("metadata", {}))


def date_windows(start: date, end: date, chunk_days: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        terminal = min(current + timedelta(days=chunk_days - 1), end)
        windows.append((current, terminal))
        current = terminal + timedelta(days=1)
    return windows


def akshare_bond_china_yield(start: date, end: date) -> pd.DataFrame:
    """Use AKShare's official adapter, correcting its current UTF-8 response detection."""
    try:
        import akshare as ak
        import akshare.bond.bond_china as bond_china
    except ImportError as exc:
        raise RuntimeError("AKShare is required for ChinaBond 10Y history; install akshare") from exc
    original_get = bond_china.requests.get

    def utf8_get(*args: Any, **kwargs: Any) -> Any:
        response = original_get(*args, **kwargs)
        response.encoding = "utf-8"
        return response

    bond_china.requests.get = utf8_get
    try:
        return ak.bond_china_yield(start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    finally:
        bond_china.requests.get = original_get


def fetch_rates(start: date, end: date, fetcher: Callable[[date, date], pd.DataFrame] = akshare_bond_china_yield) -> pd.DataFrame:
    frames = [fetcher(window_start, window_end) for window_start, window_end in date_windows(start, end)]
    return normalise_rates(pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if any(not frame.empty for frame in frames) else pd.DataFrame())


def append_rates(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    columns = ["observation_date", "curve_name", "yield_10y_pct", "source"]
    combined = pd.concat([existing.reindex(columns=columns), fresh.reindex(columns=columns)], ignore_index=True).drop_duplicates(columns, keep="first")
    return normalise_rates(combined)


def source_from_cache_or_api_status(cache_path: Path, start: date, as_of: date, refresh: bool = True, refresh_date: date | None = None, fetcher: Callable[[date, date], pd.DataFrame] = akshare_bond_china_yield) -> tuple[pd.DataFrame | None, list[dict[str, Any]], dict[str, Any], str | None]:
    payload, cached = load_cache_payload(cache_path), load_cache(cache_path)
    existing_metadata = dict((payload or {}).get("metadata", {}))
    if cached is None:
        try:
            rates = fetch_rates(start, as_of, fetcher)
        except Exception as exc:
            return None, [{"source_error": str(exc)}], cache_metadata(pd.DataFrame(columns=["observation_date", "curve_name", "yield_10y_pct", "source"]), [], None), str(exc)
        conflicts = source_conflicts(rates)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_payload(rates, conflicts, refresh_date or date.today()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return rates, conflicts, load_cache_metadata(cache_path), None
    rates, cached_conflicts = cached
    if not refresh:
        return rates, cached_conflicts, load_cache_metadata(cache_path), None
    try:
        latest = parse_date(existing_metadata.get("latest_observation_date"))
        refresh_start = max(start, (latest - timedelta(days=MAX_STALENESS_DAYS)) if latest else start)
        rates = append_rates(rates, fetch_rates(refresh_start, as_of, fetcher))
        conflicts = source_conflicts(rates)
    except Exception as exc:
        return rates, cached_conflicts, load_cache_metadata(cache_path), str(exc)
    cache_path.write_text(json.dumps(cache_payload(rates, conflicts, refresh_date or date.today(), existing_metadata), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rates, conflicts, load_cache_metadata(cache_path), None


def snapshot(rates: pd.DataFrame | None, basis: date, refresh_error: str | None = None) -> dict[str, Any]:
    base = {"source": SOURCE, "curve_name": CURVE_NAME, "observation_date": None, "lag_days": None, "available": False, "pit_safe": False, "value": None, "reason": refresh_error}
    if rates is None:
        base["reason"] = refresh_error or "China 10Y source unavailable"
        return base
    visible = rates.loc[(rates["observation_date"] <= basis) & ~rates["_ambiguous_source_conflict"]].copy()
    if visible.empty:
        base["reason"] = refresh_error or "no China 10Y observation at or before basis trade date"
        return base
    row = visible.sort_values("observation_date", kind="stable").iloc[-1]
    observation = row["observation_date"]
    lag_days = (basis - observation).days
    base.update({"observation_date": iso(observation), "lag_days": lag_days, "pit_safe": True})
    if lag_days > MAX_STALENESS_DAYS:
        base["reason"] = "China 10Y observation too stale"
        return base
    base.update({"value": round(float(row["yield_10y_pct"]), 4), "available": True, "reason": None})
    return base


def source_validation(rates: pd.DataFrame | None) -> dict[str, Any]:
    if rates is None or rates.empty:
        return {"first_observation_date": None, "latest_observation_date": None, "record_count": 0, "post_2010_record_count": 0, "range_warning_count": 0, "sample": []}
    clean = rates.loc[~rates["_ambiguous_source_conflict"]].copy()
    samples = clean.sample(n=min(20, len(clean)), random_state=20260901).sort_values("observation_date")
    return {
        "first_observation_date": iso(clean["observation_date"].min()),
        "latest_observation_date": iso(clean["observation_date"].max()),
        "record_count": int(len(clean)),
        "post_2010_record_count": int((clean["observation_date"] >= date(2010, 1, 1)).sum()),
        "range_warning_count": int(((clean["yield_10y_pct"] <= 0) | (clean["yield_10y_pct"] >= 10)).sum()),
        "sample": [{"observation_date": iso(row.observation_date), "yield_10y_pct": round(float(row.yield_10y_pct), 4)} for row in samples.itertuples()],
    }
