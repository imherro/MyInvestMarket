from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import tushare as ts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")

INDEXES = {
    "000001.SH": {"name": "\u4e0a\u8bc1\u6307\u6570", "name_en": "Shanghai Composite"},
    "399001.SZ": {"name": "\u6df1\u8bc1\u6210\u6307", "name_en": "Shenzhen Component"},
    "399006.SZ": {"name": "\u521b\u4e1a\u677f\u6307", "name_en": "ChiNext Index"},
    "899050.BJ": {"name": "\u5317\u8bc150", "name_en": "BSE 50"},
}


@dataclass
class Quality:
    missing_fields: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    feature_freshness: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cross_validation: dict[str, Any] = field(default_factory=dict)

    def source(self, name: str) -> None:
        if name not in self.sources_used:
            self.sources_used.append(name)

    def missing(self, field_name: str, reason: str | None = None) -> None:
        if field_name not in self.missing_fields:
            self.missing_fields.append(field_name)
        if reason:
            note = f"{field_name}: {reason}"
            if note not in self.notes:
                self.notes.append(note)

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def freshness(
        self,
        field_name: str,
        basis_date: date,
        observation_date: date | None,
        source: str,
        status: str,
        ignored_future_observations: int = 0,
    ) -> None:
        lag_days = (basis_date - observation_date).days if observation_date else None
        self.feature_freshness[field_name] = {
            "basis_date": basis_date.isoformat(),
            "observation_date": observation_date.isoformat() if observation_date else None,
            "lag_days": lag_days,
            "source": source,
            "status": status,
            "ignored_future_observations": ignored_future_observations,
        }


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def iso_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def parse_observation_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def finite_float(value: Any, digits: int | None = 4) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, digits) if digits is not None else number
    except Exception:
        return None


