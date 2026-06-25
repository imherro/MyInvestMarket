from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402


TRADE_DATE = "2026-06-18"


def index_rows(
    *,
    return_5d_pct: float = 2,
    return_20d_pct: float = 4,
    ma20_deviation_pct: float = 2,
    above_ma20: bool = True,
    volume_ratio_5d: float = 1.08,
) -> dict:
    rows = {}
    for code, close in [
        ("000001.SH", 4000),
        ("399001.SZ", 12000),
        ("399006.SZ", 2400),
        ("000905.SH", 6200),
        ("000852.SH", 6500),
    ]:
        rows[code] = {
            "close": close,
            "above_ma20": above_ma20,
            "return_5d_pct": return_5d_pct,
            "return_20d_pct": return_20d_pct,
            "ma20_deviation_pct": ma20_deviation_pct,
            "volume_ratio_5d": volume_ratio_5d,
        }
    return rows


def rolling_features(
    *,
    northbound_5d: float = 200,
    main_5d: float = 700,
    breadth_5d_pct: float = 70,
    top_flow_5d: float = 600,
    repeat_ratio: float = 0.8,
    sample_count: int = 5,
) -> dict:
    return {
        "sample_count": sample_count,
        "basis_trade_date": TRADE_DATE,
        "capital_flow": {
            "northbound_5d_sum_100m_cny": northbound_5d,
            "main_5d_sum_100m_cny": main_5d,
            "northbound_sample_count": sample_count,
            "main_sample_count": sample_count,
        },
        "breadth": {
            "advancer_ratio_5d_avg_pct": breadth_5d_pct,
            "sample_count": sample_count,
        },
        "mainline": {
            "top_flow_5d_sum_100m_cny": top_flow_5d,
            "current_group_repeat_ratio_5d": repeat_ratio,
            "sample_count": sample_count,
        },
    }


def base_snapshot() -> dict:
    return {
        "date": TRADE_DATE,
        "market": {"as_of_trade_date": TRADE_DATE, "indices": index_rows()},
        "breadth": {
            "advancers": 3600,
            "decliners": 1100,
            "total": 5000,
            "industry_up_ratio": 0.72,
            "median_pct_change": 1.1,
            "strong_advancers_gt3_pct": 0.22,
            "strong_decliners_lt_minus3_pct": 0.02,
            "limit_up": 90,
            "limit_down": 1,
            "max_limit_up_streak": 7,
        },
        "capital_flow": {
            "northbound_net_inflow_100m_cny": 80,
            "main_net_inflow_100m_cny": 300,
            "turnover_distribution": {
                "large_cap": {"share": 0.25},
                "mid_cap": {"share": 0.45},
                "small_cap": {"share": 0.30},
            },
        },
        "sector_rotation": {
            "top5_industries_by_return": [
                {"industry": "半导体", "pct_change": 4.0},
                {"industry": "通信", "pct_change": 3.4},
                {"industry": "计算机", "pct_change": 3.0},
                {"industry": "有色", "pct_change": 2.6},
            ],
            "top5_industries_by_capital_inflow": [
                {"industry": "半导体", "net_amount_100m_cny": 90},
                {"industry": "通信", "net_amount_100m_cny": 80},
                {"industry": "计算机", "net_amount_100m_cny": 70},
                {"industry": "有色", "net_amount_100m_cny": 60},
            ],
        },
        "valuation": {
            "market": {
                "valuation_score": 55,
                "index_pe_value_score": 55,
                "index_pb_value_score": 55,
                "erp_value_score": 55,
            },
            "indices": {"000001.SH": {}},
        },
        "volatility": {"market": {"realized_vol_30d": 0.16}},
        "macro": {
            "china_10y_government_bond_yield_pct": {"date": TRADE_DATE, "value_pct": 2.0},
            "us_10y_treasury_yield_pct": {"date": TRADE_DATE, "value_pct": 3.8},
            "dxy": {"date": TRADE_DATE, "value": 98},
            "usd_cny": {"date": TRADE_DATE, "value": 6.85},
        },
        "data_quality": {"missing_fields": [], "warnings": []},
    }


