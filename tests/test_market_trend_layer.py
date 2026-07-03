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


class MarketTrendLayerTest(unittest.TestCase):
    def test_strong_trend_from_broad_strength_and_liquidity(self) -> None:
        record = score_scenario("strong-trend", base_snapshot())

        self.assertEqual(record["trend_state"], "strong_trend")
        self.assertEqual(record["trend_state_label"], "强趋势")
        self.assertGreaterEqual(record["trend_strength"], 85)
        self.assertEqual(record["market_trend_layer"]["trend_state"], record["trend_state"])

    def test_late_trend_from_hot_index_and_fading_breadth(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["market"]["indices"] = index_rows(
            return_5d_pct=5.5,
            return_20d_pct=11,
            ma20_deviation_pct=8.5,
            above_ma20=True,
            volume_ratio_5d=0.92,
        )
        snapshot["breadth"].update(
            {
                "advancers": 2300,
                "decliners": 2600,
                "industry_up_ratio": 0.38,
                "median_pct_change": 0.0,
            }
        )

        record = score_scenario("late-trend", snapshot, rolling_features(breadth_5d_pct=42))

        self.assertEqual(record["trend_state"], "late_trend")
        self.assertEqual(record["trend_state_label"], "趋势末期")
        self.assertGreaterEqual(record["trend_strength"], 70)

    def test_weakening_trend_from_negative_momentum_and_width(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["market"]["indices"] = index_rows(
            return_5d_pct=-2,
            return_20d_pct=-6,
            ma20_deviation_pct=-4,
            above_ma20=False,
            volume_ratio_5d=0.7,
        )
        snapshot["breadth"].update(
            {
                "advancers": 900,
                "decliners": 4100,
                "industry_up_ratio": 0.18,
                "median_pct_change": -1.1,
                "strong_advancers_gt3_pct": 0.02,
                "strong_decliners_lt_minus3_pct": 0.18,
            }
        )

        record = score_scenario("weakening-trend", snapshot, rolling_features(breadth_5d_pct=28))

        self.assertEqual(record["trend_state"], "weakening_trend")
        self.assertEqual(record["trend_state_label"], "趋势转弱")
        self.assertLess(record["trend_strength"], 25)

    def test_score_record_schema_requires_trend_layer(self) -> None:
        record = score_scenario("trend-schema", base_snapshot())
        validation = market_scoring.validate_score_record(record)

        self.assertTrue(validation["ok"])
        self.assertEqual(record["model_version"], market_scoring.MODEL_VERSION)
        self.assertIn("market_trend_layer", validation["checked_required_fields"])


if __name__ == "__main__":
    unittest.main()
