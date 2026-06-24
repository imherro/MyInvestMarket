from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402
from tests.helpers import attach_allocation_policy  # noqa: E402


def score_record(*, warnings: list[str] | None = None, risk_caps: list[dict] | None = None, confidence: str = "medium") -> dict:
    modules = {
        key: {
            "label": meta["label"],
            "weight": meta["weight"],
            "score": meta["weight"] * 0.5,
            "score_pct": 50,
            "summary": "test",
            "evidence": [],
            "metrics": {},
        }
        for key, meta in market_scoring.MODULES.items()
    }
    return attach_allocation_policy({
        "run_id": "risk-overview-test",
        "scored_at": "2026-06-22T16:00:00+08:00",
        "basis_trade_date": "2026-06-18",
        "snapshot_sha256": "risk-overview-test",
        "model_version": market_scoring.MODEL_VERSION,
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
        "account_scope": "stock_account",
        "market_regime": "中性震荡偏结构",
        "market_opportunity_score": 50,
        "opportunity_score": 50,
        "crowding_penalty": 15,
        "pre_cap_market_position_score": 35,
        "market_position_score": 35,
        "base_market_position_score": 35,
        "recommended_equity_position_range": "20%-40%",
        "base_equity_position_range": "20%-40%",
        "equity_position_range": "20%-40%",
        "confidence": confidence,
        "data_quality": {
            "warnings": warnings or [],
            "missing_fields": ["valuation.indices.899050.BJ"],
            "sources_used": ["Tushare.daily", "BaoStock.query_history_k_data_plus"],
        },
        "risk_caps": risk_caps or [],
        "modules": modules,
        "crowding": {"penalty": 15, "items": []},
    })


class RiskOverviewContractTest(unittest.TestCase):
    def test_risk_overview_surfaces_confidence_warnings_and_caps(self) -> None:
        payload = serve_market_web.risk_overview_result(
            score_record(
                warnings=["rolling sample insufficient"],
                risk_caps=[{"reason": "bubble_top_combo", "severity": "high", "message": "泡沫顶部风险触发强仓位上限。"}],
                confidence="low",
            )
        )

        self.assertEqual(payload["status"], "risk")
        self.assertEqual(payload["confidence"]["value"], "low")
        self.assertEqual(payload["data_quality"]["warning_count"], 1)
        self.assertEqual(payload["data_quality"]["warnings"], ["rolling sample insufficient"])
        self.assertEqual(payload["data_quality"]["missing_field_count"], 1)
        self.assertEqual(payload["risk_caps"]["count"], 1)
        self.assertEqual(payload["risk_caps"]["items"][0]["reason"], "bubble_top_combo")

    def test_risk_overview_has_explicit_normal_messages(self) -> None:
        payload = serve_market_web.risk_overview_result(score_record(warnings=[], risk_caps=[], confidence="high"))

        self.assertEqual(payload["status"], "normal")
        self.assertEqual(payload["data_quality"]["message"], "暂无数据质量 warning。")
        self.assertEqual(payload["risk_caps"]["message"], "未触发风险上限。")

    def test_homepage_index_exposes_risk_overview(self) -> None:
        history = {
            "schema_version": market_scoring.HISTORY_SCHEMA_VERSION,
            "updated_at": "2026-06-22T16:10:00+08:00",
            "records": [score_record(warnings=["future-dated macro feature"], risk_caps=[])],
        }

        with patch.object(serve_market_web, "load_history", return_value=history):
            payload = serve_market_web.homepage_index_result()

        self.assertIn("risk_overview", payload)
        self.assertEqual(payload["risk_overview"]["data_quality"]["warnings"], ["future-dated macro feature"])
        self.assertIn("data_quality", payload["summary"])

    def test_frontend_contains_risk_overview_surface(self) -> None:
        index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        for element_id in ["riskOverviewStatus", "riskConfidence", "qualityWarnings", "riskCapList"]:
            self.assertIn(element_id, index_html)
        self.assertIn("renderRiskOverview()", app_js)
        self.assertIn("data_quality", app_js)
        self.assertIn("risk_caps", app_js)
        self.assertIn("暂无数据质量 warning", app_js)
        self.assertIn("未触发风险上限", app_js)


if __name__ == "__main__":
    unittest.main()
