from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402


def low_sample_rolling() -> dict:
    return {
        "sample_count": 2,
        "basis_trade_date": "2026-06-18",
        "capital_flow": {
            "northbound_5d_sum_100m_cny": 1000,
            "main_5d_sum_100m_cny": 1000,
            "northbound_sample_count": 2,
            "main_sample_count": 2,
        },
        "breadth": {
            "advancer_ratio_5d_avg_pct": 80,
            "sample_count": 2,
        },
        "mainline": {
            "top_flow_5d_sum_100m_cny": 1000,
            "current_group_repeat_ratio_5d": 1.0,
            "sample_count": 2,
        },
    }


def snapshot() -> dict:
    return {
        "date": "2026-06-18",
        "market": {
            "as_of_trade_date": "2026-06-18",
            "indices": {
                "000001.SH": {
                    "close": 3000,
                    "above_ma20": True,
                    "return_5d_pct": 1,
                    "return_20d_pct": 3,
                    "ma20_deviation_pct": 2,
                    "volume_ratio_5d": 1.05,
                },
                "399001.SZ": {
                    "close": 10000,
                    "above_ma20": True,
                    "return_5d_pct": 1,
                    "return_20d_pct": 3,
                    "ma20_deviation_pct": 2,
                    "volume_ratio_5d": 1.05,
                },
                "399006.SZ": {
                    "close": 2000,
                    "above_ma20": True,
                    "return_5d_pct": 1,
                    "return_20d_pct": 3,
                    "ma20_deviation_pct": 2,
                    "volume_ratio_5d": 1.05,
                },
            },
        },
        "breadth": {
            "advancers": 80,
            "decliners": 20,
            "total": 100,
            "industry_up_ratio": 0.8,
            "median_pct_change": 1.2,
            "strong_advancers_gt3_pct": 0.2,
            "strong_decliners_lt_minus3_pct": 0.02,
            "limit_up": 80,
            "limit_down": 0,
            "max_limit_up_streak": 6,
        },
        "capital_flow": {
            "northbound_net_inflow_100m_cny": 100,
            "main_net_inflow_100m_cny": 500,
            "turnover_distribution": {
                "large_cap": {"share": 0.25},
                "mid_cap": {"share": 0.45},
                "small_cap": {"share": 0.25},
            },
        },
        "sector_rotation": {
            "top5_industries_by_return": [
                {"industry": "半导体", "pct_change": 4.0},
                {"industry": "通信", "pct_change": 3.5},
            ],
            "top5_industries_by_capital_inflow": [
                {"industry": "半导体", "net_amount_100m_cny": 180},
                {"industry": "通信", "net_amount_100m_cny": 120},
            ],
        },
        "valuation": {"market": {"valuation_score": 50}, "indices": {}},
        "volatility": {"market": {"realized_vol_30d": 0.2}},
        "macro": {},
        "data_quality": {"missing_fields": [], "warnings": []},
    }


def evidence_score(module: dict, label: str) -> float:
    for item in module.get("evidence", []):
        if item.get("label") == label:
            return item["score"]
    raise AssertionError(f"missing evidence {label}")


class RollingSampleGuardTest(unittest.TestCase):
    def test_capital_flow_rolling_scores_are_capped_when_samples_are_short(self) -> None:
        with patch.object(market_scoring, "rolling_market_features", return_value=low_sample_rolling()):
            result = market_scoring.capital_flow(snapshot())

        self.assertLessEqual(evidence_score(result, "北向5日持续性"), 1.0)
        self.assertLessEqual(evidence_score(result, "主力5日持续性"), 1.5)

    def test_mainline_continuity_score_is_capped_when_samples_are_short(self) -> None:
        with patch.object(market_scoring, "rolling_market_features", return_value=low_sample_rolling()):
            result = market_scoring.mainline(snapshot())

        self.assertLessEqual(evidence_score(result, "当前主线5日重复率"), 1.5)

    def test_score_snapshot_warns_and_lowers_confidence_on_short_rolling_samples(self) -> None:
        with patch.object(market_scoring, "rolling_market_features", return_value=low_sample_rolling()):
            record = market_scoring.score_snapshot(snapshot(), snapshot_bytes=b"rolling-sample-test")

        warnings = record["data_quality"]["warnings"]
        self.assertEqual(record["confidence"], "medium")
        self.assertTrue(any("rolling sample insufficient" in warning for warning in warnings))
        self.assertTrue(any("capital_flow.northbound_5d_sum_100m_cny" in warning for warning in warnings))
        self.assertTrue(any("mainline.current_group_repeat_ratio_5d" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
