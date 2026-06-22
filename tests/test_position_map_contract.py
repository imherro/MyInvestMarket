from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402


def band_for_score(bands: list[dict], score: float) -> dict:
    for index, band in enumerate(bands):
        is_last = index == len(bands) - 1
        if score >= band["score_min"] and (score < band["score_max"] or (is_last and score <= band["score_max"])):
            return band
    raise AssertionError(f"no band covers score {score}")


class PositionMapContractTest(unittest.TestCase):
    def test_api_index_returns_position_policy_map(self) -> None:
        payload = serve_market_web.homepage_index_result()
        policy_map = payload.get("position_policy_map")

        self.assertIsInstance(policy_map, dict)
        self.assertEqual(policy_map.get("account_scope"), "stock_account")
        self.assertEqual(policy_map.get("position_policy_version"), "stock_account_position_policy_v2")
        self.assertEqual(policy_map.get("score_min"), 0)
        self.assertEqual(policy_map.get("score_max"), 100)
        self.assertEqual(policy_map.get("position_min"), 0)
        self.assertEqual(policy_map.get("position_max"), 100)
        self.assertTrue(policy_map.get("bands"))

    def test_position_bands_match_scoring_function(self) -> None:
        policy_map = serve_market_web.homepage_index_result()["position_policy_map"]
        bands = policy_map["bands"]
        expectations = {
            10: "0%-20%",
            30: "20%-40%",
            45: "40%-60%",
            60: "55%-75%",
            75: "75%-90%",
            85: "90%-100%",
        }

        for score, expected_range in expectations.items():
            self.assertEqual(market_scoring.position_range(score), expected_range)
            self.assertEqual(band_for_score(bands, score)["position_range"], expected_range)

    def test_current_point_fields_are_complete_when_history_exists(self) -> None:
        payload = serve_market_web.homepage_index_result()
        current = payload["position_policy_map"]["current"]

        if payload.get("available"):
            self.assertIsNotNone(current.get("market_position_score"))
            self.assertIsNotNone(current.get("recommended_equity_position_range"))
            self.assertIn("pre_cap_market_position_score", current)
            self.assertIsInstance(current.get("risk_caps"), list)

    def test_frontend_no_longer_uses_score_as_cycle_stage(self) -> None:
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("markerX = xForStage(clamp(currentScore", app_js)
        self.assertNotIn("市场循环阶段", app_js)
        self.assertNotIn("Elliott", app_js)

    def test_frontend_official_position_range_prefers_recommended_field(self) -> None:
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        function_start = app_js.index("function officialPositionRange(record)")
        function_body = app_js[function_start : function_start + 240]

        self.assertIn("recommended_equity_position_range", function_body)
        self.assertLess(
            function_body.index("recommended_equity_position_range"),
            function_body.index("base_equity_position_range"),
        )


if __name__ == "__main__":
    unittest.main()
