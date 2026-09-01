from __future__ import annotations

"""Build the monthly, point-in-time input dataset for the future cycle engine.

This module deliberately contains no cycle score, position rule, or API wiring.  It
is a research dataset only; the production v3.4 market score remains untouched.
"""

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import build_market_dataset
import cycle_earnings
import cycle_roe


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATASET_VERSION = "cycle_dataset_v1"
EARNINGS_CACHE_PATH = DATA_DIR / "cycle_earnings_source_cache.json"
ROE_CACHE_PATH = DATA_DIR / "cycle_roe_source_cache.json"
START_MONTH = "2010-01"
WARMUP_START = "2005-01-01"
VALUATION_CHUNK_YEARS = 5
HISTORY_READY_OBSERVATIONS = 504
INDEXES = {
    "csi300": {"ts_code": "000300.SH", "name": "CSI 300"},
    "csi500": {"ts_code": "000905.SH", "name": "CSI 500"},
    "csi1000": {"ts_code": "000852.SH", "name": "CSI 1000"},
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def api_call(call: Callable[..., pd.DataFrame], **kwargs: Any) -> pd.DataFrame:
    """Keep live errors explicit.  A missing source never becomes a neutral value."""
    return call(**kwargs)


def parse_date(value: Any) -> date | None:
    return build_market_dataset.parse_observation_date(value)


def iso(value: date) -> str:
    return value.isoformat()


def finite(value: Any, digits: int = 4) -> float | None:
    return build_market_dataset.finite_float(value, digits)


def month_floor(value: date) -> date:
    return value.replace(day=1)


def previous_month_end(value: date) -> date:
    return value.replace(day=1) - timedelta(days=1)


def month_range(start: str, end: date) -> list[str]:
    current = datetime.strptime(start, "%Y-%m").date()
    terminal = month_floor(end)
    months: list[str] = []
    while current <= terminal:
        months.append(current.strftime("%Y-%m"))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def feature(
    value: float | None,
    basis: date,
    source: str,
    observation_date: date | None = None,
    announcement_date: date | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_date = announcement_date or observation_date
    available = value is not None and effective_date is not None and effective_date <= basis
    result: dict[str, Any] = {
        "value": value if available else None,
        "observation_date": iso(observation_date) if observation_date else None,
        "announcement_date": iso(announcement_date) if announcement_date else None,
        "source": source,
        "lag_days": (basis - effective_date).days if effective_date else None,
        "available": available,
        "pit_safe": effective_date <= basis if effective_date else False,
    }
    if reason:
        result["reason"] = reason
    if extra:
        result.update(extra)
    return result


def unavailable(basis: date, source: str, reason: str) -> dict[str, Any]:
    return feature(None, basis, source, reason=reason)


def standardised_feature(values: pd.Series, trade_dates: pd.Series, basis: date, source: str, source_first_observation: date | None = None) -> dict[str, Any]:
    history = pd.DataFrame({"value": pd.to_numeric(values, errors="coerce"), "trade_date": trade_dates.astype(str)}).dropna(subset=["value"])
    if history.empty:
        row = unavailable(basis, source, "no valid valuation observation at or before basis trade date")
        row.update({"percentile_expanding": None, "zscore_expanding": None, "history_observations": 0, "history_start_date": None, "history_end_date": None, "history_years": None, "history_ready": False, "source_first_observation_date": iso(source_first_observation) if source_first_observation else None, "pre_inception": False})
        return row
    history = history.sort_values("trade_date").reset_index(drop=True)
    observation = datetime.strptime(history.iloc[-1]["trade_date"], "%Y%m%d").date()
    start = datetime.strptime(history.iloc[0]["trade_date"], "%Y%m%d").date()
    clean = history["value"].astype(float)
    value = finite(clean.iloc[-1])
    row = feature(value, basis, source, observation_date=observation)
    row.update({
        "percentile_expanding": finite((clean <= value).sum() / len(clean) * 100, 2) if value is not None else None,
        "zscore_expanding": finite((value - clean.mean()) / clean.std(ddof=0), 4) if value is not None and len(clean) >= 24 and clean.std(ddof=0) else None,
        "history_observations": int(len(clean)),
        "history_start_date": iso(start),
        "history_end_date": iso(observation),
        "history_years": finite((observation - start).days / 365.25, 2),
        "history_ready": len(clean) >= HISTORY_READY_OBSERVATIONS,
        "source_first_observation_date": iso(source_first_observation) if source_first_observation else iso(start),
        "pre_inception": False,
    })
    return row


def fetch_open_calendar(pro: Any, start: date, end: date) -> list[str]:
    frame = api_call(
        pro.trade_cal,
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
    )
    if frame.empty:
        raise RuntimeError("Tushare.trade_cal returned no open SSE dates")
    return sorted(frame["cal_date"].astype(str).tolist())


def fetch_index_history(pro: Any, end: date) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for name, meta in INDEXES.items():
        try:
            frame = api_call(
                pro.index_daily,
                ts_code=meta["ts_code"],
                start_date=WARMUP_START.replace("-", ""),
                end_date=end.strftime("%Y%m%d"),
            )
            if frame.empty:
                raise RuntimeError("empty index_daily response")
            frame = frame.copy()
            frame["trade_date"] = frame["trade_date"].astype(str)
            frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
            frames[name] = frame.dropna(subset=["close"]).sort_values("trade_date").reset_index(drop=True)
        except Exception as exc:
            frames[name] = pd.DataFrame(columns=["trade_date", "close"])
            errors[name] = str(exc)
    return frames, errors


def valuation_date_windows(start: date, end: date, years: int = VALUATION_CHUNK_YEARS) -> list[tuple[date, date]]:
    """Keep each Tushare request beneath its single-response row limit."""
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        terminal = min(current.replace(year=current.year + years) - timedelta(days=1), end)
        windows.append((current, terminal))
        current = terminal + timedelta(days=1)
    return windows


def fetch_valuation_history(pro: Any, end: date) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for name, meta in INDEXES.items():
        try:
            parts = [
                api_call(
                    pro.index_dailybasic,
                    ts_code=meta["ts_code"],
                    start_date=start.strftime("%Y%m%d"),
                    end_date=terminal.strftime("%Y%m%d"),
                )
                for start, terminal in valuation_date_windows(datetime.strptime(WARMUP_START, "%Y-%m-%d").date(), end)
            ]
            frame = pd.concat([part for part in parts if not part.empty], ignore_index=True) if any(not part.empty for part in parts) else pd.DataFrame()
            if frame.empty:
                raise RuntimeError("empty index_dailybasic response")
            frame = frame.copy()
            frame["trade_date"] = frame["trade_date"].astype(str)
            for column in ("pe_ttm", "pe", "pb"):
                if column in frame:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frames[name] = frame.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last").reset_index(drop=True)
        except Exception as exc:
            frames[name] = pd.DataFrame(columns=["trade_date", "pe_ttm", "pe", "pb"])
            errors[name] = str(exc)
    return frames, errors


def last_trade_date_by_month(open_dates: list[str], end: date) -> dict[str, date]:
    result: dict[str, date] = {}
    for raw in open_dates:
        current = datetime.strptime(raw, "%Y%m%d").date()
        if current <= end:
            result[current.strftime("%Y-%m")] = current
    return result


def trend_snapshot(frame: pd.DataFrame, basis: date, source: str, reason: str | None = None) -> dict[str, Any]:
    eligible = frame.loc[frame["trade_date"] <= basis.strftime("%Y%m%d")].copy()
    if eligible.empty:
        why = reason or "no index observation at or before basis trade date"
        return {
            "close": unavailable(basis, source, why),
            "ma250_deviation_pct": unavailable(basis, source, why),
            "return_6m_pct": unavailable(basis, source, why),
            "return_12m_pct": unavailable(basis, source, why),
            "drawdown_prev_12m_high_pct": unavailable(basis, source, why),
        }
    close = pd.to_numeric(eligible["close"], errors="coerce").dropna().reset_index(drop=True)
    observation = datetime.strptime(str(eligible.iloc[-1]["trade_date"]), "%Y%m%d").date()
    latest = float(close.iloc[-1])
    def metric(value: float | None) -> dict[str, Any]:
        return feature(finite(value), basis, source, observation_date=observation)
    ma250 = close.tail(250).mean() if len(close) >= 250 else None
    return_6m = (latest / close.iloc[-127] - 1) * 100 if len(close) >= 127 else None
    return_12m = (latest / close.iloc[-253] - 1) * 100 if len(close) >= 253 else None
    prior_high = close.tail(252).max() if len(close) >= 1 else None
    drawdown = (latest / prior_high - 1) * 100 if prior_high else None
    return {
        "close": metric(latest),
        "ma250_deviation_pct": metric((latest / ma250 - 1) * 100 if ma250 else None),
        "return_6m_pct": metric(return_6m),
        "return_12m_pct": metric(return_12m),
        "drawdown_prev_12m_high_pct": metric(drawdown),
    }


def valuation_snapshot(frame: pd.DataFrame, basis: date, source: str, reason: str | None = None) -> dict[str, Any]:
    eligible = frame.loc[frame["trade_date"] <= basis.strftime("%Y%m%d")].copy()
    if eligible.empty:
        source_first = parse_date(frame.iloc[0]["trade_date"]) if not frame.empty else None
        pre_inception = source_first is not None and source_first > basis
        why = "valuation history not yet available for index" if pre_inception else (reason or "no valuation observation at or before basis trade date")

        def missing() -> dict[str, Any]:
            row = unavailable(basis, source, why)
            row.update({"percentile_expanding": None, "zscore_expanding": None, "history_observations": 0, "history_start_date": None, "history_end_date": None, "history_years": None, "history_ready": False, "source_first_observation_date": iso(source_first) if source_first else None, "pre_inception": pre_inception, "source_error": reason if reason and not pre_inception else None})
            return row

        return {"pe_ttm": missing(), "pb": missing()}
    source_first = parse_date(frame.iloc[0]["trade_date"])
    pe_column = "pe_ttm" if "pe_ttm" in eligible.columns else "pe"
    return {
        "pe_ttm": standardised_feature(eligible[pe_column], eligible["trade_date"], basis, source, source_first),
        "pb": standardised_feature(eligible["pb"], eligible["trade_date"], basis, source, source_first),
    }


def valuation_source_metadata(valuations: dict[str, pd.DataFrame], errors: dict[str, str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for name, frame in valuations.items():
        first = parse_date(frame.iloc[0]["trade_date"]) if not frame.empty else None
        metadata[name] = {
            "source_first_observation_date": iso(first) if first else None,
            "source_error": errors.get(name),
        }
    return metadata


def valuation_domain(valuations: dict[str, pd.DataFrame], errors: dict[str, str], basis: date) -> dict[str, Any]:
    valuation_indices = {
        name: valuation_snapshot(valuations[name], basis, "Tushare.index_dailybasic", errors.get(name))
        for name in INDEXES
    }
    csi300_pe = valuation_indices["csi300"]["pe_ttm"]
    observation = parse_date(csi300_pe.get("observation_date"))
    earnings_yield = None
    if csi300_pe.get("available") and csi300_pe.get("value") and csi300_pe["value"] > 0:
        earnings_yield = 100 / csi300_pe["value"]
    return {
        "indices": valuation_indices,
        "china_10y_government_bond_yield_pct": unavailable(
            basis,
            "Tushare.yc_cb",
            "historical yc_cb permission is unavailable; no second PIT source is configured",
        ),
        "csi300_earnings_yield_pct": feature(
            finite(earnings_yield),
            basis,
            "derived:Tushare.index_dailybasic",
            observation_date=observation,
            extra={"derived_from": "valuation.indices.csi300.pe_ttm"},
        ) if earnings_yield is not None and observation else unavailable(basis, "derived:Tushare.index_dailybasic", "CSI 300 PE TTM unavailable"),
        "csi300_erp_pct": unavailable(
            basis,
            "derived:Tushare.index_dailybasic,Tushare.yc_cb",
            "requires both CSI 300 earnings yield and a PIT China 10-year government yield",
        ),
    }


def latest_financial_observation(frame: pd.DataFrame, basis: date) -> pd.Series | None:
    """Return only an already announced report; used by the PIT financial adapter."""
    if frame.empty or "ann_date" not in frame:
        return None
    eligible = frame.copy()
    eligible["_ann_date"] = eligible["ann_date"].map(parse_date)
    eligible = eligible.loc[eligible["_ann_date"].notna() & (eligible["_ann_date"] <= basis)]
    if eligible.empty:
        return None
    return eligible.sort_values(["_ann_date", "end_date" if "end_date" in eligible else "ann_date"]).iloc[-1]


def unavailable_earnings(basis: date, source_reason: str) -> dict[str, Any]:
    source = "Tushare.fina_indicator/income"
    fields = {
        "all_a_net_profit_yoy_pct": unavailable(basis, source, source_reason),
        "nonfinancial_a_net_profit_yoy_pct": unavailable(basis, source, source_reason),
        "all_a_roe_ttm_pct": unavailable(basis, source, source_reason),
        "nonfinancial_a_roe_ttm_pct": unavailable(basis, source, source_reason),
        "industrial_profit_yoy_pct": unavailable(basis, "not_configured", source_reason),
        "pmi": unavailable(basis, "not_configured", source_reason),
        "ppi_yoy_pct": unavailable(basis, "not_configured", source_reason),
    }
    return {
        **fields,
        "coverage": {
            "available": False,
            "stock_count": None,
            "coverage_rate": None,
            "report_period": None,
            "latest_announcement_date": None,
            "reason": source_reason,
        },
        "methodology": "Financial-industry exclusion must use each report-period constituent/industry metadata; current broad-market PIT source is unavailable, so no retrospective listed-set substitution is used.",
    }


def a_fear_snapshot(basis: date) -> dict[str, Any]:
    path = DATA_DIR / "a_fear_history.json"
    if not path.exists():
        return {"basis_trade_date": None, "fear_score": None, "confidence": "unavailable", "available": False}
    try:
        records = json.loads(path.read_text(encoding="utf-8-sig")).get("records", [])
        candidates = [row for row in records if str(row.get("basis_trade_date", "")) <= basis.isoformat()]
        if not candidates:
            return {"basis_trade_date": None, "fear_score": None, "confidence": "unavailable", "available": False}
        row = sorted(candidates, key=lambda item: item["basis_trade_date"])[-1]
        return {"basis_trade_date": row["basis_trade_date"], "fear_score": row.get("fear_score"), "confidence": row.get("confidence", "unknown"), "available": row.get("fear_score") is not None}
    except Exception:
        return {"basis_trade_date": None, "fear_score": None, "confidence": "unavailable", "available": False}


def record_for_month(
    month: str,
    basis: date,
    prices: dict[str, pd.DataFrame],
    valuations: dict[str, pd.DataFrame],
    price_errors: dict[str, str],
    valuation_errors: dict[str, str],
    earnings_income_by_period: dict[str, pd.DataFrame] | None,
    earnings_stocks: pd.DataFrame | None,
    roe_balance_by_period: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    trend_indices: dict[str, Any] = {}
    warnings: list[str] = []
    for name, meta in INDEXES.items():
        trend_indices[name] = trend_snapshot(prices[name], basis, "Tushare.index_daily", price_errors.get(name))
        if valuation_errors.get(name):
            warnings.append(f"valuation.{name}: {valuation_errors[name]}")
        if price_errors.get(name):
            warnings.append(f"trend.{name}: {price_errors[name]}")
    valuation = valuation_domain(valuations, valuation_errors, basis)
    if earnings_income_by_period is not None and earnings_stocks is not None:
        aggregation = cycle_earnings.profit_growth_snapshot(earnings_income_by_period, earnings_stocks, basis)
        earnings = unavailable_earnings(basis, "ROE and macro earnings fields are outside Cycle Earnings Growth PIT v1")
        earnings["all_a_net_profit_yoy_pct"] = aggregation["all_a"]
        earnings["nonfinancial_a_net_profit_yoy_pct"] = aggregation["nonfinancial_a"]
        earnings["profit_growth_aggregation"] = aggregation
        if roe_balance_by_period is not None:
            roe = cycle_roe.roe_snapshot(earnings_income_by_period, roe_balance_by_period, earnings_stocks, basis, aggregation["all_a"].get("report_period"))
            earnings["all_a_roe_ttm_pct"] = roe["all_a"]
            earnings["nonfinancial_a_roe_ttm_pct"] = roe["nonfinancial_a"]
        earnings["coverage"] = {
            "available": aggregation["all_a"]["available"],
            "stock_count": aggregation["all_a"]["matched_stock_count"],
            "coverage_rate": aggregation["all_a"]["matched_coverage_rate"],
            "report_period": aggregation["all_a"]["report_period"],
            "latest_announcement_date": aggregation["all_a"]["announcement_date"],
            "reason": aggregation["all_a"].get("reason"),
        }
    else:
        earnings = unavailable_earnings(basis, "income_vip source unavailable; no neutral fallback is permitted")
        warnings.append("earnings: income_vip source unavailable")
    domains = {"valuation": valuation, "earnings": earnings, "trend": {"indices": trend_indices}, "sentiment": {"a_fear": a_fear_snapshot(basis)}}
    coverage = domain_coverage(domains)
    return {
        "month": month,
        "basis_trade_date": iso(basis),
        "valuation": valuation,
        "earnings": earnings,
        "trend": {"indices": trend_indices},
        "sentiment": {"a_fear": a_fear_snapshot(basis)},
        "data_quality": {
            "warnings": warnings,
            "coverage": coverage,
            "confidence": "low" if coverage["earnings_pct"] == 0 else "medium",
        },
    }


def walk_feature_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if {"available", "pit_safe", "source"}.issubset(value):
            return [value]
        rows: list[dict[str, Any]] = []
        for nested in value.values():
            rows.extend(walk_feature_rows(nested))
        return rows
    return []


def domain_coverage(domains: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for domain in ("valuation", "earnings", "trend"):
        rows = walk_feature_rows(domains.get(domain, {}))
        result[f"{domain}_pct"] = finite(sum(bool(row.get("available")) for row in rows) / len(rows) * 100, 2) if rows else 0.0
    sentiment = domains.get("sentiment", {}).get("a_fear", {})
    result["a_fear_pct"] = 100.0 if sentiment.get("available") else 0.0
    return result


def valuation_warmup_audit(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records", [])
    january_2010 = next((record for record in records if record.get("month") == "2010-01"), {})
    source_metadata = payload.get("valuation_source_metadata", {})
    output: dict[str, Any] = {}
    for name in INDEXES:
        january_index = january_2010.get("valuation", {}).get("indices", {}).get(name, {})
        pe = january_index.get("pe_ttm", {})
        pb = january_index.get("pb", {})
        ready_months = {
            field: next((record.get("month") for record in records if record.get("valuation", {}).get("indices", {}).get(name, {}).get(field, {}).get("history_ready")), None)
            for field in ("pe_ttm", "pb")
        }
        output[name] = {
            "source_first_observation_date": source_metadata.get(name, {}).get("source_first_observation_date") or pe.get("source_first_observation_date") or pb.get("source_first_observation_date"),
            "2010_01": {
                "basis_trade_date": january_2010.get("basis_trade_date"),
                "pe_history_observations": pe.get("history_observations"),
                "pe_percentile_expanding": pe.get("percentile_expanding"),
                "pe_history_start_date": pe.get("history_start_date"),
                "pb_history_observations": pb.get("history_observations"),
                "pb_percentile_expanding": pb.get("percentile_expanding"),
                "pb_history_start_date": pb.get("history_start_date"),
                "pre_inception": bool(pe.get("pre_inception")) or bool(pb.get("pre_inception")),
            },
            "first_history_ready_month": ready_months,
        }
    return output


def audit_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records", [])
    months = [row.get("month") for row in records]
    basis_dates = [row.get("basis_trade_date") for row in records]
    order_violation_count = sum(left >= right for left, right in zip(months, months[1:]))
    pit_violations: list[dict[str, Any]] = []
    missing_by_field: dict[str, int] = {}
    low_confidence_periods: list[str] = []
    domain_totals = {"valuation": [], "earnings": [], "trend": [], "a_fear": []}
    profit_growth_counts = {"all_a": 0, "nonfinancial_a": 0, "months": 0}
    profit_growth_samples: dict[str, list[dict[str, float]]] = {"all_a": [], "nonfinancial_a": []}
    roe_counts = {"all_a": 0, "nonfinancial_a": 0, "months": 0}
    roe_samples: dict[str, list[dict[str, float]]] = {"all_a": [], "nonfinancial_a": []}
    current_invalid_report_types = 0
    prior_invalid_report_types = 0
    roe_pit_violations: list[dict[str, Any]] = []
    roe_invalid_report_types = 0
    roe_nonfinancial_universe_violations: list[dict[str, Any]] = []
    roe_nonfinancial_matched_violations: list[dict[str, Any]] = []
    valuation_future_observations: list[dict[str, Any]] = []
    derived_lineage_violations: list[dict[str, Any]] = []
    index_valuation_samples: dict[str, list[dict[str, bool]]] = {name: [] for name in INDEXES}
    for record in records:
        basis = parse_date(record.get("basis_trade_date"))
        if not basis:
            pit_violations.append({"month": record.get("month"), "field": "basis_trade_date", "reason": "invalid basis"})
            continue
        for domain in ("valuation", "earnings", "trend"):
            for row in walk_feature_rows(record.get(domain, {})):
                observed = parse_date(row.get("announcement_date") or row.get("observation_date"))
                if observed and observed > basis:
                    pit_violations.append({"month": record["month"], "field": domain, "date": iso(observed), "basis": iso(basis)})
                if not row.get("available"):
                    key = row.get("source", "unknown")
                    missing_by_field[key] = missing_by_field.get(key, 0) + 1
            domain_totals[domain].append(record.get("data_quality", {}).get("coverage", {}).get(f"{domain}_pct", 0.0))
        valuation = record.get("valuation", {})
        for name in INDEXES:
            index = valuation.get("indices", {}).get(name, {})
            pe = index.get("pe_ttm", {})
            pb = index.get("pb", {})
            for field, row in (("pe_ttm", pe), ("pb", pb)):
                for date_field in ("observation_date", "history_end_date"):
                    observed = parse_date(row.get(date_field))
                    if observed and observed > basis:
                        valuation_future_observations.append({"month": record["month"], "index": name, "field": field, "date_field": date_field, "date": iso(observed), "basis": iso(basis)})
            index_valuation_samples[name].append({
                "pe_available": bool(pe.get("available")),
                "pb_available": bool(pb.get("available")),
                "history_ready": bool(pe.get("history_ready")) and bool(pb.get("history_ready")),
                "pre_inception": bool(pe.get("pre_inception")) or bool(pb.get("pre_inception")),
                "source_error": bool(pe.get("source_error")) or bool(pb.get("source_error")),
                "history_not_ready": (bool(pe.get("available")) or bool(pb.get("available"))) and not (bool(pe.get("history_ready")) and bool(pb.get("history_ready"))),
            })
        pe = valuation.get("indices", {}).get("csi300", {}).get("pe_ttm", {})
        earnings_yield = valuation.get("csi300_earnings_yield_pct", {})
        if pe.get("available") and earnings_yield.get("available") and earnings_yield.get("observation_date") != pe.get("observation_date"):
            derived_lineage_violations.append({"month": record["month"], "field": "csi300_earnings_yield_pct", "expected_observation_date": pe.get("observation_date"), "actual_observation_date": earnings_yield.get("observation_date")})
        domain_totals["a_fear"].append(record.get("data_quality", {}).get("coverage", {}).get("a_fear_pct", 0.0))
        if record.get("data_quality", {}).get("confidence") == "low":
            low_confidence_periods.append(record["month"])
        earnings = record.get("earnings", {})
        profit_growth_counts["months"] += 1
        profit_growth_counts["all_a"] += bool(earnings.get("all_a_net_profit_yoy_pct", {}).get("available"))
        profit_growth_counts["nonfinancial_a"] += bool(earnings.get("nonfinancial_a_net_profit_yoy_pct", {}).get("available"))
        for name, field in (("all_a", "all_a_net_profit_yoy_pct"), ("nonfinancial_a", "nonfinancial_a_net_profit_yoy_pct")):
            row = earnings.get(field, {})
            if row.get("available") and row.get("current_statement_report_type") != cycle_earnings.CURRENT_REPORT_TYPE:
                current_invalid_report_types += 1
            if row.get("available") and any(item not in cycle_earnings.PRIOR_REPORT_TYPES for item in row.get("prior_comparator_report_types_used", [])):
                prior_invalid_report_types += 1
            if row.get("available"):
                profit_growth_samples[name].append({
                    "eligible_stock_count": float(row.get("eligible_stock_count", 0)),
                    "matched_stock_count": float(row.get("matched_stock_count", 0)),
                    "matched_coverage_rate": float(row.get("matched_coverage_rate", 0)),
                })
        roe_counts["months"] += 1
        for name, field in (("all_a", "all_a_roe_ttm_pct"), ("nonfinancial_a", "nonfinancial_a_roe_ttm_pct")):
            row = earnings.get(field, {})
            roe_counts[name] += bool(row.get("available"))
            announcement = parse_date(row.get("announcement_date"))
            if row.get("available") and announcement and announcement > basis:
                roe_pit_violations.append({"month": record["month"], "field": field, "date": iso(announcement), "basis": iso(basis)})
            if row.get("available") and row.get("current_statement_report_type") != cycle_earnings.CURRENT_REPORT_TYPE:
                roe_invalid_report_types += 1
            if row.get("available") and any(item not in cycle_earnings.PRIOR_REPORT_TYPES for item in row.get("prior_equity_report_types_used", [])):
                roe_invalid_report_types += 1
            if row.get("available"):
                roe_samples[name].append({"eligible_stock_count": float(row.get("eligible_stock_count", 0)), "matched_stock_count": float(row.get("matched_stock_count", 0)), "matched_coverage_rate": float(row.get("matched_coverage_rate", 0))})
        all_a_roe = earnings.get("all_a_roe_ttm_pct", {})
        nonfinancial_roe = earnings.get("nonfinancial_a_roe_ttm_pct", {})
        all_eligible = int(all_a_roe.get("eligible_stock_count", 0) or 0)
        nonfinancial_eligible = int(nonfinancial_roe.get("eligible_stock_count", 0) or 0)
        all_matched = int(all_a_roe.get("matched_stock_count", 0) or 0)
        nonfinancial_matched = int(nonfinancial_roe.get("matched_stock_count", 0) or 0)
        if nonfinancial_eligible > all_eligible:
            roe_nonfinancial_universe_violations.append({"month": record["month"], "all_a_eligible_stock_count": all_eligible, "nonfinancial_eligible_stock_count": nonfinancial_eligible})
        if nonfinancial_matched > all_matched:
            roe_nonfinancial_matched_violations.append({"month": record["month"], "all_a_matched_stock_count": all_matched, "nonfinancial_matched_stock_count": nonfinancial_matched})
    coverage = {key: finite(sum(values) / len(values), 2) if values else 0.0 for key, values in domain_totals.items()}
    duplicate_count = len(months) - len(set(months)) + len(basis_dates) - len(set(basis_dates))
    cache = payload.get("earnings_source_cache", {})
    affected_months: list[str] = []
    affected_identities: list[dict[str, Any]] = []
    identities = cache.get("conflicts", [])
    for record in records:
        basis = parse_date(record.get("basis_trade_date"))
        periods = {record.get("earnings", {}).get("all_a_net_profit_yoy_pct", {}).get("report_period"), record.get("earnings", {}).get("all_a_net_profit_yoy_pct", {}).get("prior_year_report_period")}
        for conflict in identities:
            identity = conflict.get("identity", {})
            if identity.get("end_date") in periods and basis and parse_date(identity.get("_effective_ann_str")) and parse_date(identity.get("_effective_ann_str")) <= basis:
                affected_months.append(record["month"])
                if conflict not in affected_identities:
                    affected_identities.append(conflict)
                break
    roe_cache = payload.get("roe_source_cache", {})
    roe_universe_violation_months = sorted({row["month"] for row in roe_nonfinancial_universe_violations + roe_nonfinancial_matched_violations})
    structural_passed = len(pit_violations) == 0 and len(roe_pit_violations) == 0 and duplicate_count == 0 and order_violation_count == 0 and current_invalid_report_types == 0 and prior_invalid_report_types == 0 and roe_invalid_report_types == 0 and len(roe_nonfinancial_universe_violations) == 0 and len(roe_nonfinancial_matched_violations) == 0 and len(valuation_future_observations) == 0 and len(derived_lineage_violations) == 0
    freshness_passed = not bool(cache.get("stale")) and not bool(cache.get("refresh_error")) and not bool(cache.get("offline")) and not bool(roe_cache.get("stale")) and not bool(roe_cache.get("refresh_error")) and not bool(roe_cache.get("offline"))
    return {
        "dataset_version": payload.get("dataset_version"),
        "generated_at": datetime.now(build_market_dataset.TZ).isoformat(timespec="seconds"),
        "record_count": len(records),
        "start_month": min(months) if months else None,
        "end_month": max(months) if months else None,
        "coverage_pct": coverage,
        "profit_growth_coverage_pct": {
            "all_a_net_profit_yoy_pct": finite(profit_growth_counts["all_a"] / profit_growth_counts["months"] * 100, 2) if profit_growth_counts["months"] else 0.0,
            "nonfinancial_a_net_profit_yoy_pct": finite(profit_growth_counts["nonfinancial_a"] / profit_growth_counts["months"] * 100, 2) if profit_growth_counts["months"] else 0.0,
        },
        "profit_growth_sample_averages": {
            name: {
                "eligible_stock_count": finite(sum(row["eligible_stock_count"] for row in rows) / len(rows), 2) if rows else None,
                "matched_stock_count": finite(sum(row["matched_stock_count"] for row in rows) / len(rows), 2) if rows else None,
                "matched_coverage_rate": finite(sum(row["matched_coverage_rate"] for row in rows) / len(rows), 2) if rows else None,
            }
            for name, rows in profit_growth_samples.items()
        },
        "roe_coverage_pct": {"all_a": finite(roe_counts["all_a"] / roe_counts["months"] * 100, 2) if roe_counts["months"] else 0.0, "nonfinancial_a": finite(roe_counts["nonfinancial_a"] / roe_counts["months"] * 100, 2) if roe_counts["months"] else 0.0},
        "roe_sample_averages": {name: {"eligible_stock_count": finite(sum(row["eligible_stock_count"] for row in rows) / len(rows), 2) if rows else None, "matched_stock_count": finite(sum(row["matched_stock_count"] for row in rows) / len(rows), 2) if rows else None, "matched_coverage_rate": finite(sum(row["matched_coverage_rate"] for row in rows) / len(rows), 2) if rows else None} for name, rows in roe_samples.items()},
        "roe_pit_violation_count": len(roe_pit_violations),
        "roe_pit_violations": roe_pit_violations,
        "roe_invalid_report_type_count": roe_invalid_report_types,
        "roe_nonfinancial_universe_violation_count": len(roe_nonfinancial_universe_violations),
        "roe_nonfinancial_matched_violation_count": len(roe_nonfinancial_matched_violations),
        "roe_universe_violation_months": roe_universe_violation_months,
        "valuation_future_observation_count": len(valuation_future_observations),
        "valuation_future_observations": valuation_future_observations,
        "derived_lineage_violation_count": len(derived_lineage_violations),
        "derived_lineage_violations": derived_lineage_violations,
        "index_valuation_coverage": {
            name: {
                "pe_coverage_pct": finite(sum(row["pe_available"] for row in rows) / len(rows) * 100, 2) if rows else 0.0,
                "pb_coverage_pct": finite(sum(row["pb_available"] for row in rows) / len(rows) * 100, 2) if rows else 0.0,
                "history_ready_coverage_pct": finite(sum(row["history_ready"] for row in rows) / len(rows) * 100, 2) if rows else 0.0,
                "pre_inception_count": sum(row["pre_inception"] for row in rows),
                "source_error_count": sum(row["source_error"] for row in rows),
                "history_not_ready_count": sum(row["history_not_ready"] for row in rows),
            }
            for name, rows in index_valuation_samples.items()
        },
        "valuation_warmup_audit": valuation_warmup_audit(payload),
        "roe_source_conflict_count": int(roe_cache.get("conflict_count", 0)),
        "roe_cache_latest_period": roe_cache.get("metadata", {}).get("latest_period"),
        "roe_cache_stale": bool(roe_cache.get("stale")),
        "roe_cache_refresh_error": roe_cache.get("refresh_error"),
        "earnings_source_cache_conflict_count": int(payload.get("earnings_source_cache", {}).get("conflict_count", 0)),
        "current_statement_invalid_report_type_count": current_invalid_report_types,
        "prior_statement_invalid_report_type_count": prior_invalid_report_types,
        "ambiguous_source_conflict_count": int(payload.get("earnings_source_cache", {}).get("conflict_count", 0)),
        "affected_month_count": len(affected_months),
        "affected_months": affected_months,
        "affected_source_conflict_count": len(affected_identities),
        "affected_source_identities": affected_identities,
        "stock_metadata_conflict_count": len(cache.get("metadata", {}).get("stock_metadata_conflicts", [])),
        "earnings_cache_latest_period": payload.get("earnings_source_cache", {}).get("metadata", {}).get("latest_period"),
        "earnings_cache_stale": bool(payload.get("earnings_source_cache", {}).get("stale")),
        "earnings_cache_missing_expected_periods": payload.get("earnings_source_cache", {}).get("missing_expected_periods", []),
        "earnings_cache_last_successful_refresh_date": payload.get("earnings_source_cache", {}).get("last_successful_refresh_date") or payload.get("earnings_source_cache", {}).get("last_refresh_date"),
        "earnings_cache_refresh_lag_days": payload.get("earnings_source_cache", {}).get("refresh_lag_days"),
        "earnings_cache_refresh_error": payload.get("earnings_source_cache", {}).get("refresh_error"),
        "pit_violation_count": len(pit_violations),
        "pit_violations": pit_violations,
        "duplicate_count": duplicate_count,
        "order_violation_count": order_violation_count,
        "missing_by_source": missing_by_field,
        "low_confidence_periods": low_confidence_periods,
        "structural_passed": structural_passed,
        "freshness_passed": freshness_passed,
        "passed": structural_passed and freshness_passed,
    }


def audit_markdown(audit: dict[str, Any]) -> str:
    coverage = audit["coverage_pct"]
    return "\n".join(
        [
            "# Cycle Dataset v1 Audit",
            "",
            f"- Dataset version: `{audit['dataset_version']}`",
            f"- Records: {audit['record_count']} ({audit['start_month']} to {audit['end_month']})",
            f"- PIT violations: {audit['pit_violation_count']}",
            f"- Duplicate count: {audit['duplicate_count']}",
            f"- Order violations: {audit['order_violation_count']}",
            f"- Valuation coverage: {coverage['valuation']}%",
            f"- Valuation future observations / lineage violations: {audit['valuation_future_observation_count']}/{audit['derived_lineage_violation_count']}",
            f"- Earnings coverage: {coverage['earnings']}%",
            f"- ROE nonfinancial-universe violations: {audit['roe_nonfinancial_universe_violation_count']}",
            f"- ROE nonfinancial-matched violations: {audit['roe_nonfinancial_matched_violation_count']}",
            f"- All-A profit-growth coverage: {audit['profit_growth_coverage_pct']['all_a_net_profit_yoy_pct']}%",
            f"- Nonfinancial profit-growth coverage: {audit['profit_growth_coverage_pct']['nonfinancial_a_net_profit_yoy_pct']}%",
            f"- All-A/nonfinancial ROE(TTM) coverage: {audit['roe_coverage_pct']['all_a']}%/{audit['roe_coverage_pct']['nonfinancial_a']}%",
            f"- ROE PIT violations / invalid report types: {audit['roe_pit_violation_count']}/{audit['roe_invalid_report_type_count']}",
            f"- Earnings source-cache conflicts: {audit['earnings_source_cache_conflict_count']}",
            f"- Invalid current/prior report types: {audit['current_statement_invalid_report_type_count']}/{audit['prior_statement_invalid_report_type_count']}",
            f"- Earnings cache latest period: {audit['earnings_cache_latest_period']}; stale: {audit['earnings_cache_stale']}",
            f"- Earnings cache last successful refresh: {audit['earnings_cache_last_successful_refresh_date']}; refresh lag days: {audit['earnings_cache_refresh_lag_days']}",
            f"- Trend coverage: {coverage['trend']}%",
            f"- A-FEAR coverage: {coverage['a_fear']}%",
            f"- Result: {'PASS' if audit['passed'] else 'FAIL'}",
            "",
            "Unavailable fields are retained as unavailable with an explicit source reason; they are never assigned neutral values.",
            "",
        ]
    )


def build_dataset(as_of: date, refresh_earnings_cache: bool = True) -> dict[str, Any]:
    end = previous_month_end(as_of)
    if end < datetime.strptime(START_MONTH, "%Y-%m").date():
        raise ValueError("as_of is before the first supported month")
    pro = build_market_dataset.tushare_client()
    open_dates = fetch_open_calendar(pro, datetime.strptime(WARMUP_START, "%Y-%m-%d").date(), end)
    month_basis = last_trade_date_by_month(open_dates, end)
    months = [month for month in month_range(START_MONTH, end) if month in month_basis]
    prices, price_errors = fetch_index_history(pro, end)
    valuations, valuation_errors = fetch_valuation_history(pro, end)
    try:
        earnings_income, earnings_stocks, cache_conflicts, earnings_cache_meta, refresh_error = cycle_earnings.source_from_cache_or_api_status(
            pro, EARNINGS_CACHE_PATH, 2009, end.year, end, refresh=refresh_earnings_cache
        )
        earnings_income_by_period = cycle_earnings.prepare_income_by_period(earnings_income) if earnings_income is not None else None
        earnings_freshness = cycle_earnings.audit_cache_freshness(earnings_income if earnings_income is not None else pd.DataFrame(columns=["end_date"]), earnings_cache_meta, end, refresh_error=refresh_error)
    except Exception as exc:
        earnings_income_by_period, earnings_stocks, cache_conflicts, earnings_cache_meta, earnings_freshness = None, None, [{"source_error": str(exc)}], {}, {"stale": True, "missing_expected_periods": [], "refresh_error": str(exc)}
    try:
        roe_balance, roe_conflicts, roe_cache_meta, roe_refresh_error = cycle_roe.source_from_cache_or_api_status(pro, ROE_CACHE_PATH, 2008, end.year, end, refresh=refresh_earnings_cache)
        roe_balance_by_period = cycle_roe.prepare_balance_by_period(roe_balance) if roe_balance is not None else None
        roe_freshness = cycle_roe.audit_cache_freshness(roe_balance if roe_balance is not None else pd.DataFrame(columns=["end_date"]), roe_cache_meta, end, roe_refresh_error)
    except Exception as exc:
        roe_balance_by_period, roe_conflicts, roe_cache_meta, roe_freshness = None, [{"source_error": str(exc)}], {}, {"stale": True, "missing_expected_periods": [], "refresh_error": str(exc)}
    records = [
        record_for_month(month, month_basis[month], prices, valuations, price_errors, valuation_errors, earnings_income_by_period, earnings_stocks, roe_balance_by_period)
        for month in months
    ]
    payload = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "description": "Monthly Point-in-Time cycle research inputs. Not an official score or position decision.",
        "period": {"start_month": months[0], "end_month": months[-1], "warmup_start": WARMUP_START},
        "sources": ["Tushare.trade_cal", "Tushare.index_daily", "Tushare.index_dailybasic", "Tushare.income_vip", "A-FEAR local history (optional)"],
        "valuation_source_metadata": valuation_source_metadata(valuations, valuation_errors),
        "earnings_source_cache": {"path": str(EARNINGS_CACHE_PATH.relative_to(ROOT)), "conflict_count": len(cache_conflicts), "conflicts": cache_conflicts, "metadata": earnings_cache_meta, **earnings_freshness, "offline": not refresh_earnings_cache},
        "roe_source_cache": {"path": str(ROE_CACHE_PATH.relative_to(ROOT)), "equity_field": cycle_roe.EQUITY_FIELD, "conflict_count": len(roe_conflicts), "conflicts": roe_conflicts, "metadata": roe_cache_meta, **roe_freshness, "offline": not refresh_earnings_cache},
        "records": records,
    }
    audit = audit_dataset(payload)
    if not audit["structural_passed"]:
        raise RuntimeError(
            "Cycle dataset audit failed: "
            f"{audit['pit_violation_count']} PIT violations, {audit['duplicate_count']} duplicates, "
            f"{audit['order_violation_count']} order violations"
        )
    return payload


def rebuild_earnings_from_existing_dataset(path: Path) -> dict[str, Any]:
    """Refresh only the earnings domain when market source endpoints are unavailable."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    cached = cycle_earnings.load_cache(EARNINGS_CACHE_PATH)
    roe_cached = cycle_roe.load_cache(ROE_CACHE_PATH)
    if cached is None:
        raise RuntimeError("earnings source cache is unavailable")
    income, stocks, conflicts = cached
    balance, roe_conflicts = roe_cached if roe_cached is not None else (None, [])
    by_period = cycle_earnings.prepare_income_by_period(income)
    roe_by_period = cycle_roe.prepare_balance_by_period(balance) if balance is not None else None
    for record in payload.get("records", []):
        basis = parse_date(record.get("basis_trade_date"))
        if not basis:
            raise RuntimeError(f"invalid basis date in {record.get('month')}")
        aggregation = cycle_earnings.profit_growth_snapshot(by_period, stocks, basis)
        earnings = unavailable_earnings(basis, "macro earnings fields are outside Cycle Earnings PIT v1")
        earnings["all_a_net_profit_yoy_pct"] = aggregation["all_a"]
        earnings["nonfinancial_a_net_profit_yoy_pct"] = aggregation["nonfinancial_a"]
        earnings["profit_growth_aggregation"] = aggregation
        if roe_by_period is not None:
            roe = cycle_roe.roe_snapshot(by_period, roe_by_period, stocks, basis, aggregation["all_a"].get("report_period"))
            earnings["all_a_roe_ttm_pct"] = roe["all_a"]
            earnings["nonfinancial_a_roe_ttm_pct"] = roe["nonfinancial_a"]
        earnings["coverage"] = {"available": aggregation["all_a"]["available"], "stock_count": aggregation["all_a"]["matched_stock_count"], "coverage_rate": aggregation["all_a"]["matched_coverage_rate"], "report_period": aggregation["all_a"]["report_period"], "latest_announcement_date": aggregation["all_a"]["announcement_date"], "reason": aggregation["all_a"].get("reason")}
        record["earnings"] = earnings
        record["data_quality"]["coverage"] = domain_coverage({"valuation": record.get("valuation", {}), "earnings": earnings, "trend": record.get("trend", {}), "sentiment": record.get("sentiment", {})})
        record["data_quality"]["confidence"] = "low" if record["data_quality"]["coverage"]["earnings_pct"] == 0 else "medium"
    metadata = cycle_earnings.load_cache_metadata(EARNINGS_CACHE_PATH)
    end = parse_date(payload.get("records", [])[-1].get("basis_trade_date"))
    freshness = cycle_earnings.audit_cache_freshness(income, metadata, end) if end else {"stale": True, "missing_expected_periods": []}
    payload["earnings_source_cache"] = {"path": str(EARNINGS_CACHE_PATH.relative_to(ROOT)), "conflict_count": len(conflicts), "conflicts": conflicts, "metadata": metadata, **freshness, "offline": True}
    roe_metadata = cycle_roe.load_cache_metadata(ROE_CACHE_PATH)
    roe_freshness = cycle_roe.audit_cache_freshness(balance, roe_metadata, end) if balance is not None and end else {"stale": True, "missing_expected_periods": [], "refresh_error": "ROE balance-sheet cache unavailable"}
    payload["roe_source_cache"] = {"path": str(ROE_CACHE_PATH.relative_to(ROOT)), "equity_field": cycle_roe.EQUITY_FIELD, "conflict_count": len(roe_conflicts), "conflicts": roe_conflicts, "metadata": roe_metadata, **roe_freshness, "offline": True}
    return payload


def rebuild_valuation_from_existing_dataset(path: Path, as_of: date) -> dict[str, Any]:
    """Refresh only PIT valuation fields without rewriting other Cycle domains."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    end = previous_month_end(as_of)
    pro = build_market_dataset.tushare_client()
    valuations, valuation_errors = fetch_valuation_history(pro, end)
    for record in payload.get("records", []):
        basis = parse_date(record.get("basis_trade_date"))
        if not basis:
            raise RuntimeError(f"invalid basis date in {record.get('month')}")
        record["valuation"] = valuation_domain(valuations, valuation_errors, basis)
        record["data_quality"]["coverage"] = domain_coverage({"valuation": record["valuation"], "earnings": record.get("earnings", {}), "trend": record.get("trend", {}), "sentiment": record.get("sentiment", {})})
        record["data_quality"]["confidence"] = "low" if record["data_quality"]["coverage"]["earnings_pct"] == 0 else "medium"
    payload["valuation_source_metadata"] = valuation_source_metadata(valuations, valuation_errors)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Cycle Dataset v1 without changing official market scoring.")
    parser.add_argument("--as-of", default=datetime.now(build_market_dataset.TZ).strftime("%Y-%m-%d"))
    parser.add_argument("--out", default=str(DATA_DIR / "cycle_dataset_v1.json"))
    parser.add_argument("--audit-json", default=str(DATA_DIR / "cycle_dataset_audit_latest.json"))
    parser.add_argument("--audit-md", default=str(DATA_DIR / "cycle_dataset_audit_latest.md"))
    parser.add_argument("--offline-cache", action="store_true", help="Rebuild from the append-only earnings cache without a live refresh.")
    parser.add_argument("--reuse-existing-market-data", action="store_true", help="Reuse existing valuation/trend records and refresh only the earnings domain.")
    parser.add_argument("--reuse-existing-nonvaluation-data", action="store_true", help="Reuse existing nonvaluation records and refresh only PIT valuation fields.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_market_dataset.load_dotenv(ROOT / ".env")
    output_path = Path(args.out)
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    if args.reuse_existing_market_data and args.reuse_existing_nonvaluation_data:
        raise ValueError("choose at most one reuse mode")
    if args.reuse_existing_market_data:
        payload = rebuild_earnings_from_existing_dataset(output_path)
    elif args.reuse_existing_nonvaluation_data:
        payload = rebuild_valuation_from_existing_dataset(output_path, as_of)
    else:
        payload = build_dataset(as_of, refresh_earnings_cache=not args.offline_cache)
    audit = audit_dataset(payload)
    write_json(output_path, payload)
    write_json(Path(args.audit_json), audit)
    Path(args.audit_md).write_text(audit_markdown(audit), encoding="utf-8")
    print(json.dumps({"dataset": args.out, "audit": args.audit_json, "records": audit["record_count"], "passed": audit["passed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
