from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402


def record(run_id: str, model_version: str, position_policy_version: str) -> dict:
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
        "basis_trade_date": "2026-06-18",
        "snapshot_sha256": run_id,
        "model_version": model_version,
        "position_policy_version": position_policy_version,
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


def mixed_history() -> dict:
    return {
        "schema_version": market_scoring.HISTORY_SCHEMA_VERSION,
        "model_version": market_scoring.MODEL_VERSION,
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
        "updated_at": "2026-06-22T16:10:00+08:00",
        "records": [
            record("legacy-model-1", "a_share_market_score_v1_3", market_scoring.POSITION_POLICY_VERSION),
            record("legacy-policy-2", market_scoring.MODEL_VERSION, "stock_account_position_policy_v1"),
            record("current-3", market_scoring.MODEL_VERSION, market_scoring.POSITION_POLICY_VERSION),
        ],
    }


class HistoryVersionFilterTest(unittest.TestCase):
    def test_filtered_history_defaults_to_current_model_and_policy(self) -> None:
        result = serve_market_web.filtered_history(mixed_history())

        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["total_record_count"], 3)
        self.assertEqual(result["legacy_record_count"], 2)
        self.assertEqual(result["records"][0]["run_id"], "current-3")
        self.assertFalse(result["version_filter"]["include_legacy"])

    def test_filtered_history_can_include_legacy_records_explicitly(self) -> None:
        result = serve_market_web.filtered_history(mixed_history(), include_legacy=True)

        self.assertEqual(result["record_count"], 3)
        self.assertEqual([row["run_id"] for row in result["records"]], ["legacy-model-1", "legacy-policy-2", "current-3"])
        self.assertTrue(result["version_filter"]["include_legacy"])

    def test_history_api_result_uses_version_filter_contract(self) -> None:
        with patch.object(serve_market_web, "load_history", return_value=mixed_history()):
            current = serve_market_web.history_api_result()
            with_legacy = serve_market_web.history_api_result(include_legacy=True)

        self.assertEqual(current["record_count"], 1)
        self.assertEqual(current["history"]["records"][0]["run_id"], "current-3")
        self.assertEqual(with_legacy["record_count"], 3)
        self.assertEqual(current["version_filter"]["model_version"], market_scoring.MODEL_VERSION)
        self.assertEqual(current["version_filter"]["position_policy_version"], market_scoring.POSITION_POLICY_VERSION)

    def test_frontend_does_not_request_legacy_history_by_default(self) -> None:
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('fetchJson("/api/history")', app_js)
        self.assertIn("historyVersionFilter", app_js)
        self.assertNotIn("include_legacy=true", app_js)


if __name__ == "__main__":
    unittest.main()
