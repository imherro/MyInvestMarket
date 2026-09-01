from __future__ import annotations

"""Point-in-time official manufacturing PMI source for the Cycle dataset."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd


VALUE_SOURCE = "Tushare.cn_pmi"
SCHEDULE_SOURCE = "Tushare.cn_schedule"
FALLBACK_SOURCE = "AKShare.macro_china_pmi_yearly"
FIELD_MONTH = "month"
FIELD_VALUE = "pmi010000"
RELEASE_MATCH_TOLERANCE = 0.05
RELEASE_WINDOW_START_DAY = 20
RELEASE_WINDOW_END_DAYS = 10


def parse_date(value: Any) -> date | None:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def parse_month(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("-", "")[:6]
    if len(text) != 6 or not text.isdigit():
        return None
    try:
        datetime.strptime(text, "%Y%m")
    except ValueError:
        return None
    return f"{text[:4]}-{text[4:]}"


def month_date(month: str) -> date:
    return datetime.strptime(month, "%Y-%m").date()


def next_month(month: str) -> date:
    value = month_date(month)
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def release_window(month: str) -> tuple[date, date]:
    start = month_date(month).replace(day=RELEASE_WINDOW_START_DAY)
    return start, next_month(month) + timedelta(days=RELEASE_WINDOW_END_DAYS)


def normalise_tushare(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if frame.empty:
        return [], []
    month_column = next((column for column in frame.columns if str(column).lower() == "month"), None)
    value_column = next((column for column in frame.columns if str(column).lower() == FIELD_VALUE), None)
    if month_column is None or value_column is None:
        raise ValueError("Tushare.cn_pmi response lacks month or pmi010000")
    rows = []
    for row in frame[[month_column, value_column]].itertuples(index=False):
        month = parse_month(row[0])
        value = pd.to_numeric(pd.Series([row[1]]), errors="coerce").iloc[0]
        if month and pd.notna(value):
            rows.append({"data_month": month, "pmi": round(float(value), 4), "value_source": VALUE_SOURCE})
    rows.sort(key=lambda item: item["data_month"])
    conflicts = []
    for month, group in pd.DataFrame(rows).groupby("data_month") if rows else []:
        values = sorted(set(float(value) for value in group["pmi"]))
        if len(values) > 1:
            conflicts.append({"identity": {"data_month": month}, "values": values})
    return rows, conflicts


def normalise_schedule(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    def column(name: str) -> str | None:
        return next((item for item in frame.columns if str(item).lower() == name), None)
    month_column = column("month")
    publish_column = column("publish_date")
    api_column = column("data_api")
    if month_column is None or publish_column is None or api_column is None:
        return []
    rows = []
    for row in frame.to_dict("records"):
        api_name = str(row.get(api_column, ""))
        title = str(row.get(column("title") or "", ""))
        if api_name != "cn_pmi" and "pmi" not in title.lower() and "PMI" not in title and "\u91c7\u8d2d\u7ecf\u7406\u6307\u6570" not in title:
            continue
        month = parse_month(row.get(month_column))
        published = parse_date(row.get(publish_column))
        if month and published:
            rows.append({
                "data_month": month,
                "publish_date": iso(published),
                "publish_date_source": SCHEDULE_SOURCE,
                "issuing_org": str(row.get(column("issuing_org") or "", "")),
                "release_match_method": "schedule_exact_month",
            })
    return sorted(rows, key=lambda item: (item["data_month"], item["publish_date"]))


def normalise_akshare(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """The endpoint is a fixed official manufacturing PMI series; use its first two columns."""
    if frame.empty or len(frame.columns) < 3:
        return []
    rows = []
    date_column, value_column = frame.columns[1], frame.columns[2]
    for row in frame[[date_column, value_column]].itertuples(index=False):
        published = parse_date(row[0])
        value = pd.to_numeric(pd.Series([row[1]]), errors="coerce").iloc[0]
        if published and pd.notna(value):
            rows.append({"publish_date": iso(published), "crosscheck_value": round(float(value), 4)})
    return sorted(rows, key=lambda item: item["publish_date"])


def fetch_akshare() -> pd.DataFrame:
    import akshare as ak
    return ak.macro_china_pmi_yearly()


def match_release_dates(
    rows: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    fallback_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    schedule_by_month: dict[str, list[dict[str, Any]]] = {}
    for event in schedule:
        schedule_by_month.setdefault(event["data_month"], []).append(event)
    fallback_used: set[str] = set()
    release_conflicts: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    counters = {"schedule_direct": 0, "akshare_fallback": 0, "untrusted": 0, "conflict": 0, "crosscheck_mismatch": 0}
    output = []
    for row in rows:
        enriched = dict(row)
        month = row["data_month"]
        direct = schedule_by_month.get(month, [])
        if len(direct) > 1:
            dates = sorted(set(item["publish_date"] for item in direct))
            if len(dates) > 1:
                release_conflicts.append({"identity": {"data_month": month}, "publish_dates": dates, "reason": "multiple cn_schedule PMI events"})
                counters["conflict"] += 1
                counters["untrusted"] += 1
                output.append(enriched)
                continue
        if direct:
            event = direct[0]
            enriched.update({"publish_date": event["publish_date"], "publish_date_source": SCHEDULE_SOURCE, "issuing_org": event.get("issuing_org"), "release_match_method": "schedule_exact_month"})
            crosschecks = [item for item in fallback_events if item["publish_date"] == event["publish_date"]]
            if len(crosschecks) == 1:
                diff = round(float(crosschecks[0]["crosscheck_value"]) - float(row["pmi"]), 4)
                enriched.update({"crosscheck_value": crosschecks[0]["crosscheck_value"], "crosscheck_diff": diff})
                if abs(diff) > RELEASE_MATCH_TOLERANCE:
                    mismatch_rows.append({"data_month": month, "publish_date": event["publish_date"], "diff": diff})
                    counters["crosscheck_mismatch"] += 1
            counters["schedule_direct"] += 1
            output.append(enriched)
            continue
        start, end = release_window(month)
        candidates = [
            event for event in fallback_events
            if start <= parse_date(event["publish_date"]) <= end
            and abs(float(event["crosscheck_value"]) - float(row["pmi"])) <= RELEASE_MATCH_TOLERANCE
            and event["publish_date"] not in fallback_used
        ]
        if len(candidates) == 1:
            event = candidates[0]
            fallback_used.add(event["publish_date"])
            diff = round(float(event["crosscheck_value"]) - float(row["pmi"]), 4)
            enriched.update({"publish_date": event["publish_date"], "publish_date_source": FALLBACK_SOURCE, "crosscheck_value": event["crosscheck_value"], "crosscheck_diff": diff, "release_match_method": "akshare_value_window"})
            counters["akshare_fallback"] += 1
        elif len(candidates) > 1:
            dates = sorted(event["publish_date"] for event in candidates)
            release_conflicts.append({"identity": {"data_month": month}, "publish_dates": dates, "reason": "multiple AKShare value matches"})
            counters["conflict"] += 1
            counters["untrusted"] += 1
        else:
            window_events = [event for event in fallback_events if start <= parse_date(event["publish_date"]) <= end]
            if window_events:
                diffs = [round(float(event["crosscheck_value"]) - float(row["pmi"]), 4) for event in window_events]
                mismatch_rows.append({"data_month": month, "diffs": diffs})
                counters["crosscheck_mismatch"] += 1
            counters["untrusted"] += 1
        output.append(enriched)
    return output, release_conflicts, mismatch_rows, counters


def canonical_records(
    tushare_rows: list[dict[str, Any]],
    value_conflicts: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    fallback_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    rows, release_conflicts, mismatch_rows, counters = match_release_dates(tushare_rows, schedule, fallback_events)
    conflicted_months = {item["identity"]["data_month"] for item in value_conflicts}
    conflicted_months |= {item["identity"]["data_month"] for item in release_conflicts}
    records = []
    for row in rows:
        record = {
            "data_month": row["data_month"],
            "pmi": row["pmi"],
            "publish_date": row.get("publish_date"),
            "value_source": VALUE_SOURCE,
            "publish_date_source": row.get("publish_date_source"),
            "issuing_org": row.get("issuing_org"),
            "crosscheck_value": row.get("crosscheck_value"),
            "crosscheck_diff": row.get("crosscheck_diff"),
            "release_match_method": row.get("release_match_method"),
            "revision_history_unavailable": True,
        }
        records.append(record)
    counters["untrusted"] = len([row for row in records if not row.get("publish_date")])
    counters["conflict_months"] = len(conflicted_months)
    return records, value_conflicts + release_conflicts, counters


def source_conflict_months(conflicts: list[dict[str, Any]]) -> set[str]:
    return {item.get("identity", {}).get("data_month") for item in conflicts}


def merge_records(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [dict(row) for row in existing]
    conflicts: list[dict[str, Any]] = []
    by_month: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_month.setdefault(row["data_month"], []).append(row)
    for row in fresh:
        same_month = by_month.setdefault(row["data_month"], [])
        same_value = next((item for item in same_month if item.get("pmi") == row.get("pmi")), None)
        if same_value:
            if same_value.get("publish_date") and row.get("publish_date") and same_value["publish_date"] != row["publish_date"]:
                conflicts.append({"identity": {"data_month": row["data_month"]}, "publish_dates": sorted({same_value["publish_date"], row["publish_date"]}), "reason": "different release date for same month"})
            if not same_value.get("publish_date") and row.get("publish_date"):
                same_value.update({key: value for key, value in row.items() if value is not None})
            continue
        if same_month:
            conflicts.append({"identity": {"data_month": row["data_month"]}, "values": sorted({float(item.get("pmi")) for item in same_month + [row]}), "reason": "different PMI value for same month"})
        same_month.append(dict(row))
        rows.append(dict(row))
    return sorted(rows, key=lambda item: (item["data_month"], item.get("pmi", 0))), conflicts


def cache_metadata(records: list[dict[str, Any]], conflicts: list[dict[str, Any]], refreshed_at: date | None = None, refresh_error: str | None = None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(existing or {})
    months = sorted({row["data_month"] for row in records})
    published = sorted(row["publish_date"] for row in records if row.get("publish_date"))
    successful = iso(refreshed_at) if refreshed_at else metadata.get("last_successful_refresh_date")
    metadata.update({
        "first_data_month": months[0] if months else None,
        "latest_data_month": months[-1] if months else None,
        "first_publish_date": published[0] if published else None,
        "latest_publish_date": published[-1] if published else None,
        "record_count": len(records),
        "release_date_coverage_pct": round(sum(bool(row.get("publish_date")) for row in records) / len(records) * 100, 2) if records else 0.0,
        "last_successful_refresh_date": successful,
        "conflict_count": len(conflicts),
        "refresh_error": refresh_error,
    })
    return metadata


def cache_payload(records: list[dict[str, Any]], conflicts: list[dict[str, Any]], refreshed_at: date | None = None, metadata: dict[str, Any] | None = None, refresh_error: str | None = None, audit_counters: dict[str, int] | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "source": VALUE_SOURCE, "records": records, "conflicts": conflicts, "metadata": cache_metadata(records, conflicts, refreshed_at, refresh_error, metadata), "audit_counters": audit_counters or {}}


def load_cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1 or payload.get("source") != VALUE_SOURCE:
        raise ValueError("unsupported Cycle PMI source cache schema")
    return payload


def load_cache(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    payload = load_cache_payload(path)
    if payload is None:
        return None
    return list(payload.get("records", [])), list(payload.get("conflicts", []))


def load_cache_metadata(path: Path) -> dict[str, Any]:
    payload = load_cache_payload(path)
    if payload is None:
        return cache_metadata([], [])
    return cache_metadata(payload.get("records", []), payload.get("conflicts", []), existing=payload.get("metadata", {}))


def fetch_sources(pro: Any, start: date, end: date, ak_fetcher: Callable[[], pd.DataFrame] = fetch_akshare) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pmi_frame = pro.cn_pmi(start_m=start.strftime("%Y%m"), end_m=end.strftime("%Y%m"), fields="month,pmi010000")
    tushare_rows, value_conflicts = normalise_tushare(pmi_frame)
    schedule_frame = pro.cn_schedule(start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), fields="month,publish_date,title,issuing_org,data_api")
    schedule = normalise_schedule(schedule_frame)
    fallback_error = None
    try:
        fallback = normalise_akshare(ak_fetcher())
    except Exception as exc:
        fallback = []
        fallback_error = str(exc)
    records, conflicts, counters = canonical_records(tushare_rows, value_conflicts, schedule, fallback)
    return records, conflicts, schedule, fallback, {"fallback_error": fallback_error, **counters}


def source_from_cache_or_api_status(
    pro: Any,
    cache_path: Path,
    start: date,
    end: date,
    refresh: bool = True,
    refresh_date: date | None = None,
    ak_fetcher: Callable[[], pd.DataFrame] = fetch_akshare,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], dict[str, Any], str | None, dict[str, int]]:
    payload = load_cache_payload(cache_path)
    cached = load_cache(cache_path)
    if cached is None and not refresh:
        return None, [], cache_metadata([], []), "PMI cache unavailable in offline mode", {}
    if cached is not None and not refresh:
        return cached[0], cached[1], load_cache_metadata(cache_path), None, dict((payload or {}).get("audit_counters", {}))
    try:
        fresh, source_conflicts, schedule, fallback, counters = fetch_sources(pro, start, end, ak_fetcher)
        records, merge_conflicts = merge_records(cached[0] if cached else [], fresh)
        conflicts = source_conflicts + merge_conflicts
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_payload(records, conflicts, refresh_date or date.today(), (payload or {}).get("metadata"), audit_counters=counters), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return records, conflicts, load_cache_metadata(cache_path), None, counters
    except Exception as exc:
        if cached is not None:
            return cached[0], cached[1], load_cache_metadata(cache_path), str(exc), dict((payload or {}).get("audit_counters", {}))
        return None, [{"source_error": str(exc)}], cache_metadata([], []), str(exc), {}


def unavailable(basis: date, reason: str, source: str = VALUE_SOURCE) -> dict[str, Any]:
    return {"value": None, "data_month": None, "observation_date": None, "publish_date": None, "source": source, "value_source": VALUE_SOURCE, "publish_date_source": None, "lag_days": None, "change_1m": None, "change_3m": None, "above_50": None, "available": False, "pit_safe": False, "reason": reason}


def snapshot(records: list[dict[str, Any]] | None, conflicts: list[dict[str, Any]], basis: date, refresh_error: str | None = None) -> dict[str, Any]:
    if records is None:
        return unavailable(basis, refresh_error or "PMI source unavailable")
    blocked = source_conflict_months(conflicts)
    visible = [row for row in records if row.get("data_month") not in blocked and row.get("publish_date") and parse_date(row["publish_date"]) <= basis]
    visible.sort(key=lambda row: (row["data_month"], row["publish_date"]))
    if not visible:
        return unavailable(basis, refresh_error or "no PMI publication visible at or before basis trade date")
    current = visible[-1]
    index = len(visible) - 1
    published = parse_date(current["publish_date"])
    prior_1 = visible[index - 1] if index >= 1 else None
    prior_3 = visible[index - 3] if index >= 3 else None
    result = {
        "value": round(float(current["pmi"]), 4),
        "data_month": current["data_month"],
        "observation_date": iso(published),
        "publish_date": current["publish_date"],
        "source": VALUE_SOURCE,
        "value_source": current.get("value_source", VALUE_SOURCE),
        "publish_date_source": current.get("publish_date_source"),
        "issuing_org": current.get("issuing_org"),
        "crosscheck_value": current.get("crosscheck_value"),
        "crosscheck_diff": current.get("crosscheck_diff"),
        "release_match_method": current.get("release_match_method"),
        "lag_days": (basis - published).days,
        "change_1m": round(float(current["pmi"]) - float(prior_1["pmi"]), 4) if prior_1 else None,
        "change_3m": round(float(current["pmi"]) - float(prior_3["pmi"]), 4) if prior_3 else None,
        "above_50": float(current["pmi"]) >= 50,
        "available": True,
        "pit_safe": published <= basis,
        "reason": refresh_error if refresh_error else None,
    }
    return result


def audit_records(records: list[dict[str, Any]] | None, conflicts: list[dict[str, Any]], counters: dict[str, int], refresh_error: str | None) -> dict[str, Any]:
    rows = records or []
    months = sorted({row.get("data_month") for row in rows if row.get("data_month")})
    published = [row.get("publish_date") for row in rows if row.get("publish_date")]
    return {
        "pmi_first_data_month": months[0] if months else None,
        "pmi_latest_data_month": months[-1] if months else None,
        "pmi_first_publish_date": min(published) if published else None,
        "pmi_latest_publish_date": max(published) if published else None,
        "pmi_record_count": len(rows),
        "pmi_duplicate_month_count": len(rows) - len(months),
        "pmi_release_date_coverage_pct": round(len(published) / len(rows) * 100, 2) if rows else 0.0,
        "pmi_source_conflict_count": len([item for item in conflicts if item.get("reason", "").startswith("different PMI") or "values" in item and len(item.get("values", [])) > 1]),
        "pmi_release_conflict_count": len([item for item in conflicts if "publish_dates" in item]),
        "pmi_crosscheck_mismatch_count": counters.get("crosscheck_mismatch", 0),
        "pmi_schedule_direct_count": counters.get("schedule_direct", 0),
        "pmi_akshare_fallback_count": counters.get("akshare_fallback", 0),
        "pmi_untrusted_publish_date_count": counters.get("untrusted", 0),
        "pmi_future_publication_count": 0,
        "pmi_cache_refresh_error": refresh_error,
        "revision_history_unavailable": True,
    }