def finite_int(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def percentile_rank(series: pd.Series, value: float | None) -> float | None:
    if value is None:
        return None
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return finite_float((clean <= value).sum() / len(clean) * 100, 2)


def tushare_client() -> Any:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured in .env or environment")
    ts.set_token(token)
    return ts.pro_api(token)


def fetch_latest_complete_trade_date(pro: Any, as_of: date, q: Quality) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    start = yyyymmdd(as_of - timedelta(days=45))
    end = yyyymmdd(as_of)
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    q.source("Tushare.trade_cal")
    if cal.empty:
        raise RuntimeError(f"No open trading day found from {start} to {end}")

    open_days = sorted(cal["cal_date"].astype(str).tolist(), reverse=True)
    for trade_date in open_days:
        daily = pro.daily(trade_date=trade_date)
        index_probe = pro.index_daily(ts_code="000001.SH", trade_date=trade_date)
        if not daily.empty and not index_probe.empty:
            q.source("Tushare.daily")
            q.source("Tushare.index_daily")
            return trade_date, daily, index_probe

    raise RuntimeError(f"No complete Tushare daily market data found through {end}")


def index_metrics(pro: Any, trade_date: str, q: Quality) -> dict[str, Any]:
    start = (
        datetime.strptime(trade_date, "%Y%m%d").date() - timedelta(days=90)
    ).strftime("%Y%m%d")
    result: dict[str, Any] = {}
    for code, meta in INDEXES.items():
        try:
            df = pro.index_daily(ts_code=code, start_date=start, end_date=trade_date)
            q.source("Tushare.index_daily")
        except Exception as exc:
            q.missing(f"market.indices.{code}", str(exc))
            continue

        if df.empty:
            q.missing(f"market.indices.{code}", "no index_daily rows")
            result[code] = {"name": meta["name"], "name_en": meta["name_en"], "available": False}
            continue

        df = df.sort_values("trade_date").reset_index(drop=True)
        latest = df.iloc[-1]
        close = float(latest["close"])
        ma20 = df["close"].tail(20).mean() if len(df) >= 20 else float("nan")
        prev5_close = df.iloc[-6]["close"] if len(df) >= 6 else float("nan")
        prev20_close = df.iloc[-21]["close"] if len(df) >= 21 else float("nan")
        prev5_vol = df["vol"].iloc[-6:-1].mean() if len(df) >= 6 else float("nan")

        result[code] = {
            "name": meta["name"],
            "name_en": meta["name_en"],
            "trade_date": iso_date(str(latest["trade_date"])),
            "close": finite_float(close),
            "return_5d_pct": finite_float((close / prev5_close - 1) * 100),
            "return_20d_pct": finite_float((close / prev20_close - 1) * 100),
            "ma20": finite_float(ma20),
            "ma20_deviation_pct": finite_float((close / ma20 - 1) * 100),
            "volume_ratio_5d": finite_float(float(latest["vol"]) / prev5_vol),
            "above_ma20": bool(close >= ma20) if math.isfinite(ma20) else None,
            "source": "Tushare.index_daily",
        }
    return result


def index_valuation(pro: Any, trade_date: str, q: Quality) -> dict[str, Any]:
    start = (
        datetime.strptime(trade_date, "%Y%m%d").date() - timedelta(days=365 * 5 + 30)
    ).strftime("%Y%m%d")
    result: dict[str, Any] = {
        "trade_date": iso_date(trade_date),
        "indices": {},
        "market": {},
    }

    pe_scores: list[float] = []
    pb_scores: list[float] = []
    for code, meta in INDEXES.items():
        try:
            df = pro.index_dailybasic(ts_code=code, start_date=start, end_date=trade_date)
            q.source("Tushare.index_dailybasic")
        except Exception as exc:
            q.missing(f"valuation.indices.{code}", str(exc))
            continue

        if df.empty:
            q.missing(f"valuation.indices.{code}", "empty index_dailybasic")
            continue

        df = df.sort_values("trade_date").reset_index(drop=True)
        latest = df.iloc[-1]
        pe = finite_float(latest.get("pe_ttm") if "pe_ttm" in latest else latest.get("pe"))
        pb = finite_float(latest.get("pb"))
        pe_percentile = percentile_rank(df["pe_ttm"] if "pe_ttm" in df.columns else df.get("pe", pd.Series(dtype=float)), pe)
        pb_percentile = percentile_rank(df["pb"] if "pb" in df.columns else pd.Series(dtype=float), pb)
        if pe_percentile is not None:
            pe_scores.append(100 - pe_percentile)
        if pb_percentile is not None:
            pb_scores.append(100 - pb_percentile)

        result["indices"][code] = {
            "name": meta["name"],
            "trade_date": iso_date(str(latest.get("trade_date"))),
            "pe_ttm": pe,
            "pb": pb,
            "pe_percentile_5y": pe_percentile,
            "pb_percentile_5y": pb_percentile,
            "source": "Tushare.index_dailybasic",
        }

    pe_score = finite_float(sum(pe_scores) / len(pe_scores), 2) if pe_scores else None
    pb_score = finite_float(sum(pb_scores) / len(pb_scores), 2) if pb_scores else None
    blended = None
    if pe_score is not None and pb_score is not None:
        blended = finite_float(pe_score * 0.6 + pb_score * 0.4, 2)
    elif pe_score is not None:
        blended = pe_score
    elif pb_score is not None:
        blended = pb_score

    result["market"] = {
        "index_pe_value_score": pe_score,
        "index_pb_value_score": pb_score,
        "valuation_score": blended,
        "score_note": "Higher score means cheaper relative to the 5-year index_dailybasic history.",
    }
    return result


def volatility_metrics(pro: Any, trade_date: str, q: Quality) -> dict[str, Any]:
    start = (
        datetime.strptime(trade_date, "%Y%m%d").date() - timedelta(days=180)
    ).strftime("%Y%m%d")
    result: dict[str, Any] = {"trade_date": iso_date(trade_date), "indices": {}, "market": {}}

    market_vols: list[float] = []
    for code, meta in INDEXES.items():
        try:
            df = pro.index_daily(ts_code=code, start_date=start, end_date=trade_date)
            q.source("Tushare.index_daily")
        except Exception as exc:
            q.missing(f"volatility.indices.{code}", str(exc))
            continue
        if df.empty:
            q.missing(f"volatility.indices.{code}", "empty index_daily")
            continue
        df = df.sort_values("trade_date").reset_index(drop=True)
        returns = pd.to_numeric(df["close"], errors="coerce").pct_change().dropna()
        vol_30 = finite_float(returns.tail(30).std() * math.sqrt(252), 4) if len(returns) >= 10 else None
        vol_60 = finite_float(returns.tail(60).std() * math.sqrt(252), 4) if len(returns) >= 20 else None
        max_close = pd.to_numeric(df["close"], errors="coerce").tail(60).max()
        latest_close = finite_float(df.iloc[-1].get("close"))
        drawdown_60 = finite_float((latest_close / max_close - 1) * 100, 4) if latest_close is not None and pd.notna(max_close) and max_close else None
        if vol_30 is not None and code in ["000001.SH", "399001.SZ", "399006.SZ"]:
            market_vols.append(vol_30)
        result["indices"][code] = {
            "name": meta["name"],
            "realized_vol_30d": vol_30,
            "realized_vol_60d": vol_60,
            "drawdown_60d_pct": drawdown_60,
            "source": "Tushare.index_daily",
        }

    result["market"] = {
        "realized_vol_30d": finite_float(sum(market_vols) / len(market_vols), 4) if market_vols else None,
        "target_annual_vol": None,
        "source_note": "Average 30-day annualized realized volatility of Shanghai, Shenzhen, and ChiNext when available; stock-account position policy uses volatility as a risk indicator only.",
    }
    return result


def fetch_sw_l1(pro: Any, trade_date: str, q: Quality) -> pd.DataFrame:
    classify = pro.index_classify(level="L1", src="SW2021")
    q.source("Tushare.index_classify")
    sw = pro.sw_daily(trade_date=trade_date)
    q.source("Tushare.sw_daily")
    if classify.empty or sw.empty:
        return pd.DataFrame()
    codes = set(classify["index_code"].astype(str))
    return sw[sw["ts_code"].astype(str).isin(codes)].copy()


def market_breadth(pro: Any, trade_date: str, daily: pd.DataFrame, sw_l1: pd.DataFrame, q: Quality) -> dict[str, Any]:
    pct = pd.to_numeric(daily["pct_chg"], errors="coerce")
    result = {
        "trade_date": iso_date(trade_date),
        "advancers": int((pct > 0).sum()),
        "decliners": int((pct < 0).sum()),
        "flat": int((pct == 0).sum()),
        "total": int(pct.notna().sum()),
        "median_pct_change": finite_float(pct.median()),
        "strong_advancers_gt3_pct": finite_float((pct > 3).sum() / pct.notna().sum(), 4) if pct.notna().sum() else None,
        "strong_decliners_lt_minus3_pct": finite_float((pct < -3).sum() / pct.notna().sum(), 4) if pct.notna().sum() else None,
    }

    try:
        limits = pro.limit_list_d(trade_date=trade_date)
        q.source("Tushare.limit_list_d")
        result["limit_up"] = int((limits.get("limit") == "U").sum()) if not limits.empty else 0
        result["limit_down"] = int((limits.get("limit") == "D").sum()) if not limits.empty else 0
    except Exception as exc:
        q.missing("breadth.limit_up_down", str(exc))
        result["limit_up"] = None
        result["limit_down"] = None

    try:
        step = pro.limit_step(trade_date=trade_date)
        q.source("Tushare.limit_step")
        if step.empty:
            result["max_limit_up_streak"] = 0
        else:
            nums = pd.to_numeric(step["nums"], errors="coerce")
            result["max_limit_up_streak"] = finite_int(nums.max())
    except Exception as exc:
        q.missing("breadth.max_limit_up_streak", str(exc))
        result["max_limit_up_streak"] = None

    if sw_l1.empty:
        q.missing("breadth.industry_up_ratio", "empty SW L1 daily data")
        result["industry_up_ratio"] = None
        result["industry_count"] = 0
    else:
        industry_pct = pd.to_numeric(sw_l1["pct_change"], errors="coerce")
        count = int(industry_pct.notna().sum())
        result["industry_up_ratio"] = finite_float((industry_pct > 0).sum() / count, 4) if count else None
        result["industry_count"] = count

    return result


def capital_flow(pro: Any, trade_date: str, daily: pd.DataFrame, q: Quality) -> dict[str, Any]:
    result: dict[str, Any] = {
        "trade_date": iso_date(trade_date),
        "market_cap_bucket_thresholds_100m_cny": {
            "large_cap_min": 2000,
            "mid_cap_min": 300,
            "small_cap_max_exclusive": 300,
        },
    }

    try:
        hsgt = pro.moneyflow_hsgt(start_date=trade_date, end_date=trade_date)
        q.source("Tushare.moneyflow_hsgt")
        if hsgt.empty:
            hsgt = pro.moneyflow_hsgt(start_date=(datetime.strptime(trade_date, "%Y%m%d").date() - timedelta(days=10)).strftime("%Y%m%d"), end_date=trade_date)
        if not hsgt.empty:
            row = hsgt.sort_values("trade_date").iloc[-1]
            north_raw = finite_float(row.get("north_money"))
            result["northbound_net_inflow_raw"] = north_raw
            # Recent Tushare HSGT rows in this environment are scaled like 10k CNY.
            # Keep the raw field above so downstream checks can audit the conversion.
            result["northbound_net_inflow_100m_cny"] = finite_float(north_raw / 10000) if north_raw is not None else None
            result["northbound_trade_date"] = iso_date(str(row.get("trade_date")))
            result["northbound_unit_note"] = "northbound_net_inflow_100m_cny = raw north_money / 10000; raw field is preserved"
        else:
            q.missing("capital_flow.northbound_net_inflow_100m_cny", "empty moneyflow_hsgt")
            result["northbound_net_inflow_raw"] = None
            result["northbound_net_inflow_100m_cny"] = None
    except Exception as exc:
        q.missing("capital_flow.northbound_net_inflow_100m_cny", str(exc))
        result["northbound_net_inflow_raw"] = None
        result["northbound_net_inflow_100m_cny"] = None

    try:
        mf = pro.moneyflow(trade_date=trade_date)
        q.source("Tushare.moneyflow")
        if mf.empty:
            q.missing("capital_flow.main_net_inflow_100m_cny", "empty moneyflow")
            result["main_net_inflow_100m_cny"] = None
        else:
            net_10k = pd.to_numeric(mf["net_mf_amount"], errors="coerce").sum()
            result["main_net_inflow_100m_cny"] = finite_float(net_10k / 10000)
    except Exception as exc:
        q.missing("capital_flow.main_net_inflow_100m_cny", str(exc))
        result["main_net_inflow_100m_cny"] = None

    try:
        basic = pro.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,total_mv,circ_mv,turnover_rate,volume_ratio",
        )
        q.source("Tushare.daily_basic")
        merged = daily[["ts_code", "amount"]].merge(
            basic[["ts_code", "total_mv"]], on="ts_code", how="inner"
        )
        merged["total_mv_100m"] = pd.to_numeric(merged["total_mv"], errors="coerce") / 10000
        merged["amount_100m"] = pd.to_numeric(merged["amount"], errors="coerce") / 100000

        def bucket(mv_100m: float) -> str | None:
            if pd.isna(mv_100m):
                return None
            if mv_100m >= 2000:
                return "large_cap"
            if mv_100m >= 300:
                return "mid_cap"
            return "small_cap"

        merged["bucket"] = merged["total_mv_100m"].map(bucket)
        grouped = merged.dropna(subset=["bucket"]).groupby("bucket")["amount_100m"].sum()
        total = grouped.sum()
        result["turnover_distribution"] = {}
        for bucket_name in ["large_cap", "mid_cap", "small_cap"]:
            amount = float(grouped.get(bucket_name, 0.0))
            result["turnover_distribution"][bucket_name] = {
                "turnover_100m_cny": finite_float(amount),
                "share": finite_float(amount / total, 4) if total else None,
            }
    except Exception as exc:
        q.missing("capital_flow.turnover_distribution", str(exc))
        result["turnover_distribution"] = None

    return result


