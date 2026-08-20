from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a_fear  # noqa: E402
import run_post_close_update  # noqa: E402
import serve_market_web  # noqa: E402


def record(trade_date: str, score: float) -> dict:
    return {
        "version": a_fear.VERSION,
        "basis_trade_date": trade_date,
        "official": True,
        "fear_score": score,
        "realized_fear_proxy": score - 2,
        "change_1d": 5,
        "change_3d": 9,
        "level": {"code": "high", "label": "高恐慌"},
        "phase": {"code": "fear_rising", "label": "恐慌升温"},
        "confidence": "high",
        "components": {
            "implied_volatility": {"score": score, "weight": 0.4},
            "downside_volatility": {"score": score, "weight": 0.2},
            "market_breadth": {"score": score, "weight": 0.25},
            "tail_loss": {"score": score, "weight": 0.15},
        },
        "metrics": {"io_iv_30d": {"sample_count": 500}},
        "fear_300": score - 3,
        "fear_1000": score + 3,
        "small_cap_fear_spread": 6,
        "data_quality": {"warnings": [], "missing_fields": []},
    }


class AFearApiTests(unittest.TestCase):
    def test_latest_history_components_and_status_are_read_only(self) -> None:
        records = [record("2026-08-18", 60), record("2026-08-19", 75)]
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "history.json"
            source_path = Path(temp_dir) / "source.json"
            history_path.write_text(json.dumps({"records": records}), encoding="utf-8")
            source_path.write_text(json.dumps({"observations": []}), encoding="utf-8")
            with (
                patch.object(a_fear, "DEFAULT_HISTORY_PATH", history_path),
                patch.object(a_fear, "DEFAULT_SOURCE_CACHE_PATH", source_path),
                patch.object(serve_market_web, "expected_latest_complete_trade_date", return_value="2026-08-19"),
            ):
                latest = serve_market_web.latest_a_fear_result()
                history = serve_market_web.a_fear_history_result("2026-08-19", "2026-08-19")
                components = serve_market_web.latest_a_fear_components_result()
                status = serve_market_web.a_fear_status_result()

        self.assertTrue(latest["available"])
        self.assertFalse(latest["safety"]["triggers_recalculation"])
        self.assertEqual(history["record_count"], 1)
        self.assertEqual(components["small_cap_fear_spread"], 6)
        self.assertFalse(status["stale"])

    def test_catalog_lists_all_fear_endpoints_as_read_only(self) -> None:
        endpoints = {
            endpoint["path"]: endpoint
            for group in serve_market_web.api_catalog_result()["groups"]
            for endpoint in group["endpoints"]
        }
        for path in (
            "/api/fear/latest",
            "/api/fear/history",
            "/api/fear/components/latest",
            "/api/fear/status",
        ):
            self.assertIn(path, endpoints)
            self.assertTrue(endpoints[path]["read_only"])

    def test_report_states_fear_is_not_a_buy_score(self) -> None:
        section = run_post_close_update.fear_report_section(record("2026-08-19", 75))
        self.assertIn("A-FEAR", section)
        self.assertIn("不是买入分", section)
        self.assertIn("中证1000恐慌", section)


if __name__ == "__main__":
    unittest.main()
