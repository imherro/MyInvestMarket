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


class PositionModelTest(unittest.TestCase):
    def test_expansion_strong_trend_lifts_low_risk_position(self) -> None:
        record = score_scenario("position-expansion", base_snapshot())

        model = record["position_model"]
        self.assertEqual(model["version"], "position_model_v1")
        self.assertGreater(model["trend_multiplier"], 1)
        self.assertGreater(model["regime_multiplier"], 1)
        self.assertEqual(model["risk_discount"], 1.0)
        self.assertGreaterEqual(record["market_position_score"], record["base_market_position_score"])

    def test_distribution_high_risk_reduces_position_before_cap(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["market"]["indices"] = index_rows(return_5d_pct=6, return_20d_pct=10, ma20_deviation_pct=7, volume_ratio_5d=1.5)
        snapshot["capital_flow"].update({"northbound_net_inflow_100m_cny": 70, "main_net_inflow_100m_cny": -1200})
        snapshot["valuation"]["market"] = {
            "valuation_score": 8,
            "index_pe_value_score": 8,
            "index_pb_value_score": 10,
            "erp_value_score": 12,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.32

        record = score_scenario(
            "position-distribution",
            snapshot,
            rolling_features(northbound_5d=150, main_5d=-1800, breadth_5d_pct=65, top_flow_5d=700, repeat_ratio=0.9),
        )

        model = record["position_model"]
        self.assertLess(model["regime_multiplier"], 1)
        self.assertLess(model["risk_discount"], 1)
        self.assertLess(record["pre_cap_market_position_score"], record["base_market_position_score"])
        self.assertTrue(record["decision_explain"]["why_position_changed"])

    def test_score_record_schema_requires_position_explain(self) -> None:
        record = score_scenario("position-schema", base_snapshot())
        validation = market_scoring.validate_score_record(record)

        self.assertTrue(validation["ok"])
        self.assertEqual(record["model_version"], market_scoring.MODEL_VERSION)
        self.assertIn("position_model", validation["checked_required_fields"])
        self.assertIn("decision_explain", validation["checked_required_fields"])


if __name__ == "__main__":
    unittest.main()
