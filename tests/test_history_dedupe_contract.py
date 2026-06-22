from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402


def score_record(
    run_id: str,
    *,
    trade_date: str = "2026-06-18",
    snapshot_sha256: str = "abc123",
    model_version: str | None = None,
    position_policy_version: str | None = None,
) -> dict:
    modules = {
        key: {
            "label": meta["label"],
            "weight": meta["weight"],
            "score": meta["weight"] * 0.5,
            "score_pct": 50,
            "summary": "test",
            "evidence": [],
            "metrics": {},
        }
        for key, meta in market_scoring.MODULES.items()
    }
    return {
        "run_id": run_id,
        "scored_at": f"2026-06-22T16:00:0{run_id[-1]}+08:00",
        "basis_trade_date": trade_date,
        "snapshot_sha256": snapshot_sha256,
        "model_version": model_version or market_scoring.MODEL_VERSION,
        "position_policy_version": position_policy_version or market_scoring.POSITION_POLICY_VERSION,
        "account_scope": "stock_account",
        "market_regime": "中性震荡偏结构",
        "market_opportunity_score": 50,
        "opportunity_score": 50,
        "crowding_penalty": 15,
        "pre_cap_market_position_score": 35,
        "market_position_score": 35,
        "base_market_position_score": 35,
        "recommended_equity_position_range": "20%-40%",
        "base_equity_position_range": "20%-40%",
        "equity_position_range": "20%-40%",
        "confidence": "medium",
        "risk_caps": [],
        "modules": modules,
        "crowding": {"penalty": 15, "items": []},
        "data_quality": {"missing_fields": [], "warnings": []},
    }


class HistoryDedupeContractTest(unittest.TestCase):
    def test_same_trade_date_snapshot_model_and_policy_are_not_appended_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            first = market_scoring.append_score_record(score_record("run-1"), history_path)
            duplicate = market_scoring.append_score_record(score_record("run-2"), history_path)
            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertTrue(first["appended"])
        self.assertFalse(duplicate["appended"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["record"]["run_id"], "run-1")
        self.assertEqual(duplicate["candidate_record"]["run_id"], "run-2")
        self.assertEqual(duplicate["duplicate_of_run_id"], "run-1")
        self.assertEqual(len(saved["records"]), 1)
        self.assertEqual(saved["records"][0]["run_id"], "run-1")

    def test_version_fields_isolate_history_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            first = market_scoring.append_score_record(score_record("run-1"), history_path)
            new_model = market_scoring.append_score_record(
                score_record("run-2", model_version=f"{market_scoring.MODEL_VERSION}_next"),
                history_path,
            )
            new_policy = market_scoring.append_score_record(
                score_record("run-3", position_policy_version=f"{market_scoring.POSITION_POLICY_VERSION}_next"),
                history_path,
            )
            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertTrue(first["appended"])
        self.assertTrue(new_model["appended"])
        self.assertTrue(new_policy["appended"])
        self.assertEqual([row["run_id"] for row in saved["records"]], ["run-1", "run-2", "run-3"])

    def test_missing_key_fields_are_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            invalid = score_record("run-1")
            invalid.pop("position_policy_version")
            with self.assertRaisesRegex(market_scoring.ScoreRecordValidationError, "position_policy_version"):
                market_scoring.append_score_record(invalid, history_path)
            second = market_scoring.append_score_record(score_record("run-2"), history_path)
            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertTrue(second["appended"])
        self.assertEqual(len(saved["records"]), 1)
        self.assertEqual(saved["records"][0]["run_id"], "run-2")

    def test_history_api_exposes_version_and_dedupe_contract(self) -> None:
        payload = serve_market_web.history_api_result()

        self.assertEqual(payload["api_version"], 2)
        self.assertEqual(payload["history_schema_version"], market_scoring.HISTORY_SCHEMA_VERSION)
        self.assertEqual(payload["model_version"], market_scoring.MODEL_VERSION)
        self.assertEqual(payload["position_policy_version"], market_scoring.POSITION_POLICY_VERSION)
        self.assertEqual(payload["dedupe_key_fields"], list(market_scoring.HISTORY_DEDUPE_KEY_FIELDS))
        self.assertGreaterEqual(payload["history"]["schema_version"], market_scoring.HISTORY_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
