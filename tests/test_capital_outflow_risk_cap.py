from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
from tests.test_market_scenarios import base_snapshot, rolling_features  # noqa: E402


def score_with_rolling(snapshot: dict) -> dict:
    with patch.object(
        market_scoring,
        "rolling_market_features",
        return_value=rolling_features(
            northbound_5d=-200,
            main_5d=-3000,
            breadth_5d_pct=70,
            top_flow_5d=600,
            repeat_ratio=0.8,
        ),
    ):
        return market_scoring.score_snapshot(snapshot, snapshot_bytes=b"capital-outflow-test")


def risk_cap(record: dict, reason: str) -> dict | None:
    for item in record.get("risk_caps", []):
        if item.get("reason") == reason:
            return item
    return None


class CapitalOutflowRiskCapTest(unittest.TestCase):
    def test_capital_outflow_combo_caps_high_score_trend_market(self) -> None:
        snapshot = base_snapshot()
        snapshot["capital_flow"]["northbound_net_inflow_100m_cny"] = -80
        snapshot["capital_flow"]["main_net_inflow_100m_cny"] = -900

        record = score_with_rolling(snapshot)
        cap = risk_cap(record, "capital_outflow_combo")

        self.assertIsNotNone(cap)
        self.assertGreaterEqual(record["market_opportunity_score"], 65)
        self.assertGreater(record["pre_cap_market_position_score"], record["market_position_score"])
        self.assertEqual(record["market_position_score"], 55)
        self.assertEqual(record["recommended_equity_position_range"], "55%-75%")
        self.assertEqual(cap["score_cap"], 55)
        self.assertEqual(cap["severity"], "high")
        self.assertEqual(cap["evidence"]["northbound_net_inflow_100m_cny"], -80)
        self.assertEqual(cap["evidence"]["main_net_inflow_100m_cny"], -900)
        self.assertIn("资金退潮", cap["message"])

    def test_single_sided_outflow_does_not_trigger_capital_outflow_combo(self) -> None:
        snapshot = base_snapshot()
        snapshot["capital_flow"]["northbound_net_inflow_100m_cny"] = 60
        snapshot["capital_flow"]["main_net_inflow_100m_cny"] = -900

        record = score_with_rolling(snapshot)

        self.assertIsNone(risk_cap(record, "capital_outflow_combo"))


if __name__ == "__main__":
    unittest.main()
