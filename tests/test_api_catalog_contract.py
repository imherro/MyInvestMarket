from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import serve_market_web  # noqa: E402


class ApiCatalogContractTest(unittest.TestCase):
    def test_api_catalog_exposes_required_top_level_fields(self) -> None:
        catalog = serve_market_web.api_catalog_result()

        self.assertEqual(catalog["system_name"], "MyInvestMarketWeb")
        self.assertEqual(catalog["version"], 1)
        self.assertIn("A股市场研究", catalog["description"])
        self.assertEqual(catalog["system"]["name"], "MyInvestMarketWeb")
        self.assertIn("version", catalog["system"])
        self.assertIn("description", catalog["system"])
        self.assertEqual(catalog["base_url"], "http://127.0.0.1:8011")
        self.assertEqual(catalog["docs"]["docs"], "/docs")
        self.assertEqual(catalog["docs"]["redoc"], "/redoc")
        self.assertEqual(catalog["docs"]["openapi_json"], "/openapi.json")
        self.assertTrue(catalog["recommended_entrypoints"])
        self.assertTrue(catalog["safety"]["catalog_read_only"])
        self.assertTrue(catalog["groups"])
        self.assertEqual(
            catalog["total_endpoints"],
            sum(len(group["endpoints"]) for group in catalog["groups"]),
        )

    def test_every_catalog_endpoint_has_complete_description(self) -> None:
        catalog = serve_market_web.api_catalog_result()

        for group in catalog["groups"]:
            self.assertIn("key", group)
            self.assertIn("label", group)
            self.assertIn("description", group)
            self.assertTrue(group["endpoints"])
            for endpoint in group["endpoints"]:
                with self.subTest(path=endpoint.get("path"), method=endpoint.get("method")):
                    self.assertIn(endpoint["method"], {"GET", "POST"})
                    self.assertTrue(endpoint["path"].startswith("/"))
                    self.assertTrue(endpoint["purpose"])
                    self.assertIsInstance(endpoint["parameters"], list)
                    self.assertTrue(endpoint["response"])
                    self.assertIsInstance(endpoint["read_only"], bool)

    def test_catalog_is_read_only_and_score_endpoint_is_marked_write(self) -> None:
        catalog = serve_market_web.api_catalog_result()
        endpoints = {
            (endpoint["method"], endpoint["path"]): endpoint
            for group in catalog["groups"]
            for endpoint in group["endpoints"]
        }

        self.assertTrue(endpoints[("GET", "/api")]["read_only"])
        self.assertFalse(endpoints[("POST", "/api/score")]["read_only"])
        self.assertIn("不触发重计算", " ".join(catalog["safety"]["boundaries"]))
        self.assertIn("不下单", endpoints[("POST", "/api/score")]["safety_note"])

    def test_openapi_is_generated_from_catalog(self) -> None:
        openapi = serve_market_web.openapi_result()

        self.assertEqual(openapi["openapi"], "3.1.0")
        self.assertIn("/api", openapi["paths"])
        self.assertIn("get", openapi["paths"]["/api"])
        self.assertTrue(openapi["paths"]["/api"]["get"]["x-read-only"])
        self.assertFalse(openapi["paths"]["/api/score"]["post"]["x-read-only"])

    def test_homepage_index_contains_api_catalog_summary(self) -> None:
        index = serve_market_web.homepage_index_result()
        summary = index["api_catalog"]

        self.assertEqual(summary["endpoint"], "/api")
        self.assertGreaterEqual(summary["total_endpoints"], 1)
        self.assertTrue(summary["recommended_entrypoints"])
        self.assertTrue(summary["groups"])
        self.assertTrue(summary["safety"]["catalog_read_only"])


if __name__ == "__main__":
    unittest.main()
