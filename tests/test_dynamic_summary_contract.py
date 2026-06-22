from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402


def breadth_snapshot(strong: bool) -> dict:
    if strong:
        return {
            "breadth": {
                "advancers": 80,
                "decliners": 20,
                "total": 100,
                "industry_up_ratio": 0.8,
                "median_pct_change": 1.5,
                "strong_advancers_gt3_pct": 0.2,
                "strong_decliners_lt_minus3_pct": 0.02,
                "limit_up": 80,
                "limit_down": 0,
                "max_limit_up_streak": 7,
            }
        }
    return {
        "breadth": {
            "advancers": 15,
            "decliners": 85,
            "total": 100,
            "industry_up_ratio": 0.1,
            "median_pct_change": -1.8,
            "strong_advancers_gt3_pct": 0.01,
            "strong_decliners_lt_minus3_pct": 0.2,
            "limit_up": 5,
            "limit_down": 20,
            "max_limit_up_streak": 1,
        }
    }


def rolling_samples() -> dict:
    return {
        "capital_flow": {
            "northbound_5d_sum_100m_cny": 500,
            "main_5d_sum_100m_cny": 1200,
            "northbound_sample_count": 5,
            "main_sample_count": 5,
        },
        "mainline": {"sample_count": 5, "current_group_repeat_ratio_5d": 0.8},
        "breadth": {"sample_count": 5},
    }


class DynamicSummaryContractTest(unittest.TestCase):
    def test_high_breadth_summary_does_not_describe_weak_market(self) -> None:
        result = market_scoring.market_breadth(breadth_snapshot(strong=True))

        self.assertIn("偏强", result["summary"])
        self.assertNotIn("偏弱", result["summary"])
        self.assertNotIn("扩散不足", result["summary"])

    def test_low_breadth_summary_does_not_describe_strong_market(self) -> None:
        result = market_scoring.market_breadth(breadth_snapshot(strong=False))

        self.assertIn("偏弱", result["summary"])
        self.assertNotIn("偏强", result["summary"])

    def test_capital_flow_summary_matches_direction_evidence(self) -> None:
        with patch.object(market_scoring, "rolling_market_features", return_value=rolling_samples()):
            positive = market_scoring.capital_flow(
                {"capital_flow": {"northbound_net_inflow_100m_cny": 100, "main_net_inflow_100m_cny": 500}}
            )
            negative = market_scoring.capital_flow(
                {"capital_flow": {"northbound_net_inflow_100m_cny": -100, "main_net_inflow_100m_cny": -900}}
            )

        self.assertIn("同向流入", positive["summary"])
        self.assertIn("同向流出", negative["summary"])
        self.assertNotIn("主力流出", positive["summary"])

    def test_macro_summary_follows_score_strength(self) -> None:
        strong = market_scoring.macro(
            {
                "date": "2026-06-18",
                "macro": {
                    "china_10y_government_bond_yield_pct": {"date": "2026-06-18", "value_pct": 1.7},
                    "us_10y_treasury_yield_pct": {"date": "2026-06-18", "value": 3.5},
                    "dxy": {"date": "2026-06-18", "value": 96},
                    "usd_cny": {"date": "2026-06-18", "value": 6.7},
                },
            }
        )
        weak = market_scoring.macro(
            {
                "date": "2026-06-18",
                "macro": {
                    "china_10y_government_bond_yield_pct": {"date": "2026-06-18", "value_pct": 3.0},
                    "us_10y_treasury_yield_pct": {"date": "2026-06-18", "value": 5.0},
                    "dxy": {"date": "2026-06-18", "value": 107},
                    "usd_cny": {"date": "2026-06-18", "value": 7.3},
                },
            }
        )

        self.assertIn("偏强", strong["summary"])
        self.assertNotIn("偏弱", strong["summary"])
        self.assertIn("偏弱", weak["summary"])
        self.assertNotIn("偏强", weak["summary"])


if __name__ == "__main__":
    unittest.main()
