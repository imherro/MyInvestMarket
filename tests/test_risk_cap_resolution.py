from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
from tests.test_market_scenarios import base_snapshot, index_rows, rolling_features, score_scenario  # noqa: E402


class RiskCapResolutionTest(unittest.TestCase):
    def test_resolve_risk_caps_uses_lowest_score_cap_then_highest_severity(self) -> None:
        caps = [
            {"reason": "high_but_wider", "score_cap": 50, "severity": "high", "message": "wide"},
            {"reason": "medium_but_tighter", "score_cap": 35, "severity": "medium", "message": "tight"},
            {"reason": "low_same_score", "score_cap": 35, "severity": "low", "message": "tie"},
        ]

        applied, discarded = market_scoring.resolve_risk_caps(caps)

        self.assertEqual(applied["reason"], "medium_but_tighter")
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["priority_basis"], "lowest_score_cap_then_highest_severity")
        self.assertEqual({item["reason"] for item in discarded}, {"high_but_wider", "low_same_score"})
        self.assertTrue(all(item["discarded_by"] == "medium_but_tighter" for item in discarded))

    def test_apply_position_policy_exposes_resolution_fields_when_no_caps_trigger(self) -> None:
        modules = {
            "index_trend": {"score": 18, "weight": 20, "score_pct": 90},
            "breadth": {"score": 13, "weight": 15, "score_pct": 86.67},
            "valuation": {"score": 12, "weight": 15, "score_pct": 80},
        }

        result = market_scoring.apply_position_policy(
            85,
            {"penalty": 1},
            modules,
            {"volatility": {"market": {"realized_vol_30d": 0.16}}, "valuation": {"market": {"valuation_score": 70}}},
            market_scoring.data_quality_with_warnings({}),
        )

        self.assertIsNone(result["applied_cap"])
        self.assertEqual(result["discarded_caps"], [])
        self.assertEqual(result["market_position_score"], 84)

    def test_score_record_exposes_applied_and_discarded_caps_for_conflict_scenario(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(return_5d_pct=7, return_20d_pct=12, ma20_deviation_pct=8, volume_ratio_5d=1.55)
        snapshot["capital_flow"].update({"northbound_net_inflow_100m_cny": 60, "main_net_inflow_100m_cny": -650})
        snapshot["sector_rotation"]["top5_industries_by_capital_inflow"] = [
            {"industry": "半导体", "net_amount_100m_cny": 260},
            {"industry": "通信", "net_amount_100m_cny": 50},
            {"industry": "计算机", "net_amount_100m_cny": 30},
        ]
        snapshot["valuation"]["market"] = {
            "valuation_score": 8,
            "index_pe_value_score": 8,
            "index_pb_value_score": 10,
            "erp_value_score": 12,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.32

        record = score_scenario(
            "risk-cap-resolution",
            snapshot,
            rolling_features(northbound_5d=150, main_5d=-1800, breadth_5d_pct=65, top_flow_5d=700, repeat_ratio=0.9),
        )

        self.assertEqual(record["applied_cap"]["reason"], "bubble_top_combo")
        self.assertEqual(record["applied_cap"]["score_cap"], 35)
        self.assertEqual(record["market_position_score"], 35)
        discarded_reasons = {item["reason"] for item in record["discarded_caps"]}
        self.assertIn("volume_blowoff_top", discarded_reasons)
        self.assertIn("sector_concentration_top", discarded_reasons)
        self.assertIn("high_volatility", discarded_reasons)
        self.assertTrue(all(item["discarded_by"] == "bubble_top_combo" for item in record["discarded_caps"]))


if __name__ == "__main__":
    unittest.main()