def score_scenario(name: str, snapshot: dict, rolling: dict | None = None) -> dict:
    with patch.object(market_scoring, "rolling_market_features", return_value=rolling or rolling_features()):
        return market_scoring.score_snapshot(snapshot, snapshot_bytes=name.encode("utf-8"))


def risk_reasons(record: dict) -> set[str]:
    return {item.get("reason") for item in record.get("risk_caps", [])}


def upper_position_bound(record: dict) -> float:
    bounds = market_scoring.parse_percent_range(record["recommended_equity_position_range"])
    assert bounds is not None
    return bounds[1]


class MarketScenarioRegressionTest(unittest.TestCase):
    def assert_between(self, value: float, low: float, high: float) -> None:
        self.assertGreaterEqual(value, low)
        self.assertLessEqual(value, high)

    def test_bottom_scenario_scores_cheap_but_stays_defensive_until_trend_confirms(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(
            return_5d_pct=-2,
            return_20d_pct=-8,
            ma20_deviation_pct=-7,
            above_ma20=False,
            volume_ratio_5d=0.75,
        )
        snapshot["breadth"].update(
            {
                "advancers": 1200,
                "decliners": 3700,
                "industry_up_ratio": 0.25,
                "median_pct_change": -1.2,
                "strong_advancers_gt3_pct": 0.03,
                "strong_decliners_lt_minus3_pct": 0.12,
                "limit_up": 20,
                "limit_down": 25,
                "max_limit_up_streak": 2,
            }
        )
        snapshot["capital_flow"].update(
            {
                "northbound_net_inflow_100m_cny": -20,
                "main_net_inflow_100m_cny": -400,
                "turnover_distribution": {
                    "large_cap": {"share": 0.18},
                    "mid_cap": {"share": 0.35},
                    "small_cap": {"share": 0.20},
                },
            }
        )
        snapshot["sector_rotation"] = {
            "top5_industries_by_return": [{"industry": "银行", "pct_change": 1.0}],
            "top5_industries_by_capital_inflow": [
                {"industry": "银行", "net_amount_100m_cny": 30},
                {"industry": "煤炭", "net_amount_100m_cny": 20},
            ],
        }
        snapshot["valuation"]["market"] = {
            "valuation_score": 90,
            "index_pe_value_score": 90,
            "index_pb_value_score": 92,
            "erp_value_score": 85,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.22

        record = score_scenario(
            "bottom",
            snapshot,
            rolling_features(northbound_5d=-60, main_5d=-1200, breadth_5d_pct=25, top_flow_5d=80, repeat_ratio=0.2),
        )

        self.assert_between(record["market_opportunity_score"], 30, 40)
        self.assert_between(record["market_position_score"], 0, 20)
        self.assertEqual(record["recommended_equity_position_range"], "0%-20%")
        self.assertGreaterEqual(record["modules"]["valuation"]["score_pct"], 85)
        self.assertEqual(record["confidence"], "high")
        self.assertEqual(risk_reasons(record), set())

    def test_low_crowding_strong_trend_can_reach_near_full_stock_account_position(self) -> None:
        record = score_scenario("low-crowding-strong-trend", base_snapshot())

        self.assertGreaterEqual(record["market_opportunity_score"], 80)
        self.assertGreaterEqual(record["market_position_score"], 80)
        self.assertEqual(record["recommended_equity_position_range"], "90%-100%")
        self.assertGreaterEqual(upper_position_bound(record), 100)
        self.assertEqual(record["crowding_penalty"], 0)
        self.assertEqual(risk_reasons(record), set())
        self.assertEqual(record["confidence"], "high")

    def test_bubble_top_scenario_is_capped_even_when_trend_is_strong(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(return_5d_pct=7, return_20d_pct=12, ma20_deviation_pct=8, volume_ratio_5d=1.55)
        snapshot["breadth"].update(
            {
                "advancers": 3300,
                "decliners": 1500,
                "industry_up_ratio": 0.68,
                "median_pct_change": 0.7,
                "strong_advancers_gt3_pct": 0.18,
                "strong_decliners_lt_minus3_pct": 0.05,
                "limit_up": 80,
                "limit_down": 4,
                "max_limit_up_streak": 8,
            }
        )
        snapshot["capital_flow"].update({"northbound_net_inflow_100m_cny": 60, "main_net_inflow_100m_cny": -650})
        snapshot["sector_rotation"]["top5_industries_by_capital_inflow"] = [
            {"industry": "半导体", "net_amount_100m_cny": 260},
            {"industry": "通信", "net_amount_100m_cny": 50},
            {"industry": "计算机", "net_amount_100m_cny": 30},
        ]
        snapshot["valuation"]["market"] = {
            "valuation_score": 8,
            "index_pe_value_score": 8,
            "index_pb_value_score": 10,
            "erp_value_score": 12,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.32

        record = score_scenario(
            "bubble-top",
            snapshot,
            rolling_features(northbound_5d=150, main_5d=-1800, breadth_5d_pct=65, top_flow_5d=700, repeat_ratio=0.9),
        )

        self.assert_between(record["market_opportunity_score"], 60, 70)
        self.assertGreaterEqual(record["crowding_penalty"], 20)
        self.assertLessEqual(record["market_position_score"], 35)
        self.assertGreaterEqual(record["risk_penalty_score"], 70)
        self.assertLess(record["pre_cap_market_position_score"], record["base_market_position_score"])
        self.assertIn("bubble_top_combo", risk_reasons(record))
        self.assertIn("high_crowding_extreme", risk_reasons(record))
        self.assertIn("high_volatility", risk_reasons(record))
        self.assertEqual(record["confidence"], "high")

    def test_strong_index_weak_breadth_scenario_triggers_structure_cap(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["indices"] = index_rows(return_5d_pct=5, return_20d_pct=8, ma20_deviation_pct=3, volume_ratio_5d=1.15)
        snapshot["breadth"].update(
            {
                "advancers": 1500,
                "decliners": 3300,
                "industry_up_ratio": 0.28,
                "median_pct_change": -0.8,
                "strong_advancers_gt3_pct": 0.05,
                "strong_decliners_lt_minus3_pct": 0.12,
                "limit_up": 30,
                "limit_down": 12,
                "max_limit_up_streak": 4,
            }
        )
        snapshot["valuation"]["market"] = {
            "valuation_score": 50,
            "index_pe_value_score": 50,
            "index_pb_value_score": 50,
            "erp_value_score": 50,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = 0.17

        record = score_scenario(
            "strong-index-weak-breadth",
            snapshot,
            rolling_features(northbound_5d=160, main_5d=400, breadth_5d_pct=30, top_flow_5d=500, repeat_ratio=0.7),
        )

        self.assertGreaterEqual(record["modules"]["index_trend"]["score_pct"], 75)
        self.assertLessEqual(record["modules"]["breadth"]["score_pct"], 40)
        self.assertGreaterEqual(record["market_opportunity_score"], 70)
        self.assert_between(record["market_position_score"], 50, 60)
        self.assertEqual(record["recommended_equity_position_range"], "55%-75%")
        self.assertIn("strong_index_weak_breadth", risk_reasons(record))
        self.assertEqual(record["confidence"], "high")

    def test_missing_risk_data_hot_market_caps_position_and_lowers_confidence(self) -> None:
        snapshot = copy.deepcopy(base_snapshot())
        snapshot["valuation"]["market"] = {
            "valuation_score": None,
            "index_pe_value_score": None,
            "index_pb_value_score": None,
            "erp_value_score": None,
        }
        snapshot["volatility"]["market"]["realized_vol_30d"] = None
        snapshot["data_quality"]["missing_fields"] = ["valuation.market", "volatility.market"]

        record = score_scenario("missing-risk-data-hot-market", snapshot)

        reasons = risk_reasons(record)
        self.assertGreaterEqual(record["market_opportunity_score"], 80)
        self.assertLessEqual(record["market_position_score"], 50)
        self.assertEqual(record["recommended_equity_position_range"], "40%-60%")
        self.assertIn("missing_valuation_data_hot_market", reasons)
        self.assertIn("missing_volatility_data_hot_market", reasons)
        self.assertIn("missing_core_risk_data_hot_market", reasons)
        self.assertEqual(record["confidence"], "medium")
        self.assertTrue(any("valuation data missing" in warning for warning in record["data_quality"]["warnings"]))
        self.assertTrue(any("volatility data missing" in warning for warning in record["data_quality"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
