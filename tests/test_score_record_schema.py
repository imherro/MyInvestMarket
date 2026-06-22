from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import run_post_close_update  # noqa: E402


def valid_modules() -> dict:
    return {
        key: {
            "label": meta["label"],
            "weight": meta["weight"],
            "score": round(meta["weight"] * 0.6, 2),
            "score_pct": 60,
            "summary": "test module",
            "evidence": [],
            "metrics": {},
        }
        for key, meta in market_scoring.MODULES.items()
    }


def valid_score_record() -> dict:
    return {
        "run_id": "schema-test-run",
        "model_version": market_scoring.MODEL_VERSION,
        "score_schema_version": market_scoring.SCORE_SCHEMA_VERSION,
        "feature_schema_version": market_scoring.FEATURE_SCHEMA_VERSION,
        "account_scope": "stock_account",
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
        "scored_at": "2026-06-22T16:00:00+08:00",
        "basis_trade_date": "2026-06-18",
        "snapshot_sha256": "abc123",
        "market_regime": "中性震荡偏结构",
        "market_opportunity_score": 60,
        "opportunity_score": 60,
        "crowding_penalty": 10,
        "pre_cap_market_position_score": 50,
        "market_position_score": 50,
        "base_market_position_score": 50,
        "recommended_equity_position_range": "40%-60%",
        "equity_position_range": "40%-60%",
        "base_equity_position_range": "40%-60%",
        "confidence": "high",
        "risk_caps": [],
        "modules": valid_modules(),
        "crowding": {"penalty": 10, "items": []},
        "data_quality": {"missing_fields": [], "warnings": []},
    }


class ScoreRecordSchemaTest(unittest.TestCase):
    def test_validate_score_record_accepts_valid_record(self) -> None:
        validation = market_scoring.validate_score_record(valid_score_record())

        self.assertTrue(validation["ok"])
        self.assertIn("market_position_score", validation["checked_required_fields"])

    def test_append_rejects_missing_required_field_without_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            valid = market_scoring.append_score_record(valid_score_record(), history_path)
            invalid = valid_score_record()
            invalid["run_id"] = "missing-field-run"
            invalid.pop("basis_trade_date")

            with self.assertRaisesRegex(market_scoring.ScoreRecordValidationError, "basis_trade_date"):
                market_scoring.append_score_record(invalid, history_path)

            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertTrue(valid["appended"])
        self.assertEqual(len(saved["records"]), 1)
        self.assertEqual(saved["records"][0]["run_id"], "schema-test-run")

    def test_append_rejects_out_of_range_score_without_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            market_scoring.append_score_record(valid_score_record(), history_path)
            invalid = valid_score_record()
            invalid["run_id"] = "bad-score-run"
            invalid["snapshot_sha256"] = "bad-score"
            invalid["market_position_score"] = 101

            with self.assertRaisesRegex(market_scoring.ScoreRecordValidationError, "market_position_score"):
                market_scoring.append_score_record(invalid, history_path)

            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertEqual(len(saved["records"]), 1)

    def test_append_rejects_invalid_position_range_without_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            market_scoring.append_score_record(valid_score_record(), history_path)
            invalid = valid_score_record()
            invalid["run_id"] = "bad-range-run"
            invalid["snapshot_sha256"] = "bad-range"
            invalid["recommended_equity_position_range"] = "120%-130%"

            with self.assertRaisesRegex(market_scoring.ScoreRecordValidationError, "recommended_equity_position_range"):
                market_scoring.append_score_record(invalid, history_path)

            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertEqual(len(saved["records"]), 1)

    def test_post_close_append_score_rejects_invalid_scoring_output_without_history_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            invalid = valid_score_record()
            invalid.pop("run_id")

            with (
                patch.object(run_post_close_update.market_scoring, "DEFAULT_HISTORY_PATH", history_path),
                patch.object(run_post_close_update.market_scoring, "score_snapshot", return_value=invalid),
            ):
                with self.assertRaisesRegex(market_scoring.ScoreRecordValidationError, "run_id"):
                    run_post_close_update.append_score({}, Path(tmp_dir) / "snapshot.json", b"{}")

            self.assertFalse(history_path.exists())


if __name__ == "__main__":
    unittest.main()
