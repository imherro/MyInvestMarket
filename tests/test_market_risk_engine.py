from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
from tests.test_market_scenarios import base_snapshot, index_rows, rolling_features, score_scenario  # noqa: E402


class MarketRiskEngineTest(unittest.TestCase):
    def test_low_risk_strong_trend_keeps_full_discount(self) -> None:
        record = score_scenario("low-risk", base_snapshot())

        self.assertLessEqual(record["risk_penalty_score"], 20)
        self.assertEqual(record["risk_discount"], 1.0)
        self.assertGreaterEqual(record["pre_cap_market_position_score"], record["base_market_position_score"])
        self.assertEqual(record["risk_engine"]["risk_level"], "安全")

    def test_high_risk_uses_continuous_discount_before_cap(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["market"]["indices"] = index_rows(return_5d_pct=7, return_20d_pct=12, ma20_deviation_pct=8, volume_ratio_5d=1.55)
        snapshot["capital_flow"].update({"northbound_net_inflow_100m_cny": 60, "main_net_inflow_100m_cny": -1200})
        snapshot["valuation"]["market"] = {
            "valuation_score": 8,
            "index_pe_value_score": 8,
            "index_pb_value_score": 10,
            "erp_value_score": 12,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.32

        record = score_scenario(
            "high-risk",
            snapshot,
            rolling_features(northbound_5d=150, main_5d=-1800, breadth_5d_pct=65, top_flow_5d=700, repeat_ratio=0.9),
        )

        self.assertGreaterEqual(record["risk_penalty_score"], 70)
        self.assertLess(record["risk_discount"], 0.85)
        self.assertLess(record["risk_adjusted_market_position_score"], record["base_market_position_score"])
        self.assertEqual(record["risk_engine"]["risk_level"], "极端风险")

    def test_score_record_schema_requires_risk_engine(self) -> None:
        record = score_scenario("risk-schema", base_snapshot())
        validation = market_scoring.validate_score_record(record)

        self.assertTrue(validation["ok"])
        self.assertEqual(record["model_version"], "v3.3_position")
        self.assertEqual(record["risk_penalty_score"], record["risk_engine"]["risk_penalty_score"])
        self.assertIn("risk_engine", validation["checked_required_fields"])


if __name__ == "__main__":
    unittest.main()
