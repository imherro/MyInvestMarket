from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_HISTORY_PATH = DATA_DIR / "a_fear_history.json"
DEFAULT_LATEST_PATH = DATA_DIR / "a_fear_latest.json"
DEFAULT_SOURCE_CACHE_PATH = DATA_DIR / "a_fear_source_cache.json"
VERSION = "a_fear_v1"
SCHEMA_VERSION = 1
LOOKBACK_DAYS = 750
MIN_SAMPLE_COUNT = 250
TARGET_DAYS = 30
TZ = ZoneInfo("Asia/Shanghai")

COMPONENT_WEIGHTS = {
    "implied_volatility": 0.40,
    "downside_volatility": 0.20,
    "market_breadth": 0.25,
    "tail_loss": 0.15,
}

RAW_FIELDS = {
    "io_iv_30d": ("implied_volatility", "io_iv_30d"),
    "mo_iv_30d": ("implied_volatility", "mo_iv_30d"),
    "csi300_downside_vol_20d": ("downside_volatility", "csi300_20d"),
    "csi1000_downside_vol_20d": ("downside_volatility", "csi1000_20d"),
    "decliner_ratio": ("market_breadth", "decliner_ratio"),
    "decline_beyond_3pct_ratio": ("market_breadth", "decline_beyond_3pct_ratio"),
    "limit_down_ratio": ("market_breadth", "limit_down_ratio"),
    "csi300_loss_1d": ("tail_loss", "csi300_loss_1d"),
    "csi300_loss_5d": ("tail_loss", "csi300_loss_5d"),
    "csi1000_loss_1d": ("tail_loss", "csi1000_loss_1d"),
    "csi1000_loss_5d": ("tail_loss", "csi1000_loss_5d"),
}

TAIL_FIELDS = {
    "csi300_loss_1d",
    "csi300_loss_5d",
    "csi1000_loss_1d",
    "csi1000_loss_5d",
}


