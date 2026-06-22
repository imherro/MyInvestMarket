from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402


EXPECTED_STABLE_RISK_CAP_REASONS = (
    "high_crowding_extreme",
    "high_crowding",
    "volume_blowoff_top",
    "sector_concentration_top",
    "capital_outflow_combo",
    "extreme_expensive_valuation",
    "expensive_valuation",
    "bubble_top_combo",
    "extreme_high_volatility",
    "high_volatility",
    "missing_valuation_data_hot_market",
    "missing_volatility_data_hot_market",
    "missing_core_risk_data_hot_market",
    "strong_index_weak_breadth",
)


class StableReleaseLockTest(unittest.TestCase):
    def test_model_version_is_stable_release(self) -> None:
        self.assertEqual(market_scoring.MODEL_VERSION, "v1.0_stable")

    def test_risk_cap_reasons_are_frozen(self) -> None:
        self.assertEqual(market_scoring.STABLE_RISK_CAP_REASONS, EXPECTED_STABLE_RISK_CAP_REASONS)
        with self.assertRaisesRegex(ValueError, "risk_cap reason is frozen"):
            market_scoring.risk_cap("new_unreviewed_cap", 50, "medium", {}, "should fail")

    def test_service_and_index_expose_stable_release_metadata(self) -> None:
        service = serve_market_web.service_version_result()
        index = serve_market_web.homepage_index_result()

        self.assertEqual(service["stable_release"]["model_version"], "v1.0_stable")
        self.assertTrue(service["stable_release"]["core_rules_frozen"])
        self.assertEqual(service["stable_release"]["risk_cap_reasons"], list(EXPECTED_STABLE_RISK_CAP_REASONS))
        self.assertEqual(index["stable_release"]["model_version"], "v1.0_stable")
        self.assertTrue(index["stable_release"]["core_rules_frozen"])

    def test_historical_snapshot_score_is_locked(self) -> None:
        snapshot_path = ROOT / "data" / "market_snapshot_2026-06-18.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rolling = {
            "sample_count": 5,
            "basis_trade_date": snapshot.get("date"),
            "capital_flow": {
                "northbound_5d_sum_100m_cny": 120,
                "main_5d_sum_100m_cny": -900,
                "northbound_sample_count": 5,
                "main_sample_count": 5,
            },
            "breadth": {"advancer_ratio_5d_avg_pct": 44, "sample_count": 5},
            "mainline": {
                "top_flow_5d_sum_100m_cny": 360,
                "current_group_repeat_ratio_5d": 0.6,
                "sample_count": 5,
            },
        }

        with patch.object(market_scoring, "rolling_market_features", return_value=rolling):
            record = market_scoring.score_snapshot(
                snapshot,
                snapshot_path=snapshot_path,
                snapshot_bytes=snapshot_path.read_bytes(),
            )

        self.assertEqual(record["model_version"], "v1.0_stable")
        self.assertEqual(record["market_opportunity_score"], 56.11)
        self.assertEqual(record["crowding_penalty"], 19.91)
        self.assertEqual(record["pre_cap_market_position_score"], 36.2)
        self.assertEqual(record["market_position_score"], 35.0)
        self.assertEqual(record["recommended_equity_position_range"], "20%-40%")
        self.assertEqual(record["market_regime"], "防守或弱修复")
        self.assertEqual(record["confidence"], "medium")
        self.assertEqual(
            [cap["reason"] for cap in record["risk_caps"]],
            [
                "high_crowding",
                "volume_blowoff_top",
                "expensive_valuation",
                "bubble_top_combo",
                "strong_index_weak_breadth",
            ],
        )
        self.assertEqual(record["applied_cap"]["reason"], "bubble_top_combo")
        self.assertEqual(
            [cap["reason"] for cap in record["discarded_caps"]],
            ["high_crowding", "volume_blowoff_top", "expensive_valuation", "strong_index_weak_breadth"],
        )
        self.assertEqual(
            {key: module["score"] for key, module in record["modules"].items()},
            {
                "index_trend": 15.54,
                "breadth": 4.9,
                "liquidity": 7.78,
                "capital_flow": 6.29,
                "mainline": 12.29,
                "valuation": 2.8,
                "macro": 6.51,
            },
        )


if __name__ == "__main__":
    unittest.main()
