from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402


class MarketObservationTest(unittest.TestCase):
    def test_observation_detects_growth_strength_breadth_weakness_and_weight_rebound(self) -> None:
        snapshot = {
            "date": "2026-07-06",
            "breadth": {
                "advancers": 1800,
                "decliners": 3500,
                "flat": 100,
                "median_pct_change": -1.27,
                "strong_advancers_gt3_pct": 0.09,
                "strong_decliners_lt_minus3_pct": 0.28,
                "industry_up_ratio": 0.32,
            },
            "capital_flow": {
                "northbound_net_inflow_100m_cny": 39.6,
                "main_net_inflow_100m_cny": -898.1,
            },
            "sector_rotation": {
                "top5_industries_by_return": [
                    {"industry": "煤炭", "pct_change": 4.1},
                    {"industry": "银行", "pct_change": 1.9},
                ],
                "top5_industries_by_capital_inflow": [
                    {"industry": "半导体", "net_amount_100m_cny": 65.0, "pct_change": -0.4},
                    {"industry": "保险", "net_amount_100m_cny": 10.0, "pct_change": 1.2},
                ],
            },
        }
        record = {
            "basis_trade_date": "2026-07-06",
            "market_opportunity_score": 43.7,
            "market_position_score": 15.7,
            "recommended_equity_position_range": "0%-20%",
            "crowding_penalty": 18,
            "risk_penalty_score": 66,
            "risk_caps": [{"reason": "strong_index_weak_breadth", "message": "test", "severity": "high", "score_cap": 20}],
            "modules": {
                "breadth": {"score_pct": 21.58},
                "mainline": {"score_pct": 81.31},
                "capital_flow": {"score_pct": 38.67},
                "valuation": {"score_pct": 30},
            },
        }

        observation = market_scoring.build_market_observation(snapshot, record)

        self.assertEqual(observation["version"], market_scoring.MARKET_OBSERVATION_VERSION)
        self.assertTrue(observation["divergence"]["severe"])
        self.assertTrue(observation["broad_market"]["weak"])
        self.assertTrue(observation["mainline"]["growth_signal"]["active"])
        self.assertIn("半导体", observation["mainline"]["growth_signal"]["industries"])
        self.assertTrue(observation["traditional_weight_reversal"]["active"])
        self.assertIn("煤炭", observation["traditional_weight_reversal"]["industries"])
        self.assertIn("不确认全面反转", " ".join([observation["stance"], observation["summary"]]))


if __name__ == "__main__":
    unittest.main()
