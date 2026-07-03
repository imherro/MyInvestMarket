from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_scoring  # noqa: E402


def module_scores(index: float = 16, breadth: float = 12, valuation: float = 10) -> dict:
    return {
        "index_trend": {"score": index, "weight": 20, "score_pct": index / 20 * 100},
        "breadth": {"score": breadth, "weight": 15, "score_pct": breadth / 15 * 100},
        "valuation": {"score": valuation, "weight": 15, "score_pct": valuation / 15 * 100},
    }


def full_module_scores(**score_pct: float) -> dict:
    defaults = {
        "index_trend": 25,
        "breadth": 22,
        "liquidity": 35,
        "capital_flow": 32,
        "mainline": 20,
        "valuation": 88,
        "macro": 45,
    }
    defaults.update(score_pct)
    return {
        key: {
            "score": round(value / 100 * meta["weight"], 2),
            "weight": meta["weight"],
            "score_pct": value,
        }
        for key, value in defaults.items()
        for meta in [market_scoring.MODULES[key]]
    }


def snapshot(realized_vol: float | None = 0.16, valuation_score: float | None = 55) -> dict:
    payload: dict = {
        "volatility": {"market": {"realized_vol_30d": realized_vol}},
        "valuation": {"market": {"valuation_score": valuation_score}},
        "data_quality": {"missing_fields": []},
    }
    return payload


def contrarian_snapshot(main_net: float = -250, northbound: float = 10) -> dict:
    return {
        "volatility": {
            "market": {"realized_vol_30d": 0.32},
            "indices": {
                "000001.SH": {"drawdown_60d_pct": -18},
                "399001.SZ": {"drawdown_60d_pct": -22},
                "399006.SZ": {"drawdown_60d_pct": -24},
            },
        },
        "valuation": {"market": {"valuation_score": 88}},
        "breadth": {
            "total": 5000,
            "advancers": 800,
            "decliners": 4200,
            "strong_decliners_lt_minus3_pct": 0.24,
            "limit_down": 45,
        },
        "capital_flow": {
            "northbound_net_inflow_100m_cny": northbound,
            "main_net_inflow_100m_cny": main_net,
        },
        "data_quality": {"missing_fields": []},
    }


def medium_risk_engine() -> dict:
    return {
        "version": "risk_engine_v1",
        "risk_penalty_score": 30,
        "risk_level": "medium",
        "risk_discount": 0.75,
        "components": [],
    }


def upper_bound(range_text: str) -> float:
    parsed = market_scoring.parse_percent_range(range_text)
    assert parsed is not None
    return parsed[1]


