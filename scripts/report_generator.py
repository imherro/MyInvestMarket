from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import backtest_engine
import parameter_calibration


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")


def build_validation_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    comparison = backtest_engine.compare_backtests(records)
    calibration = parameter_calibration.run_parameter_calibration(records)
    v3 = comparison.get("v3", {})
    return {
        "schema_version": 1,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "title": "MyInvestMarket Phase 6 Backtesting & Model Validation",
        "available": bool(v3.get("available")),
        "sample": {
            "record_count": v3.get("record_count"),
            "return_count": v3.get("return_count"),
            "signal_delay_bars": v3.get("signal_delay_bars"),
            "lookahead_safe": v3.get("lookahead_safe"),
        },
        "comparison": comparison,
        "calibration": calibration,
        "limitations": _limitations(comparison),
    }


def write_validation_report(
    records: list[dict[str, Any]],
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    report = build_validation_report(records)
    timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    markdown_path = markdown_path or DATA_DIR / f"model_validation_{timestamp}.md"
    json_path = json_path or DATA_DIR / "model_validation_latest.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_markdown = DATA_DIR / "model_validation_latest.md"
    latest_markdown.write_text(render_markdown(report), encoding="utf-8")
    return {
        "report": report,
        "markdown_path": str(markdown_path),
        "latest_markdown_path": str(latest_markdown),
        "json_path": str(json_path),
    }


def render_markdown(report: dict[str, Any]) -> str:
    comparison = report.get("comparison", {})
    v3 = comparison.get("v3", {})
    v2 = comparison.get("v2_proxy", {})
    improvement = comparison.get("improvement", {})
    calibration = report.get("calibration", {})
    lines = [
        "# MyInvestMarket Phase 6 Backtesting & Model Validation",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Available: {report.get('available')}",
        f"- Signal delay bars: {(report.get('sample') or {}).get('signal_delay_bars')}",
        f"- Lookahead safe: {(report.get('sample') or {}).get('lookahead_safe')}",
        "",
        "## v3 vs v2 Proxy",
        "",
        "| Metric | v3 | v2 proxy | Delta |",
        "|---|---:|---:|---:|",
    ]
    for field in ["total_return", "cagr", "sharpe_ratio", "max_drawdown", "calmar_ratio", "turnover", "win_rate"]:
        lines.append(
            f"| {field} | {_fmt(((v3.get('metrics') or {}).get(field)))} | "
            f"{_fmt(((v2.get('metrics') or {}).get(field)))} | {_fmt(improvement.get(field))} |"
        )
    lines.extend(
        [
            "",
            "## Regime Contribution",
            "",
            "| Regime | Count | Avg Return | Hit Rate |",
            "|---|---:|---:|---:|",
        ]
    )
    for key, value in ((v3.get("regime_hit_return_map") or {}).items()):
        lines.append(f"| {key} | {_fmt(value.get('count'))} | {_fmt(value.get('avg_return'))} | {_fmt(value.get('hit_rate'))} |")
    trend = v3.get("trend_state_alpha_contribution") or {}
    lines.extend(["", "## Trend Contribution", "", "| Trend | Count | Avg Return | Alpha vs Avg |", "|---|---:|---:|---:|"])
    for key, value in ((trend.get("by_trend_state") or {}).items()):
        lines.append(
            f"| {key} | {_fmt(value.get('count'))} | {_fmt(value.get('avg_return'))} | {_fmt(value.get('alpha_vs_all_avg'))} |"
        )
    risk = v3.get("risk_cap_reduction_effect") or {}
    lines.extend(
        [
            "",
            "## Risk Engine Effect",
            "",
            f"- High risk sample count: {risk.get('sample_count')}",
            f"- Actual max drawdown: {_fmt(risk.get('actual_max_drawdown'))}",
            f"- Baseline max drawdown: {_fmt(risk.get('baseline_max_drawdown'))}",
            f"- Drawdown reduction: {_fmt(risk.get('drawdown_reduction'))}",
            "",
            "## Calibration Sensitivity",
            "",
            f"- Available: {calibration.get('available')}",
            f"- Tested count: {calibration.get('tested_count')}",
            f"- Best params: `{json.dumps(calibration.get('best_params', {}), ensure_ascii=False)}`",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    return "\n".join(lines) + "\n"


def _limitations(comparison: dict[str, Any]) -> list[str]:
    v3 = comparison.get("v3", {})
    count = int(v3.get("return_count") or 0)
    notes = [
        "Backtest uses close-to-close Shanghai Composite returns and score-derived stock-account exposure.",
        "All positions are shifted by one bar to avoid lookahead bias.",
    ]
    if count < 30:
        notes.append("The current repository has a short real score history; statistical claims require more post-close records.")
    if not comparison.get("available"):
        notes.append("v3/v2 comparison is unavailable until at least two dated score records with index closes exist.")
    return notes


def _fmt(value: Any) -> str:
    number = backtest_engine.as_float(value)
    if number is None:
        return "--"
    return f"{number:.4f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Phase 6 validation report.")
    parser.add_argument("--history", default=str(backtest_engine.DEFAULT_HISTORY_PATH), help="Score history JSON path.")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = backtest_engine.load_history_records(Path(args.history), include_legacy=args.include_legacy)
    result = write_validation_report(records)
    print(json.dumps({key: value for key, value in result.items() if key != "report"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
