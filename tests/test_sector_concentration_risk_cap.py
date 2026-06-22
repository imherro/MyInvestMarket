from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
from tests.test_market_scenarios import base_snapshot, index_rows, rolling_features  # noqa: E402


def score_with_rolling(snapshot: dict) -> dict:
    with patch.object(
        market_scoring,
        "rolling_market_features",
        return_value=rolling_features(
            northbound_5d=180,
            main_5d=650,
            breadth_5d_pct=68,
            top_flow_5d=620,
            repeat_ratio=0.8,
        ),
    ):
        return market_scoring.score_snapshot(snapshot, snapshot_bytes=b"sector-concentration-test")


def risk_cap(record: dict, reason: str) -> dict | None:
    for item in record.get("risk_caps", []):
        if item.get("reason") == reason:
            return item
    return None


class SectorConcentrationRiskCapTest(unittest.TestCase):
    def concentrated_flow_snapshot(self) -> dict:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(return_5d_pct=4, return_20d_pct=8, ma20_deviation_pct=4)
        snapshot["valuation"]["market"] = {
            "valuation_score": 32,
            "index_pe_value_score": 32,
            "index_pb_value_score": 32,
            "erp_value_score": 32,
        }
        snapshot["sector_rotation"]["top5_industries_by_capital_inflow"] = [
            {"industry": "半导体", "net_amount_100m_cny": 260},
            {"industry": "通信", "net_amount_100m_cny": 35},
            {"industry": "计算机", "net_amount_100m_cny": 25},
            {"industry": "有色", "net_amount_100m_cny": 18},
            {"industry": "医药生物", "net_amount_100m_cny": 12},
        ]
        return snapshot

    def test_sector_flow_concentration_caps_hot_market(self) -> None:
        record = score_with_rolling(self.concentrated_flow_snapshot())
        cap = risk_cap(record, "sector_concentration_top")

        self.assertIsNotNone(cap)
        self.assertGreaterEqual(record["market_opportunity_score"], 60)
        self.assertGreater(record["pre_cap_market_position_score"], record["market_position_score"])
        self.assertEqual(record["market_position_score"], 50)
        self.assertEqual(record["recommended_equity_position_range"], "40%-60%")
        self.assertEqual(cap["score_cap"], 50)
        self.assertEqual(cap["severity"], "high")
        self.assertEqual(cap["evidence"]["top_flow_industry"], "半导体")
        self.assertEqual(cap["evidence"]["top_flow_amount_100m_cny"], 260)
        self.assertEqual(cap["evidence"]["top5_flow_sum_100m_cny"], 350)
        self.assertGreaterEqual(cap["evidence"]["top_flow_concentration_ratio"], 0.70)
        self.assertIn("主线拥挤顶部", cap["message"])

    def test_sector_return_concentration_caps_when_volatility_is_elevated(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(return_5d_pct=4, return_20d_pct=7, ma20_deviation_pct=3)
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.26
        snapshot["sector_rotation"]["top5_industries_by_return"] = [
            {"industry": "半导体", "pct_change": 8.5},
            {"industry": "通信", "pct_change": 1.2},
            {"industry": "计算机", "pct_change": 1.0},
            {"industry": "有色", "pct_change": 0.8},
            {"industry": "医药生物", "pct_change": 0.5},
        ]
        snapshot["sector_rotation"]["top5_industries_by_capital_inflow"] = [
            {"industry": "半导体", "net_amount_100m_cny": 80},
            {"industry": "通信", "net_amount_100m_cny": 75},
            {"industry": "计算机", "net_amount_100m_cny": 70},
            {"industry": "有色", "net_amount_100m_cny": 65},
            {"industry": "医药生物", "net_amount_100m_cny": 60},
        ]

        record = score_with_rolling(snapshot)
        cap = risk_cap(record, "sector_concentration_top")

        self.assertIsNotNone(cap)
        self.assertEqual(record["market_position_score"], 50)
        self.assertEqual(cap["evidence"]["top_return_industry"], "半导体")
        self.assertEqual(cap["evidence"]["top_return_pct"], 8.5)
        self.assertGreaterEqual(cap["evidence"]["top_return_concentration_ratio"], 0.55)

    def test_sector_concentration_without_valuation_or_volatility_risk_does_not_trigger(self) -> None:
        snapshot = self.concentrated_flow_snapshot()
        snapshot["valuation"]["market"] = {
            "valuation_score": 60,
            "index_pe_value_score": 60,
            "index_pb_value_score": 60,
            "erp_value_score": 60,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.16

        record = score_with_rolling(snapshot)

        self.assertIsNone(risk_cap(record, "sector_concentration_top"))


if __name__ == "__main__":
    unittest.main()
