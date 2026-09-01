from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import a_fear


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_JSON_PATH = DATA_DIR / "a_fear_audit_latest.json"
DEFAULT_MARKDOWN_PATH = DATA_DIR / "a_fear_audit_latest.md"


def rounded(value: Any, digits: int = 4) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def latest_broad_panic_check(latest: dict[str, Any]) -> dict[str, Any]:
    """Require breadth/tail confirmation only when the latest score is extreme."""
    fear_score = rounded(latest.get("fear_score"))
    components = latest.get("components") or {}
    breadth_score = rounded((components.get("market_breadth") or {}).get("score")) or 0.0
    tail_score = rounded((components.get("tail_loss") or {}).get("score")) or 0.0
    if fear_score is None or fear_score < 80:
        return {
            "key": "latest_broad_panic_consistency",
            "passed": True,
            "detail": "Latest score is below the extreme-panic threshold; breadth/tail confirmation is not required.",
        }
    return {
        "key": "latest_broad_panic_consistency",
        "passed": breadth_score >= 80 and tail_score >= 80,
        "detail": (
            "Latest extreme reading is confirmed by both breadth and tail-loss components."
            if breadth_score >= 80 and tail_score >= 80
            else "Latest extreme reading lacks simultaneous breadth and tail-loss confirmation."
        ),
    }