def sector_rotation(pro: Any, trade_date: str, sw_l1: pd.DataFrame, q: Quality) -> dict[str, Any]:
    result: dict[str, Any] = {"trade_date": iso_date(trade_date)}
    if sw_l1.empty:
        q.missing("sector_rotation.return_rankings", "empty SW L1 daily data")
        result["top5_industries_by_return"] = []
        result["bottom5_industries_by_return"] = []
    else:
        ranked = sw_l1.copy()
        ranked["pct_change"] = pd.to_numeric(ranked["pct_change"], errors="coerce")
        ranked = ranked.dropna(subset=["pct_change"])

        def row_to_industry(row: pd.Series) -> dict[str, Any]:
            return {
                "industry": row.get("name"),
                "ts_code": row.get("ts_code"),
                "pct_change": finite_float(row.get("pct_change")),
                "close": finite_float(row.get("close")),
            }

        result["top5_industries_by_return"] = [
            row_to_industry(row) for _, row in ranked.sort_values("pct_change", ascending=False).head(5).iterrows()
        ]
        result["bottom5_industries_by_return"] = [
            row_to_industry(row) for _, row in ranked.sort_values("pct_change", ascending=True).head(5).iterrows()
        ]

    try:
        flow = pro.moneyflow_ind_ths(trade_date=trade_date)
        q.source("Tushare.moneyflow_ind_ths")
        if flow.empty:
            q.missing("sector_rotation.top5_industries_by_capital_inflow", "empty moneyflow_ind_ths")
            result["top5_industries_by_capital_inflow"] = []
        else:
            flow = flow.copy()
            flow["net_amount"] = pd.to_numeric(flow["net_amount"], errors="coerce")
            result["top5_industries_by_capital_inflow"] = [
                {
                    "industry": row.get("industry"),
                    "ts_code": row.get("ts_code"),
                    "pct_change": finite_float(row.get("pct_change")),
                    "net_amount_100m_cny": finite_float(row.get("net_amount")),
                    "lead_stock": row.get("lead_stock"),
                }
                for _, row in flow.sort_values("net_amount", ascending=False).head(5).iterrows()
            ]
    except Exception as exc:
        q.missing("sector_rotation.top5_industries_by_capital_inflow", str(exc))
        result["top5_industries_by_capital_inflow"] = []

    return result