class StockAccountPositionPolicyTest(unittest.TestCase):
    def test_low_crowding_strong_trend_can_approach_full_position(self) -> None:
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            86,
            {"penalty": 1},
            module_scores(index=19, breadth=14, valuation=12),
            snapshot(realized_vol=0.16, valuation_score=55),
            quality,
        )

        self.assertGreaterEqual(result["market_position_score"], 80)
        self.assertGreaterEqual(upper_bound(result["recommended_equity_position_range"]), 90)
        self.assertLessEqual(upper_bound(result["recommended_equity_position_range"]), 100)
        self.assertFalse(any(cap["reason"] in {"bubble_top_combo", "high_crowding"} for cap in result["risk_caps"]))

    def test_bubble_top_is_capped_to_low_position(self) -> None:
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            75,
            {"penalty": 17},
            module_scores(index=19, breadth=14, valuation=2),
            snapshot(realized_vol=0.30, valuation_score=12),
            quality,
        )

        self.assertIn("bubble_top_combo", {cap["reason"] for cap in result["risk_caps"]})
        self.assertLessEqual(result["market_position_score"], 45)
        self.assertLessEqual(upper_bound(result["recommended_equity_position_range"]), 45)
        self.assertGreater(result["pre_cap_market_position_score"], result["market_position_score"])

    def test_missing_valuation_and_volatility_hot_market_is_not_optimistic(self) -> None:
        hot_snapshot = snapshot(realized_vol=None, valuation_score=None)
        quality = market_scoring.data_quality_with_warnings(
            {"missing_fields": ["valuation.market", "volatility.market"]}
        )
        result = market_scoring.apply_position_policy(
            75,
            {"penalty": 0},
            module_scores(index=18, breadth=13, valuation=7.5),
            hot_snapshot,
            quality,
        )

        reasons = {cap["reason"] for cap in result["risk_caps"]}
        self.assertIn("missing_valuation_data_hot_market", reasons)
        self.assertIn("missing_volatility_data_hot_market", reasons)
        self.assertIn("missing_core_risk_data_hot_market", reasons)
        self.assertLessEqual(result["market_position_score"], 55)
        self.assertLessEqual(upper_bound(result["recommended_equity_position_range"]), 60)
        self.assertTrue(quality["warnings"])

    def test_high_volatility_is_indicator_only_not_official_scaling(self) -> None:
        vol_snapshot = snapshot(realized_vol=0.30, valuation_score=55)
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            80,
            {"penalty": 5},
            module_scores(index=18, breadth=13, valuation=12),
            vol_snapshot,
            quality,
        )
        policy = market_scoring.volatility_policy(vol_snapshot)

        self.assertEqual(policy["mode"], "risk_indicator_only")
        self.assertIsNone(policy["target_annual_vol"])
        self.assertEqual(result["market_position_score"], 55)
        self.assertGreaterEqual(upper_bound(result["recommended_equity_position_range"]), 55)

    def test_recommended_position_range_never_exceeds_100_percent(self) -> None:
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            100,
            {"penalty": 0},
            module_scores(index=20, breadth=15, valuation=15),
            snapshot(realized_vol=0.05, valuation_score=90),
            quality,
        )
        lower, upper = market_scoring.parse_percent_range(result["recommended_equity_position_range"]) or (None, None)

        self.assertIsNotNone(lower)
        self.assertGreaterEqual(lower, 0)
        self.assertLessEqual(upper, 100)

    def test_deep_bear_contrarian_overlay_raises_beta_floor_only(self) -> None:
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            42,
            {"penalty": 3},
            full_module_scores(),
            contrarian_snapshot(),
            quality,
            risk_engine=medium_risk_engine(),
        )
        overlay = result["contrarian_beta_overlay"]
        allocation = market_scoring.allocation_policy(
            result["market_position_score"],
            42,
            result["pre_cap_market_position_score"],
            result["recommended_equity_position_range"],
            full_module_scores(),
            {"penalty": 3},
            contrarian_snapshot(),
            result["risk_caps"],
            overlay,
        )

        self.assertTrue(overlay["active"])
        self.assertGreater(result["market_position_score"], result["pre_overlay_market_position_score"])
        self.assertGreater(overlay["add_score"], 0)
        self.assertEqual(allocation["state"], "深熊赔率期")
        self.assertTrue(allocation["beta_core_overlay_only"])
        self.assertLessEqual(market_scoring.parse_percent_range(allocation["sleeves"][1]["target_range"])[1], 5)

    def test_capital_stampede_blocks_contrarian_overlay(self) -> None:
        quality = market_scoring.data_quality_with_warnings({})
        result = market_scoring.apply_position_policy(
            42,
            {"penalty": 3},
            full_module_scores(),
            contrarian_snapshot(main_net=-1200, northbound=-120),
            quality,
            risk_engine=medium_risk_engine(),
        )

        overlay = result["contrarian_beta_overlay"]
        self.assertFalse(overlay["active"])
        self.assertTrue(any("资金踩踏" in blocker for blocker in overlay["blockers"]))
        self.assertEqual(result["pre_cap_market_position_score"], result["pre_overlay_market_position_score"])


if __name__ == "__main__":
    unittest.main()
