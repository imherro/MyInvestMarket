from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cycle_engine_backtest as backtest  # noqa: E402
import serve_market_web  # noqa: E402


class CycleEngineBacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = json.loads((ROOT / "web/data/cycle-engine-backtest.json").read_text(encoding="utf-8"))

    def test_result_is_audited_and_uses_forward_returns_only_after_signal(self) -> None:
        self.assertTrue(self.result["audit"]["passed"])
        self.assertEqual(self.result["audit"]["future_information_dependency_count"], 0)
        for row in self.result["observations"]:
            self.assertGreater(row["execution_proxy_month"], row["signal_month"])

    def test_all_position_scenarios_and_benchmarks_are_present(self) -> None:
        self.assertEqual(set(backtest.SCENARIOS), set(self.result["series"]["strategies"]))
        self.assertEqual(set(backtest.BENCHMARKS), set(self.result["series"]["benchmarks"]))
        self.assertGreater(self.result["sample"]["return_observations"], 100)

    def test_backtest_is_reproducible_from_frozen_inputs(self) -> None:
        rebuilt = backtest.generate()
        self.assertEqual(rebuilt["sample"], self.result["sample"])
        self.assertEqual(rebuilt["summary"], self.result["summary"])
        self.assertEqual(rebuilt["audit"]["passed"], True)

    def test_api_and_homepage_expose_backtest(self) -> None:
        payload = serve_market_web.homepage_index_result()
        self.assertTrue(payload["cycle_engine_backtest"]["available"])
        catalog = serve_market_web.api_catalog_result()
        endpoints = [endpoint for group in catalog["groups"] for endpoint in group["endpoints"]]
        match = next(endpoint for endpoint in endpoints if endpoint["path"] == "/api/cycle-engine/backtest")
        self.assertTrue(match["read_only"])

    def test_page_has_results_and_home_link(self) -> None:
        page = (ROOT / "web/cycle-engine-backtest.html").read_text(encoding="utf-8")
        home = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("/api/cycle-engine/backtest", (ROOT / "web/cycle-engine-backtest.js").read_text(encoding="utf-8"))
        self.assertIn("cycle-engine-backtest.html", home)
        self.assertIn("逐月回测明细", page)
        self.assertIn('class="portal-nav"', page)
        self.assertIn('class="active" href="/cycle-engine-backtest.html"', page)
        self.assertIn('.portal-nav a[href="/cycle.html"] { order: 1; }', (ROOT / "web/cycle-engine-backtest.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