def latest_series_value_at_or_before(
    series: pd.Series,
    field_name: str,
    q: Quality,
    basis_date: date,
    source: str,
    value_key: str = "value",
) -> dict[str, Any] | None:
    rows: list[tuple[date, float]] = []
    ignored_future = 0
    for index_value, raw_value in series.items():
        observation_date = parse_observation_date(index_value)
        value = finite_float(raw_value)
        if observation_date is None or value is None:
            continue
        if observation_date > basis_date:
            ignored_future += 1
            continue
        rows.append((observation_date, value))

    if ignored_future:
        q.warning(f"{field_name}: ignored {ignored_future} future-dated observations after {basis_date.isoformat()}")

    if not rows:
        status = "missing_after_cutoff" if ignored_future else "missing"
        q.missing(field_name, f"no observation at or before {basis_date.isoformat()}")
        q.freshness(field_name, basis_date, None, source, status, ignored_future)
        return None

    observation_date, value = sorted(rows, key=lambda item: item[0])[-1]
    q.source(source.replace(":", "."))
    q.freshness(field_name, basis_date, observation_date, source, "available", ignored_future)
    return {
        "date": observation_date.isoformat(),
        value_key: value,
        "source": source,
    }


def yf_latest(ticker: str, field_name: str, q: Quality, basis_date: date) -> dict[str, Any] | None:
    try:
        import yfinance as yf

        df = yf.download(
            ticker,
            start=(basis_date - timedelta(days=30)).isoformat(),
            end=(basis_date + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        if df.empty:
            q.missing(field_name, f"empty yfinance result for {ticker}")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df[("Close", ticker)] if ("Close", ticker) in df.columns else df["Close"].iloc[:, 0]
        else:
            close = df["Close"]
        close = close.dropna()
        if close.empty:
            q.missing(field_name, f"no close from yfinance result for {ticker}")
            return None
        return latest_series_value_at_or_before(close, field_name, q, basis_date, f"yfinance:{ticker}")
    except Exception as exc:
        q.missing(field_name, str(exc))
        return None


def fred_latest(
    series_id: str,
    field_name: str,
    q: Quality,
    basis_date: date,
    observation_start: str = "2025-01-01",
) -> dict[str, Any] | None:
    try:
        from fredapi import Fred

        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            q.missing(field_name, "FRED_API_KEY is not configured")
            return None
        fred = Fred(api_key=api_key)
        series = fred.get_series(series_id, observation_start=observation_start).dropna()
        if series.empty:
            q.missing(field_name, f"empty FRED series {series_id}")
            return None
        return latest_series_value_at_or_before(series, field_name, q, basis_date, f"FRED:{series_id}")
    except Exception as exc:
        q.missing(field_name, str(exc))
        return None


def china_10y_yield(pro: Any, q: Quality, basis_date: date) -> dict[str, Any] | None:
    try:
        df = pro.yc_cb(
            start_date=(basis_date - timedelta(days=20)).strftime("%Y%m%d"),
            end_date=basis_date.strftime("%Y%m%d"),
        )
        q.source("Tushare.yc_cb")
        if not df.empty:
            candidates = df[
                df.astype(str).apply(lambda col: col.str.contains("10", na=False)).any(axis=1)
            ].copy()
            candidates["_observation_date"] = candidates.get("trade_date", pd.Series(dtype=str)).map(parse_observation_date)
            candidates = candidates[candidates["_observation_date"].notna()]
            candidates = candidates[candidates["_observation_date"] <= basis_date]
            if not candidates.empty:
                row = candidates.sort_values("_observation_date").iloc[-1]
                for key in ["yield", "yield_rate", "yld", "close"]:
                    if key in row:
                        value = finite_float(row[key])
                        if value is not None:
                            observation_date = row["_observation_date"]
                            q.freshness(
                                "macro.china_10y_government_bond_yield_pct",
                                basis_date,
                                observation_date,
                                "Tushare:yc_cb",
                                "available",
                            )
                            return {
                                "date": observation_date.isoformat(),
                                "value_pct": value,
                                "source": "Tushare.yc_cb",
                            }
    except Exception as exc:
        q.missing("macro.china_10y_government_bond_yield_pct.tushare_yc_cb", str(exc))

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPTA_WEB_TREASURYYIELD",
            "columns": "ALL",
            "sortColumns": "SOLAR_DATE",
            "sortTypes": "-1",
            "token": "894050c76af8597a853f5b408b759f5d",
            "pageNumber": "1",
            "pageSize": "50",
        }
        response = requests.get(
            url,
            params=params,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://data.eastmoney.com/cjsj/zmgzsyl.html",
            },
        )
        response.raise_for_status()
        data = response.json()["result"]["data"]
        if not data:
            q.missing("macro.china_10y_government_bond_yield_pct", "empty Eastmoney response")
            return None
        future_count = 0
        valid_rows: list[tuple[date, dict[str, Any]]] = []
        for row in data:
            observation_date = parse_observation_date(str(row.get("SOLAR_DATE"))[:10])
            if observation_date is None:
                continue
            if observation_date > basis_date:
                future_count += 1
                continue
            valid_rows.append((observation_date, row))
        if future_count:
            q.warning(
                "macro.china_10y_government_bond_yield_pct: "
                f"ignored {future_count} future-dated observations after {basis_date.isoformat()}"
            )
        if not valid_rows:
            q.missing("macro.china_10y_government_bond_yield_pct", f"no observation at or before {basis_date.isoformat()}")
            q.freshness(
                "macro.china_10y_government_bond_yield_pct",
                basis_date,
                None,
                "Eastmoney:RPTA_WEB_TREASURYYIELD",
                "missing_after_cutoff" if future_count else "missing",
                future_count,
            )
            return None
        observation_date, row = sorted(valid_rows, key=lambda item: item[0])[-1]
        q.source("Eastmoney.RPTA_WEB_TREASURYYIELD")
        q.freshness(
            "macro.china_10y_government_bond_yield_pct",
            basis_date,
            observation_date,
            "Eastmoney:RPTA_WEB_TREASURYYIELD",
            "available",
            future_count,
        )
        return {
            "date": observation_date.isoformat(),
            "value_pct": finite_float(row.get("EMM00166466")),
            "source": "Eastmoney:RPTA_WEB_TREASURYYIELD",
        }
    except Exception as exc:
        q.missing("macro.china_10y_government_bond_yield_pct", str(exc))
        return None