def build_audit() -> dict[str, Any]:
    history = a_fear.load_history(a_fear.DEFAULT_HISTORY_PATH)
    records = history.get("records", [])
    source = json.loads(a_fear.DEFAULT_SOURCE_CACHE_PATH.read_text(encoding="utf-8-sig"))
    observations = source.get("observations", [])
    official = [record for record in records if record.get("fear_score") is not None]

    rows = []
    for record in official:
        components = record.get("components", {})
        rows.append(
            {
                "date": record.get("basis_trade_date"),
                "fear_score": record.get("fear_score"),
                **{
                    key: (components.get(key) or {}).get("score")
                    for key in a_fear.COMPONENT_WEIGHTS
                },
            }
        )
    frame = pd.DataFrame(rows)
    score_series = pd.to_numeric(frame.get("fear_score"), errors="coerce")
    component_columns = list(a_fear.COMPONENT_WEIGHTS)
    correlations = frame[component_columns].corr(method="spearman") if not frame.empty else pd.DataFrame()
    component_pairs: list[dict[str, Any]] = []
    for index, left in enumerate(component_columns):
        for right in component_columns[index + 1 :]:
            component_pairs.append(
                {"left": left, "right": right, "spearman": rounded(correlations.loc[left, right])}
            )
    highest_component_correlation = max(
        (abs(item["spearman"]) for item in component_pairs if item["spearman"] is not None),
        default=None,
    )

    absolute_changes = score_series.diff().abs()
    jumps = []
    for row_index in absolute_changes.loc[absolute_changes > 30].index:
        jumps.append(
            {
                "basis_trade_date": frame.loc[row_index, "date"],
                "fear_score": rounded(frame.loc[row_index, "fear_score"]),
                "previous_fear_score": rounded(frame.loc[row_index - 1, "fear_score"]) if row_index > 0 else None,
                "absolute_change": rounded(absolute_changes.loc[row_index]),
            }
        )
    jumps.sort(key=lambda item: item["absolute_change"], reverse=True)

    option_complete = sum(
        (item.get("implied_volatility") or {}).get("io_iv_30d") is not None
        and (item.get("implied_volatility") or {}).get("mo_iv_30d") is not None
        for item in observations
    )
    latest = official[-1] if official else (records[-1] if records else {})
    top = sorted(official, key=lambda item: item["fear_score"], reverse=True)[:10]
    bottom = sorted(official, key=lambda item: item["fear_score"])[:10]
    jump_ratio = len(jumps) / len(official) if official else None

    checks = [
        {
            "key": "source_history_depth",
            "passed": len(observations) >= a_fear.LOOKBACK_DAYS,
            "detail": f"{len(observations)} source observations; target {a_fear.LOOKBACK_DAYS}.",
        },
        {
            "key": "official_history_depth",
            "passed": len(official) >= 400,
            "detail": f"{len(official)} official daily scores after the minimum-sample warm-up.",
        },
        {
            "key": "latest_is_official",
            "passed": bool(latest.get("official") and latest.get("fear_score") is not None),
            "detail": f"Latest {latest.get('basis_trade_date')} score={latest.get('fear_score')} confidence={latest.get('confidence')}.",
        },
        {
            "key": "score_bounds",
            "passed": bool(not score_series.empty and score_series.between(0, 100).all()),
            "detail": f"Observed range {rounded(score_series.min())}..{rounded(score_series.max())}.",
        },
        {
            "key": "component_independence",
            "passed": bool(highest_component_correlation is not None and highest_component_correlation < 0.90),
            "detail": f"Highest absolute pairwise component Spearman correlation={rounded(highest_component_correlation)}.",
        },
        {
            "key": "jump_frequency",
            "passed": bool(jump_ratio is not None and jump_ratio <= 0.05),
            "detail": f"Absolute one-day changes above 30: {len(jumps)}/{len(official)} ({rounded((jump_ratio or 0) * 100, 2)}%).",
        },
        latest_broad_panic_check(latest),
    ]

    return {
        "schema_version": 1,
        "version": a_fear.VERSION,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "passed": all(check["passed"] for check in checks),
        "summary": {
            "source_observation_count": len(observations),
            "option_complete_observation_count": option_complete,
            "record_count": len(records),
            "official_record_count": len(official),
            "official_start_date": official[0].get("basis_trade_date") if official else None,
            "latest_basis_trade_date": latest.get("basis_trade_date"),
            "latest_fear_score": latest.get("fear_score"),
            "latest_level": latest.get("level"),
            "latest_phase": latest.get("phase"),
            "latest_confidence": latest.get("confidence"),
            "score_min": rounded(score_series.min()) if not score_series.empty else None,
            "score_median": rounded(score_series.median()) if not score_series.empty else None,
            "score_max": rounded(score_series.max()) if not score_series.empty else None,
            "jump_count_over_30": len(jumps),
            "jump_ratio_over_30": rounded(jump_ratio),
            "highest_component_correlation": rounded(highest_component_correlation),
        },
        "checks": checks,
        "component_correlations": component_pairs,
        "largest_jumps": jumps[:20],
        "highest_fear_dates": [
            {"basis_trade_date": item.get("basis_trade_date"), "fear_score": item.get("fear_score")}
            for item in top
        ],
        "lowest_fear_dates": [
            {"basis_trade_date": item.get("basis_trade_date"), "fear_score": item.get("fear_score")}
            for item in bottom
        ],
        "limitations": [
            "This is an implementation and behavior audit, not evidence that A-FEAR predicts future returns.",
            "The first official score appears only after the 250-observation warm-up and sufficient option-IV history.",
            "Large daily changes are retained because the indicator is intended to react to panic shocks; they require live monitoring.",
            "A-FEAR v1 remains observational and does not modify the official position recommendation.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# A-FEAR v1 Audit",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Passed: {report['passed']}",
        f"- Source observations: {summary['source_observation_count']}",
        f"- Complete IO/MO observations: {summary['option_complete_observation_count']}",
        f"- Official scores: {summary['official_record_count']}",
        f"- Latest: {summary['latest_basis_trade_date']} / {summary['latest_fear_score']} / {summary['latest_confidence']}",
        f"- Score range: {summary['score_min']} .. {summary['score_max']}",
        "",
        "## Checks",
        "",
        "| Check | Passed | Detail |",
        "|---|---:|---|",
    ]
    lines.extend(f"| {item['key']} | {item['passed']} | {item['detail']} |" for item in report["checks"])
    lines.extend(["", "## Largest One-Day Changes", "", "| Date | Previous | Current | Absolute change |", "|---|---:|---:|---:|"])
    lines.extend(
        f"| {item['basis_trade_date']} | {item['previous_fear_score']} | {item['fear_score']} | {item['absolute_change']} |"
        for item in report["largest_jumps"]
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def write_audit() -> dict[str, Any]:
    report = build_audit()
    DEFAULT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DEFAULT_MARKDOWN_PATH.write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    report = write_audit()
    print(json.dumps(report["summary"] | {"passed": report["passed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
