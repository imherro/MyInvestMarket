from __future__ import annotations

import json
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