def macro_data(pro: Any, q: Quality, trade_date: str) -> dict[str, Any]:
    basis_date = datetime.strptime(trade_date, "%Y%m%d").date()
    result = {
        "us_10y_treasury_yield_pct": fred_latest("DGS10", "macro.us_10y_treasury_yield_pct", q, basis_date),
        "dxy": yf_latest("DX-Y.NYB", "macro.dxy", q, basis_date),
        "usd_cny": yf_latest("CNY=X", "macro.usd_cny", q, basis_date),
        "china_10y_government_bond_yield_pct": china_10y_yield(pro, q, basis_date),
        "fred_key_indicators": {
            "FEDFUNDS": fred_latest("FEDFUNDS", "macro.fred_key_indicators.FEDFUNDS", q, basis_date),
            "DFF": fred_latest("DFF", "macro.fred_key_indicators.DFF", q, basis_date),
            "CPIAUCSL": fred_latest("CPIAUCSL", "macro.fred_key_indicators.CPIAUCSL", q, basis_date),
            "PCEPI": fred_latest("PCEPI", "macro.fred_key_indicators.PCEPI", q, basis_date),
        },
    }
    return result


def qmt_portfolio(q: Quality) -> dict[str, Any]:
    try:
        import importlib.util

        if importlib.util.find_spec("xtquant") is None:
            q.missing("qmt_portfolio.positions", "xtquant is not installed in the active Python environment")
            return {
                "available": False,
                "mode": "read_only_probe",
                "positions": [],
                "cash": None,
                "reason": "xtquant is not installed in the active Python environment",
            }

        q.source("QMT.xtquant")
        return {
            "available": False,
            "mode": "read_only_probe",
            "positions": [],
            "cash": None,
            "reason": "xtquant is installed, but no QMT account/session configuration was provided; no write APIs were called",
        }
    except Exception as exc:
        q.missing("qmt_portfolio", str(exc))
        return {
            "available": False,
            "mode": "read_only_probe",
            "positions": [],
            "cash": None,
            "reason": str(exc),
        }


