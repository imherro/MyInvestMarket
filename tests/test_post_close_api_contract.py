from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_post_close_update  # noqa: E402
import serve_market_web  # noqa: E402


def score_record() -> dict:
    return {
        "run_id": "20260622T170000-test",
        "basis_trade_date": "2026-06-18",
        "model_version": "a_share_market_score_v1_4",
        "position_policy_version": "stock_account_position_policy_v2",
        "market_regime": "中性震荡偏结构",
        "market_opportunity_score": 57.37,
        "crowding_penalty": 19.91,
        "pre_cap_market_position_score": 37.46,
        "market_position_score": 35.0,
        "recommended_equity_position_range": "20%-40%",
        "confidence": "medium",
        "risk_caps": [],
        "modules": {},
        "crowding": {},
    }


def snapshot() -> dict:
    return {
        "breadth": {"advancers": 1000, "decliners": 3000, "median_pct_change": -0.6},
        "valuation": {"market": {"valuation_score": 20}},
        "volatility": {"market": {"realized_vol_30d": 0.25}},
        "capital_flow": {"northbound_net_inflow_100m_cny": 10, "main_net_inflow_100m_cny": -100},
        "sector_rotation": {},
    }


def valid_api_payloads() -> dict:
    record = score_record()
    return {
        "/api/index": {
            "available": True,
            "summary": {
                "run_id": record["run_id"],
                "basis_trade_date": record["basis_trade_date"],
                "recommended_equity_position_range": record["recommended_equity_position_range"],
            },
            "position_policy_map": {
                "position_policy_version": record["position_policy_version"],
                "current": {"market_position_score": record["market_position_score"]},
            },
        },
        "/api/research/latest/market-score": {
            "available": True,
            "record": record,
        },
        "/api/research/latest/market-analysis": {
            "available": True,
            "metadata": {"file": "data/chatgpt_market_analysis_test.md"},
            "binding": {
                "run_id": record["run_id"],
                "basis_trade_date": record["basis_trade_date"],
                "expected_run_id": record["run_id"],
                "expected_basis_trade_date": record["basis_trade_date"],
                "consistent": True,
            },
        },
    }


class PostCloseApiContractTest(unittest.TestCase):
    def test_write_report_includes_score_binding_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(run_post_close_update, "DATA_DIR", Path(tmp_dir)):
                path = run_post_close_update.write_report(snapshot(), score_record())
                content = path.read_text(encoding="utf-8")

        binding = serve_market_web.analysis_report_binding(content, score_record())

        self.assertIn("- 评分运行ID: 20260622T170000-test", content)
        self.assertEqual(binding["run_id"], "20260622T170000-test")
        self.assertEqual(binding["basis_trade_date"], "2026-06-18")
        self.assertTrue(binding["consistent"])

    def test_analysis_report_binding_detects_mismatch(self) -> None:
        content = "- 评分运行ID: stale-run\n- 数据基准日: 2026-06-18\n"

        binding = serve_market_web.analysis_report_binding(content, score_record())

        self.assertFalse(binding["consistent"])
        self.assertEqual(binding["expected_run_id"], "20260622T170000-test")

    def test_validate_api_payloads_accepts_consistent_payloads(self) -> None:
        result = run_post_close_update.validate_api_payloads(valid_api_payloads())

        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "20260622T170000-test")
        self.assertEqual(result["analysis_report"]["binding"]["consistent"], True)

    def test_validate_api_payloads_rejects_mismatched_analysis(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/research/latest/market-analysis"]["binding"]["run_id"] = "stale-run"
        payloads["/api/research/latest/market-analysis"]["binding"]["consistent"] = False

        with self.assertRaisesRegex(RuntimeError, "binding is inconsistent"):
            run_post_close_update.validate_api_payloads(payloads)


if __name__ == "__main__":
    unittest.main()
