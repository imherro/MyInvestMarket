from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
from market_regime import compute_market_regime  # noqa: E402
from tests.test_market_scenarios import base_snapshot, index_rows, score_scenario  # noqa: E402


class MarketRegimeLayerTest(unittest.TestCase):
    def test_expansion_regime_from_broad_strength_and_inflow(self) -> None:
        result = compute_market_regime(base_snapshot())

        self.assertEqual(result["regime"], "expansion")
        self.assertEqual(result["label"], "主升扩张")
        self.assertGreater(result["confidence"], 0)
        self.assertTrue(result["signals"])

    def test_distribution_regime_from_expensive_valuation_and_flow_divergence(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["valuation"]["market"]["valuation_score"] = 10
        snapshot["capital_flow"].update(
            {
                "northbound_net_inflow_100m_cny": 80,
                "main_net_inflow_100m_cny": -1200,
            }
        )
        snapshot["market"]["indices"] = index_rows(volume_ratio_5d=1.55)

        result = compute_market_regime(snapshot)

        self.assertEqual(result["regime"], "distribution")
        self.assertGreaterEqual(result["scores"]["distribution"], result["scores"]["expansion"])

    def test_contraction_regime_from_weak_breadth_and_liquidity(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["breadth"].update(
            {
                "advancers": 900,
                "decliners": 4100,
                "industry_up_ratio": 0.18,
                "median_pct_change": -1.3,
                "strong_advancers_gt3_pct": 0.02,
                "strong_decliners_lt_minus3_pct": 0.18,
            }
        )
        snapshot["market"]["indices"] = index_rows(
            return_5d_pct=-3,
            return_20d_pct=-8,
            ma20_deviation_pct=-5,
            above_ma20=False,
            volume_ratio_5d=0.72,
        )
        snapshot["capital_flow"].update(
            {
                "northbound_net_inflow_100m_cny": -80,
                "main_net_inflow_100m_cny": -900,
                "turnover_distribution": {
                    "large_cap": {"share": 0.48},
                    "mid_cap": {"share": 0.28},
                    "small_cap": {"share": 0.18},
                },
            }
        )

        result = compute_market_regime(snapshot)

        self.assertEqual(result["regime"], "contraction")
        self.assertGreater(result["scores"]["contraction"], result["scores"]["accumulation"])

    def test_score_snapshot_persists_structured_regime_layer(self) -> None:
        record = score_scenario("regime-layer", base_snapshot())
        validation = market_scoring.validate_score_record(record)

        self.assertTrue(validation["ok"])
        self.assertEqual(record["model_version"], "v3.1_trend")
        self.assertEqual(record["market_regime_code"], record["market_regime_layer"]["regime"])
        self.assertEqual(record["market_regime_layer"]["version"], "market_regime_v1")
        self.assertIn("market_regime_layer", validation["checked_required_fields"])


if __name__ == "__main__":
    unittest.main()
