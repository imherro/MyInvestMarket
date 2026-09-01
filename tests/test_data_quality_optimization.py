from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_market_dataset  # noqa: E402
import run_post_close_update  # noqa: E402


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "result": {
                "data": [
                    {"SOLAR_DATE": "2026-06-22", "EMM00166466": 1.7375},
                    {"SOLAR_DATE": "2026-06-23", "EMM00166466": 1.75},
                ]
            }
        }


class DataQualityOptimizationTest(unittest.TestCase):
    def test_china_10y_fallback_success_does_not_mark_tushare_subsource_missing(self) -> None:
        class Pro:
            def yc_cb(self, **_: object) -> pd.DataFrame:
                raise RuntimeError("permission denied")

        q = build_market_dataset.Quality()
        with patch.object(build_market_dataset.requests, "get", return_value=FakeResponse()):
            result = build_market_dataset.china_10y_yield(Pro(), q, date(2026, 6, 22))

        self.assertEqual(result["source"], "Eastmoney:RPTA_WEB_TREASURYYIELD")
        self.assertEqual(result["value_pct"], 1.7375)
        self.assertNotIn("macro.china_10y_government_bond_yield_pct.tushare_yc_cb", q.missing_fields)
        self.assertEqual(q.missing_fields, [])
        self.assertTrue(any("Eastmoney fallback used" in note for note in q.notes))

    def test_qmt_probe_is_optional_for_market_score_quality(self) -> None:
        q = build_market_dataset.Quality()
        with patch("importlib.util.find_spec", return_value=None):
            result = build_market_dataset.qmt_portfolio(q)

        self.assertFalse(result["available"])
        self.assertEqual(q.missing_fields, [])
        self.assertTrue(any("optional qmt_portfolio.positions" in note for note in q.notes))

    def test_bse50_valuation_gap_is_optional_not_market_missing(self) -> None:
        class Pro:
            def index_dailybasic(self, ts_code: str, **_: object) -> pd.DataFrame:
                if ts_code == "899050.BJ":
                    return pd.DataFrame()
                return pd.DataFrame(
                    [
                        {"trade_date": "20260621", "pe_ttm": 20.0, "pb": 2.0},
                        {"trade_date": "20260622", "pe_ttm": 18.0, "pb": 1.8},
                    ]
                )

        q = build_market_dataset.Quality()
        result = build_market_dataset.index_valuation(Pro(), "20260622", q)

        self.assertNotIn("valuation.indices.899050.BJ", q.missing_fields)
        self.assertTrue(any("optional valuation.indices.899050.BJ" in note for note in q.notes))
        self.assertNotIn("899050.BJ", result["indices"])
        self.assertIsNotNone(result["market"]["valuation_score"])

    def test_backfill_recent_market_snapshots_only_writes_missing_prior_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            existing = data_dir / "market_snapshot_2026-06-18.json"
            existing.write_text("{}\n", encoding="utf-8")

            def dataset_for(as_of: date) -> dict:
                return {"date": as_of.isoformat(), "data_quality": {"missing_fields": [], "warnings": []}}

            with (
                patch.object(run_post_close_update, "DATA_DIR", data_dir),
                patch.object(
                    run_post_close_update,
                    "recent_complete_trade_dates",
                    return_value=["20260616", "20260617", "20260618", "20260619", "20260622"],
                ),
                patch.object(run_post_close_update.build_market_dataset, "build_dataset", side_effect=dataset_for),
            ):
                paths = run_post_close_update.backfill_recent_market_snapshots(date(2026, 6, 22), "2026-06-22")

            self.assertEqual(
                [path.name for path in paths],
                [
                    "market_snapshot_2026-06-16.json",
                    "market_snapshot_2026-06-17.json",
                    "market_snapshot_2026-06-19.json",
                ],
            )
            self.assertFalse((data_dir / "market_snapshot_2026-06-22.json").exists())
            for path in paths:
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["date"], path.stem.removeprefix("market_snapshot_"))

    def test_backfilled_snapshot_scores_are_appended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            first = data_dir / "market_snapshot_2026-07-03.json"
            second = data_dir / "market_snapshot_2026-07-06.json"
            first.write_text(json.dumps({"date": "2026-07-03"}) + "\n", encoding="utf-8")
            second.write_text(json.dumps({"date": "2026-07-06"}) + "\n", encoding="utf-8")

            def append_stub(snapshot: dict, snapshot_path: Path, snapshot_bytes: bytes) -> dict:
                trade_date = snapshot["date"]
                return {
                    "appended": trade_date == "2026-07-03",
                    "duplicate": trade_date == "2026-07-06",
                    "duplicate_of_run_id": "old-run" if trade_date == "2026-07-06" else None,
                    "record": {
                        "basis_trade_date": trade_date,
                        "run_id": f"run-{trade_date}",
                        "market_position_score": 35,
                        "recommended_equity_position_range": "20%-40%",
                    },
                }

            with patch.object(run_post_close_update, "append_score", side_effect=append_stub):
                results = run_post_close_update.append_backfilled_scores([second, first])

            self.assertEqual([item["basis_trade_date"] for item in results], ["2026-07-03", "2026-07-06"])
            self.assertTrue(results[0]["appended"])
            self.assertTrue(results[1]["duplicate"])
            self.assertEqual(results[1]["duplicate_of_run_id"], "old-run")

    def test_history_backfill_only_builds_missing_score_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)

            def dataset_for(as_of: date) -> dict:
                return {"date": as_of.isoformat(), "data_quality": {"missing_fields": [], "warnings": []}}

            def append_stub(snapshot: dict, snapshot_path: Path, snapshot_bytes: bytes) -> dict:
                self.assertEqual(snapshot["date"], "2026-08-13")
                self.assertTrue(snapshot_path.name.endswith("2026-08-13.json"))
                self.assertTrue(snapshot_bytes)
                return {
                    "appended": True,
                    "duplicate": False,
                    "record": {
                        "basis_trade_date": "2026-08-13",
                        "run_id": "backfill-2026-08-13",
                        "market_opportunity_score": 61.2,
                        "market_position_score": 48.0,
                        "recommended_equity_position_range": "40%-60%",
                    },
                }

            with (
                patch.object(run_post_close_update, "DATA_DIR", data_dir),
                patch.object(
                    run_post_close_update,
                    "complete_trade_dates_between",
                    return_value=(["2026-08-12", "2026-08-13"], []),
                ),
                patch.object(
                    run_post_close_update.market_scoring,
                    "load_history",
                    return_value={"records": [{"basis_trade_date": "2026-08-12"}]},
                ),
                patch.object(run_post_close_update.build_market_dataset, "build_dataset", side_effect=dataset_for),
                patch.object(run_post_close_update, "append_score", side_effect=append_stub),
            ):
                result = run_post_close_update.score_history_backfill(date(2026, 8, 12), date(2026, 8, 13))

            self.assertEqual(result["skipped"], [{"basis_trade_date": "2026-08-12", "reason": "score record already exists"}])
            self.assertEqual([row["basis_trade_date"] for row in result["scored"]], ["2026-08-13"])
            self.assertEqual([path.name for path in result["written_snapshot_paths"]], ["market_snapshot_2026-08-13.json"])
            self.assertFalse((data_dir / "latest_market_snapshot.json").exists())

    def test_history_backfill_summary_serializes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            snapshot_path = data_dir / "market_snapshot_2026-08-13.json"
            manifest_path = data_dir / "market_history_backfill_2026-08-13_2026-08-13.json"
            audit_path = data_dir / "market_score_history_audit.jsonl"
            report_path = data_dir / "model_validation_20260813_090000.md"
            latest_report_path = data_dir / "model_validation_latest.md"
            validation_json_path = data_dir / "model_validation_latest.json"
            result = {
                "requested_range": {"start_date": "2026-08-13", "end_date": "2026-08-13"},
                "written_snapshot_paths": [snapshot_path],
                "scored": [],
            }
            validation = {
                "report": {"available": True},
                "markdown_path": str(report_path),
                "latest_markdown_path": str(latest_report_path),
                "json_path": str(validation_json_path),
            }
            output = io.StringIO()
            with (
                patch.object(run_post_close_update, "score_history_backfill", return_value=result),
                patch.object(run_post_close_update, "write_history_backfill_manifest", return_value=manifest_path),
                patch.object(run_post_close_update.report_generator, "write_validation_report", return_value=validation),
                patch.object(run_post_close_update, "backtest_engine_records", return_value=[]),
                patch.object(run_post_close_update, "verify_api", return_value={"validation": {"ok": True}}),
                patch.object(run_post_close_update.market_scoring, "history_audit_log_path", return_value=audit_path),
                patch.object(run_post_close_update, "commit_and_push", return_value={"skipped": True}),
                redirect_stdout(output),
            ):
                run_post_close_update.run_history_backfill(date(2026, 8, 13), date(2026, 8, 13), no_git=True)

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["written_snapshot_paths"], [str(snapshot_path)])


if __name__ == "__main__":
    unittest.main()