def finite_float(value: Any, digits: int | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black76_price(
    forward: float,
    strike: float,
    years: float,
    rate: float,
    volatility: float,
    call_put: str,
) -> float:
    if forward <= 0 or strike <= 0 or years <= 0 or volatility <= 0:
        raise ValueError("Black-76 inputs must be positive")
    discount = math.exp(-rate * years)
    root_t = math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    if call_put.upper() == "C":
        return discount * (forward * normal_cdf(d1) - strike * normal_cdf(d2))
    if call_put.upper() == "P":
        return discount * (strike * normal_cdf(-d2) - forward * normal_cdf(-d1))
    raise ValueError("call_put must be C or P")


def implied_volatility_black76(
    price: float,
    forward: float,
    strike: float,
    years: float,
    rate: float,
    call_put: str,
    tolerance: float = 1e-8,
    max_iterations: int = 120,
) -> float | None:
    if price <= 0 or forward <= 0 or strike <= 0 or years <= 0:
        return None
    discount = math.exp(-rate * years)
    intrinsic = discount * max(forward - strike, 0.0) if call_put.upper() == "C" else discount * max(strike - forward, 0.0)
    upper_bound = discount * (forward if call_put.upper() == "C" else strike)
    if price < intrinsic - tolerance or price >= upper_bound:
        return None

    low, high = 1e-6, 5.0
    try:
        if black76_price(forward, strike, years, rate, high, call_put) < price:
            return None
        for _ in range(max_iterations):
            mid = (low + high) / 2.0
            estimate = black76_price(forward, strike, years, rate, mid, call_put)
            if abs(estimate - price) <= tolerance:
                return mid
            if estimate < price:
                low = mid
            else:
                high = mid
    except ValueError:
        return None
    return (low + high) / 2.0


def interpolate_fixed_maturity_iv(points: list[tuple[float, float]], target_days: int = TARGET_DAYS) -> float | None:
    clean = sorted((float(days), float(iv)) for days, iv in points if days > 0 and iv > 0)
    if not clean:
        return None
    exact = [iv for days, iv in clean if abs(days - target_days) < 1e-9]
    if exact:
        return mean(exact)

    before = [point for point in clean if point[0] < target_days]
    after = [point for point in clean if point[0] > target_days]
    if not before or not after:
        return None
    days1, iv1 = before[-1]
    days2, iv2 = after[0]
    t1, t2, target = days1 / 365.0, days2 / 365.0, target_days / 365.0
    variance1, variance2 = iv1 * iv1 * t1, iv2 * iv2 * t2
    target_variance = variance1 + (variance2 - variance1) * ((target - t1) / (t2 - t1))
    return math.sqrt(max(target_variance / target, 0.0))


def atm_iv_for_expiry(rows: list[dict[str, Any]], years: float, rate: float) -> dict[str, Any]:
    pairs: dict[float, dict[str, dict[str, Any]]] = {}
    for row in rows:
        strike = finite_float(row.get("exercise_price"))
        call_put = str(row.get("call_put") or "").upper()[:1]
        quote = finite_float(row.get("settle")) or finite_float(row.get("close"))
        open_interest = finite_float(row.get("oi"))
        if strike is None or call_put not in {"C", "P"} or quote is None or quote <= 0:
            continue
        if open_interest is not None and open_interest <= 0:
            continue
        pairs.setdefault(strike, {})[call_put] = {**row, "quote": quote}

    candidates: list[dict[str, Any]] = []
    for strike, pair in pairs.items():
        if "C" not in pair or "P" not in pair:
            continue
        forward = strike + math.exp(rate * years) * (pair["C"]["quote"] - pair["P"]["quote"])
        if forward <= 0:
            continue
        candidates.append({"strike": strike, "forward": forward, "pair": pair, "distance": abs(strike - forward)})

    if not candidates:
        return {"available": False, "reason": "no liquid matched call-put strike"}
    selected = min(candidates, key=lambda item: item["distance"])
    pair = selected["pair"]
    call_iv = implied_volatility_black76(
        pair["C"]["quote"], selected["forward"], selected["strike"], years, rate, "C"
    )
    put_iv = implied_volatility_black76(
        pair["P"]["quote"], selected["forward"], selected["strike"], years, rate, "P"
    )
    atm_iv = mean([call_iv, put_iv])
    if atm_iv is None:
        return {"available": False, "reason": "ATM implied volatility solver failed"}
    return {
        "available": True,
        "atm_iv": round(atm_iv, 8),
        "strike": selected["strike"],
        "forward": round(selected["forward"], 6),
        "call_iv": round(call_iv, 8) if call_iv is not None else None,
        "put_iv": round(put_iv, 8) if put_iv is not None else None,
        "call_code": pair["C"].get("ts_code"),
        "put_code": pair["P"].get("ts_code"),
        "call_quote": pair["C"]["quote"],
        "put_quote": pair["P"]["quote"],
    }


def downside_volatility(returns: list[float], annualization: int = 252) -> float | None:
    clean = [float(value) for value in returns if math.isfinite(float(value))]
    if not clean:
        return None
    downside_squares = [min(value, 0.0) ** 2 for value in clean]
    return math.sqrt(annualization * sum(downside_squares) / len(downside_squares))


def percentile_rank(values: list[float], current: float, zero_floor: bool = False) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    if zero_floor and current <= 0:
        return 0.0
    less = sum(value < current for value in clean)
    equal = sum(value == current for value in clean)
    return 100.0 * (less + 0.5 * equal) / len(clean)


def nested_value(payload: dict[str, Any], path: tuple[str, str]) -> float | None:
    parent = payload.get(path[0])
    if not isinstance(parent, dict):
        return None
    return finite_float(parent.get(path[1]))


def metric_percentile(
    observations: list[dict[str, Any]],
    field: str,
    basis_trade_date: str,
    lookback: int,
    minimum_sample: int,
) -> dict[str, Any]:
    path = RAW_FIELDS[field]
    eligible = [
        item
        for item in observations
        if str(item.get("basis_trade_date") or "") <= basis_trade_date and nested_value(item, path) is not None
    ][-lookback:]
    current_observation = next(
        (item for item in reversed(eligible) if item.get("basis_trade_date") == basis_trade_date), None
    )
    current = nested_value(current_observation, path) if current_observation else None
    values = [nested_value(item, path) for item in eligible]
    clean_values = [value for value in values if value is not None]
    score = (
        percentile_rank(clean_values, current, zero_floor=field in TAIL_FIELDS)
        if current is not None and len(clean_values) >= minimum_sample
        else None
    )
    return {
        "raw_value": current,
        "percentile": round(score, 4) if score is not None else None,
        "sample_count": len(clean_values),
        "minimum_sample": minimum_sample,
        "available": score is not None,
    }


def weighted_score(items: list[tuple[float | None, float]]) -> float | None:
    valid = [(float(score), weight) for score, weight in items if score is not None]
    total_weight = sum(weight for _, weight in valid)
    if not valid or total_weight <= 0:
        return None
    return sum(score * weight for score, weight in valid) / total_weight


def fear_level(score: float | None) -> dict[str, str]:
    if score is None:
        return {"code": "unavailable", "label": "不可用"}
    bands = [
        (20, "calm", "平静"),
        (40, "normal", "正常"),
        (60, "watch", "警觉"),
        (80, "high", "高恐慌"),
        (101, "extreme", "极端恐慌"),
    ]
    for upper, code, label in bands:
        if score < upper:
            return {"code": code, "label": label}
    return {"code": "extreme", "label": "极端恐慌"}


def fear_phase(score: float | None, change_1d: float | None, change_3d: float | None) -> dict[str, str]:
    if score is None:
        return {"code": "unavailable", "label": "不可用"}
    delta1 = change_1d or 0.0
    delta3 = change_3d or 0.0
    if score >= 80 and delta3 <= -5:
        return {"code": "extreme_easing", "label": "高位缓和"}
    if score >= 80 and (delta1 >= 5 or delta3 >= 8):
        return {"code": "panic_accelerating", "label": "恐慌加速"}
    if score >= 80:
        return {"code": "extreme", "label": "极端维持"}
    if delta1 >= 5 or delta3 >= 8:
        return {"code": "fear_rising", "label": "恐慌升温"}
    if delta1 <= -5 or delta3 <= -8:
        return {"code": "fear_easing", "label": "恐慌缓和"}
    return {"code": "stable", "label": "变化平稳"}


def score_observation(
    observation: dict[str, Any],
    observations: list[dict[str, Any]],
    previous_records: list[dict[str, Any]] | None = None,
    lookback: int = LOOKBACK_DAYS,
    minimum_sample: int = MIN_SAMPLE_COUNT,
) -> dict[str, Any]:
    basis_trade_date = str(observation["basis_trade_date"])
    eligible = sorted(
        [item for item in observations if str(item.get("basis_trade_date") or "") <= basis_trade_date],
        key=lambda item: str(item.get("basis_trade_date")),
    )
    metrics = {
        field: metric_percentile(eligible, field, basis_trade_date, lookback, minimum_sample)
        for field in RAW_FIELDS
    }

    iv_score = mean([metrics["io_iv_30d"]["percentile"], metrics["mo_iv_30d"]["percentile"]])
    downside_score = mean(
        [
            metrics["csi300_downside_vol_20d"]["percentile"],
            metrics["csi1000_downside_vol_20d"]["percentile"],
        ]
    )
    breadth_score = weighted_score(
        [
            (metrics["decliner_ratio"]["percentile"], 0.40),
            (metrics["decline_beyond_3pct_ratio"]["percentile"], 0.40),
            (metrics["limit_down_ratio"]["percentile"], 0.20),
        ]
    )
    csi300_tail = weighted_score(
        [
            (metrics["csi300_loss_1d"]["percentile"], 0.50),
            (metrics["csi300_loss_5d"]["percentile"], 0.50),
        ]
    )
    csi1000_tail = weighted_score(
        [
            (metrics["csi1000_loss_1d"]["percentile"], 0.50),
            (metrics["csi1000_loss_5d"]["percentile"], 0.50),
        ]
    )
    tail_score = mean([csi300_tail, csi1000_tail])

    components = {
        "implied_volatility": {"score": iv_score, "weight": COMPONENT_WEIGHTS["implied_volatility"]},
        "downside_volatility": {"score": downside_score, "weight": COMPONENT_WEIGHTS["downside_volatility"]},
        "market_breadth": {"score": breadth_score, "weight": COMPONENT_WEIGHTS["market_breadth"]},
        "tail_loss": {"score": tail_score, "weight": COMPONENT_WEIGHTS["tail_loss"]},
    }
    io_available = metrics["io_iv_30d"]["available"]
    mo_available = metrics["mo_iv_30d"]["available"]
    official = bool(io_available or mo_available)
    non_iv_scores = [downside_score, breadth_score, tail_score]
    realized_proxy = weighted_score(
        [
            (downside_score, COMPONENT_WEIGHTS["downside_volatility"]),
            (breadth_score, COMPONENT_WEIGHTS["market_breadth"]),
            (tail_score, COMPONENT_WEIGHTS["tail_loss"]),
        ]
    )
    fear_score = weighted_score([(item["score"], item["weight"]) for item in components.values()]) if official else None
    if not official and sum(score is not None for score in non_iv_scores) < 2:
        realized_proxy = None

    previous = sorted(
        [item for item in (previous_records or []) if str(item.get("basis_trade_date") or "") < basis_trade_date],
        key=lambda item: str(item.get("basis_trade_date")),
    )
    active_score = fear_score if fear_score is not None else realized_proxy
    prior_scores = [
        finite_float(item.get("fear_score") if item.get("fear_score") is not None else item.get("realized_fear_proxy"))
        for item in previous
    ]
    prior_scores = [score for score in prior_scores if score is not None]
    change_1d = active_score - prior_scores[-1] if active_score is not None and prior_scores else None
    change_3d = active_score - prior_scores[-3] if active_score is not None and len(prior_scores) >= 3 else None

    io_mo_count = int(io_available) + int(mo_available)
    all_non_iv = all(score is not None for score in non_iv_scores)
    minimum_metric_sample = min((item["sample_count"] for item in metrics.values()), default=0)
    if official and io_mo_count == 2 and all_non_iv and minimum_metric_sample >= 500:
        confidence = "high"
    elif official:
        confidence = "medium"
    elif realized_proxy is not None:
        confidence = "low"
    else:
        confidence = "unavailable"

    fear_300 = weighted_score(
        [
            (metrics["io_iv_30d"]["percentile"], 0.50),
            (metrics["csi300_downside_vol_20d"]["percentile"], 0.25),
            (csi300_tail, 0.25),
        ]
    )
    fear_1000 = weighted_score(
        [
            (metrics["mo_iv_30d"]["percentile"], 0.50),
            (metrics["csi1000_downside_vol_20d"]["percentile"], 0.25),
            (csi1000_tail, 0.25),
        ]
    )
    scoring_context = {
        "observation": observation,
        "trailing_observation_hashes": [
            hashlib.sha256(
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for item in eligible[-lookback:]
        ],
        "lookback": lookback,
        "minimum_sample": minimum_sample,
    }
    canonical_input = json.dumps(scoring_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()
    generated_at = datetime.now(TZ).isoformat(timespec="seconds")
    level = fear_level(active_score)
    phase = fear_phase(active_score, change_1d, change_3d)
    missing_fields = [field for field, item in metrics.items() if not item["available"]]
    warnings = list(observation.get("data_quality", {}).get("warnings", []))
    if not official:
        warnings.append("Both IO and MO fixed-30-day IV are unavailable; official A-FEAR is not published.")
    elif io_mo_count == 1:
        warnings.append("Only one option family is available; A-FEAR confidence is reduced.")

    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "basis_trade_date": basis_trade_date,
        "generated_at": generated_at,
        "run_id": f"{VERSION}-{basis_trade_date}-{input_hash[:12]}",
        "input_hash": input_hash,
        "official": official,
        "fear_score": round(fear_score, 4) if fear_score is not None else None,
        "realized_fear_proxy": round(realized_proxy, 4) if realized_proxy is not None else None,
        "change_1d": round(change_1d, 4) if change_1d is not None else None,
        "change_3d": round(change_3d, 4) if change_3d is not None else None,
        "level": level,
        "phase": phase,
        "confidence": confidence,
        "components": {
            key: {**value, "score": round(value["score"], 4) if value["score"] is not None else None}
            for key, value in components.items()
        },
        "metrics": metrics,
        "fear_300": round(fear_300, 4) if fear_300 is not None else None,
        "fear_1000": round(fear_1000, 4) if fear_1000 is not None else None,
        "small_cap_fear_spread": round(fear_1000 - fear_300, 4)
        if fear_300 is not None and fear_1000 is not None
        else None,
        "data_quality": {
            "missing_fields": missing_fields,
            "warnings": list(dict.fromkeys(warnings)),
            "source_dates": observation.get("source_dates", {}),
        },
        "safety": {
            "read_only_indicator": True,
            "changes_position_recommendation": False,
            "note": "A-FEAR measures fear intensity; it is not a buy score.",
        },
    }


def score_observation_series(
    observations: list[dict[str, Any]],
    lookback: int = LOOKBACK_DAYS,
    minimum_sample: int = MIN_SAMPLE_COUNT,
) -> list[dict[str, Any]]:
    ordered = sorted(observations, key=lambda item: str(item.get("basis_trade_date")))
    records: list[dict[str, Any]] = []
    for observation in ordered:
        records.append(
            score_observation(
                observation,
                ordered,
                previous_records=records,
                lookback=lookback,
                minimum_sample=minimum_sample,
            )
        )
    return records


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "version": VERSION, "records": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("A-FEAR history must be an object with a records array")
    return payload


def append_record(
    record: dict[str, Any],
    history_path: Path = DEFAULT_HISTORY_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
) -> dict[str, Any]:
    history = load_history(history_path)
    records = history["records"]
    same_day = next(
        (
            item
            for item in records
            if item.get("version") == record.get("version")
            and item.get("basis_trade_date") == record.get("basis_trade_date")
        ),
        None,
    )
    if same_day:
        if same_day.get("input_hash") != record.get("input_hash"):
            return {"appended": False, "duplicate": False, "conflict": True, "record": same_day}
        latest_path.write_text(json.dumps(same_day, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"appended": False, "duplicate": True, "conflict": False, "record": same_day}

    records.append(record)
    records.sort(key=lambda item: str(item.get("basis_trade_date")))
    payload = {"schema_version": SCHEMA_VERSION, "version": VERSION, "records": records}
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"appended": True, "duplicate": False, "conflict": False, "record": record}