def baostock_cross_validation(trade_date: str, market: dict[str, Any], q: Quality) -> None:
    try:
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            q.missing("data_quality.cross_validation.baostock_indices", login.error_msg)
            return

        mappings = {
            "000001.SH": "sh.000001",
            "399001.SZ": "sz.399001",
            "399006.SZ": "sz.399006",
        }
        target_date = iso_date(trade_date)
        rows: dict[str, Any] = {}
        for ts_code, bs_code in mappings.items():
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,close,pctChg",
                start_date=target_date,
                end_date=target_date,
                frequency="d",
                adjustflag="3",
            )
            if rs.error_code != "0":
                rows[ts_code] = {"available": False, "reason": rs.error_msg}
                continue
            data = []
            while rs.next():
                data.append(rs.get_row_data())
            if not data:
                rows[ts_code] = {"available": False, "reason": "empty BaoStock row"}
                continue
            close = finite_float(data[0][2])
            tushare_close = market.get("indices", {}).get(ts_code, {}).get("close")
            rows[ts_code] = {
                "available": True,
                "baostock_close": close,
                "tushare_close": tushare_close,
                "close_abs_diff": finite_float(abs(close - tushare_close)) if close is not None and tushare_close is not None else None,
            }
        q.source("BaoStock.query_history_k_data_plus")
        q.cross_validation["baostock_indices"] = rows
    except Exception as exc:
        q.missing("data_quality.cross_validation.baostock_indices", str(exc))
    finally:
        try:
            import baostock as bs

            bs.logout()
        except Exception:
            pass


