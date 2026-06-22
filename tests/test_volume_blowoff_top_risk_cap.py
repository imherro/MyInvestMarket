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
            northbound_5d=220,
            main_5d=700,
            breadth_5d_pct=72,
            top_flow_5d=620,
            repeat_ratio=0.75,
        ),
    ):
        return market_scoring.score_snapshot(snapshot, snapshot_bytes=b"volume-blowoff-test")


def risk_cap(record: dict, reason: str) -> dict | None:
    for item in record.get("risk_caps", []):
        if item.get("reason") == reason:
            return item
    return None


class VolumeBlowoffTopRiskCapTest(unittest.TestCase):
    def blowoff_snapshot(self) -> dict:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(
            return_5d_pct=6,
            return_20d_pct=10,
            ma20_deviation_pct=5,
            volume_ratio_5d=1.62,
        )
        snapshot["valuation"]["market"] = {
            "valuation_score": 32,
            "index_pe_value_score": 32,
            "index_pb_value_score": 32,
            "erp_value_score": 32,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.22
        snapshot["capital_flow"]["turnover_distribution"] = {
            "large_cap": {"share": 0.28, "turnover_100m_cny": 9200},
            "mid_cap": {"share": 0.42, "turnover_100m_cny": 13600},
            "small_cap": {"share": 0.30, "turnover_100m_cny": 9800},
        }
        return snapshot

    def test_volume_blowoff_top_caps_strong_trend_market(self) -> None:
        record = score_with_rolling(self.blowoff_snapshot())
        cap = risk_cap(record, "volume_blowoff_top")

        self.assertIsNotNone(cap)
        self.assertGreaterEqual(record["market_opportunity_score"], 65)
        self.assertGreater(record["pre_cap_market_position_score"], record["market_position_score"])
        self.assertEqual(record["market_position_score"], 45)
        self.assertEqual(record["recommended_equity_position_range"], "40%-60%")
        self.assertEqual(cap["score_cap"], 45)
        self.assertEqual(cap["severity"], "high")
        self.assertEqual(cap["evidence"]["avg_volume_ratio"], 1.62)
        self.assertEqual(cap["evidence"]["total_turnover_100m_cny"], 32600)
        self.assertLessEqual(cap["evidence"]["valuation_score_pct"], 0.35)
        self.assertIn("爆量顶部", cap["message"])

    def test_extreme_volume_without_valuation_or_volatility_risk_does_not_trigger(self) -> None:
        snapshot = self.blowoff_snapshot()
        snapshot["valuation"]["market"] = {
            "valuation_score": 65,
            "index_pe_value_score": 65,
            "index_pb_value_score": 65,
            "erp_value_score": 65,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.16

        record = score_with_rolling(snapshot)

        self.assertIsNone(risk_cap(record, "volume_blowoff_top"))


if __name__ == "__main__":
    unittest.main()
