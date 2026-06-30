import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import serve_market_web  # noqa: E402


class MarketDataStatusContractTest(unittest.TestCase):
    def test_expected_complete_trade_date_uses_post_close_rule(self) -> None:
        self.assertEqual(
            serve_market_web.expected_latest_complete_trade_date(
                datetime(2026, 6, 30, 14, 0, tzinfo=serve_market_web.TZ)
            ),
            "2026-06-29",
        )
        self.assertEqual(
            serve_market_web.expected_latest_complete_trade_date(
                datetime(2026, 6, 29, 18, 0, tzinfo=serve_market_web.TZ)
            ),
            "2026-06-29",
        )

    def test_flags_complete_data_without_matching_research(self) -> None:
        latest = {"basis_trade_date": "2026-06-26", "run_id": "old-run"}
        latest_research = {
            "results": {
                "market_snapshot": {"available": True, "basis_trade_date": "2026-06-29"},
                "market_analysis": {"available": True, "binding": {"consistent": True}},
            }
        }

        with patch.object(serve_market_web, "latest_local_snapshot_trade_date", return_value="2026-06-29"):
            status = serve_market_web.market_data_status_result(latest, latest_research)

        self.assertEqual(status["status"], "data_without_research")
        self.assertEqual(status["severity"], "critical")
        self.assertTrue(status["requires_attention"])
        self.assertEqual(status["latest_data_trade_date"], "2026-06-29")
        self.assertIn("重新执行收盘后市场研究", status["message"])

    def test_warns_when_expected_complete_day_is_newer_than_research_basis(self) -> None:
        latest = {"basis_trade_date": "2026-06-26", "run_id": "old-run"}
        latest_research = {
            "results": {
                "market_snapshot": {"available": True, "basis_trade_date": "2026-06-26"},
                "market_analysis": {"available": True, "binding": {"consistent": True}},
            }
        }

        with (
            patch.object(serve_market_web, "latest_local_snapshot_trade_date", return_value="2026-06-26"),
            patch.object(serve_market_web, "expected_latest_complete_trade_date", return_value="2026-06-29"),
        ):
            status = serve_market_web.market_data_status_result(latest, latest_research)

        self.assertEqual(status["status"], "expected_complete_research_lag")
        self.assertEqual(status["severity"], "warning")
        self.assertTrue(status["requires_attention"])
        self.assertIn("自动化是否执行", status["message"])

    def test_flags_missing_analysis_binding(self) -> None:
        latest = {"basis_trade_date": "2026-06-29", "run_id": "current-run"}
        latest_research = {
            "results": {
                "market_snapshot": {"available": True, "basis_trade_date": "2026-06-29"},
                "market_analysis": {
                    "available": False,
                    "binding": {"consistent": False},
                    "error": "latest analysis report does not match latest market score",
                },
            }
        }

        with patch.object(serve_market_web, "latest_local_snapshot_trade_date", return_value="2026-06-29"):
            status = serve_market_web.market_data_status_result(latest, latest_research)

        self.assertEqual(status["status"], "research_binding_mismatch")
        self.assertEqual(status["severity"], "critical")
        self.assertFalse(status["analysis_available"])
        self.assertFalse(status["analysis_binding_consistent"])

    def test_homepage_index_exposes_market_data_status(self) -> None:
        payload = serve_market_web.homepage_index_result()

        self.assertIn("market_data_status", payload)
        self.assertIn("basis_trade_date", payload["market_data_status"])
        self.assertIn(payload["market_data_status"]["severity"], {"normal", "warning", "critical"})

    def test_frontend_promotes_basis_status_and_removes_latest_api_card(self) -> None:
        index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="basisStatusBand"', index_html)
        self.assertLess(index_html.index('id="basisStatusBand"'), index_html.index('class="summary-grid"'))
        self.assertNotIn("最新研究结果 API", index_html)
        self.assertNotIn("apiStatus", index_html)
        self.assertIn("renderBasisStatus()", app_js)
        self.assertNotIn("loadResearchApiStatus", app_js)


if __name__ == "__main__":
    unittest.main()