def build_dataset(as_of: date) -> dict[str, Any]:
    q = Quality()
    pro = tushare_client()
    trade_date, daily, _ = fetch_latest_complete_trade_date(pro, as_of, q)
    sw_l1 = fetch_sw_l1(pro, trade_date, q)

    market = {
        "as_of_trade_date": iso_date(trade_date),
        "indices": index_metrics(pro, trade_date, q),
    }
    breadth = market_breadth(pro, trade_date, daily, sw_l1, q)
    cap_flow = capital_flow(pro, trade_date, daily, q)
    sectors = sector_rotation(pro, trade_date, sw_l1, q)
    valuation = index_valuation(pro, trade_date, q)
    volatility = volatility_metrics(pro, trade_date, q)
    macro = macro_data(pro, q, trade_date)
    qmt = qmt_portfolio(q)
    baostock_cross_validation(trade_date, market, q)

    dataset = {
        "date": iso_date(trade_date),
        "market": market,
        "breadth": breadth,
        "capital_flow": cap_flow,
        "sector_rotation": sectors,
        "valuation": valuation,
        "volatility": volatility,
        "macro": macro,
        "qmt_portfolio": qmt,
        "data_quality": {
            "missing_fields": q.missing_fields,
            "sources_used": q.sources_used,
            "warnings": q.warnings,
            "feature_freshness": q.feature_freshness,
            "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "basis": "latest complete Tushare A-share trading day at or before as_of",
            "notes": q.notes,
            "cross_validation": q.cross_validation,
        },
    }
    validate_built_dataset(dataset)
    return dataset


def validate_built_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    import market_scoring

    return market_scoring.validate_market_snapshot(dataset)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build standardized MyInvest A-share market dataset JSON.")
    parser.add_argument("--as-of", default=datetime.now(TZ).strftime("%Y-%m-%d"), help="Calendar date, YYYY-MM-DD.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    dataset = build_dataset(as_of)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = out_dir / f"market_snapshot_{dataset['date']}.json"
    latest = out_dir / "latest_market_snapshot.json"
    payload = json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=False)
    dated.write_text(payload + "\n", encoding="utf-8")
    latest.write_text(payload + "\n", encoding="utf-8")
    print(str(dated))
    print(str(latest))


if __name__ == "__main__":
    main()
