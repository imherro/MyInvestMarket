from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_post_close_update  # noqa: E402
import market_scoring  # noqa: E402
import serve_market_web  # noqa: E402
from tests.helpers import attach_allocation_policy  # noqa: E402


def score_record() -> dict:
    return attach_allocation_policy({
        "run_id": "20260622T170000-test",
        "basis_trade_date": "2026-06-18",
        "model_version": market_scoring.MODEL_VERSION,
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
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
        "data_quality": {"missing_fields": [], "warnings": []},
    })


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
        "/api/service": {
            "available": True,
            "model_version": record["model_version"],
            "position_policy_version": record["position_policy_version"],
            "allocation_policy_version": record["allocation_policy_version"],
        },
        "/api/index": {
            "available": True,
            "model_version": record["model_version"],
            "position_policy_version": record["position_policy_version"],
            "allocation_policy_version": record["allocation_policy_version"],
            "summary": {
                "run_id": record["run_id"],
                "basis_trade_date": record["basis_trade_date"],
                "recommended_equity_position_range": record["recommended_equity_position_range"],
                "risk_penalty_score": record["risk_penalty_score"],
                "risk_discount": record["risk_discount"],
                "risk_engine": record["risk_engine"],
                "position_model": record["position_model"],
                "decision_explain": record["decision_explain"],
                "market_regime_code": record["market_regime_code"],
                "market_regime_label": record["market_regime_label"],
                "market_regime_layer": record["market_regime_layer"],
                "trend_state": record["trend_state"],
                "trend_state_label": record["trend_state_label"],
                "trend_strength": record["trend_strength"],
                "trend_duration": record["trend_duration"],
                "market_trend_layer": record["market_trend_layer"],
            },
            "position_policy_map": {
                "position_policy_version": record["position_policy_version"],
                "current": {"market_position_score": record["market_position_score"]},
            },
            "allocation_policy": {
                **record["allocation_policy"],
                "history": [
                    {
                        "basis_trade_date": record["basis_trade_date"],
                        "scored_at": record.get("scored_at"),
                        "state": record["allocation_policy"]["state"],
                        "sleeves": {
                            sleeve["key"]: {"target_range": sleeve["target_range"], "midpoint": sleeve["midpoint"]}
                            for sleeve in record["allocation_policy"]["sleeves"]
                        },
                    }
                ],
            },
            "market_cycle_reference": {
                "waves": [{"wave": "1"}],
                "current_profile": {
                    "available": True,
                    "label": "高位过热风控特征",
                    "is_wave_prediction": False,
                },
            },
        },
        "/api/research/latest/market-score": {
            "available": True,
            "record": record,
        },
        "/api/research/latest/market-analysis": {
            "available": True,
            "metadata": {"file": "data/market_analysis_test.md"},
            "binding": {
                "run_id": record["run_id"],
                "basis_trade_date": record["basis_trade_date"],
                "expected_run_id": record["run_id"],
                "expected_basis_trade_date": record["basis_trade_date"],
                "consistent": True,
            },
        },
        "/api/research/latest/model-validation": {
            "available": True,
            "payload": {
                "available": True,
                "sample": {"lookahead_safe": True},
                "comparison": {
                    "v3": {
                        "metrics": {
                            "total_return": 0.01,
                            "sharpe_ratio": 0.5,
                            "max_drawdown": 0.02,
                            "period_count": 5.0,
                        },
                        "nav_curve": [{"date": record["basis_trade_date"], "nav": 1.01}],
                    }
                },
            },
        },
        "/api/research/latest/model-health": {
            "available": True,
            "payload": {
                "available": True,
                "model_health": {
                    "backtest_metrics": {
                        "total_return": 0.01,
                        "sharpe_ratio": 0.5,
                        "max_drawdown": 0.02,
                        "period_count": 5.0,
                    }
                },
            },
        },
        "/api/research/latest/strategy-robustness": {
            "available": True,
            "payload": {
                "available": True,
                "deployable": False,
                "oos_validation": {
                    "splits": {
                        "test": {"end": record["basis_trade_date"]},
                    }
                },
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
        self.assertIn("## 周期特征参照", content)
        self.assertIn("- 当前特征:", content)
        self.assertIn("不判定当前处于某个具体浪位", content)
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
        self.assertEqual(result["service_version"]["model_version"], market_scoring.MODEL_VERSION)
        self.assertEqual(result["analysis_report"]["binding"]["consistent"], True)

    def test_validate_api_payloads_rejects_mismatched_analysis(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/research/latest/market-analysis"]["binding"]["run_id"] = "stale-run"
        payloads["/api/research/latest/market-analysis"]["binding"]["consistent"] = False

        with self.assertRaisesRegex(RuntimeError, "binding is inconsistent"):
            run_post_close_update.validate_api_payloads(payloads)

    def test_validate_api_payloads_rejects_service_model_version_mismatch(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/service"]["model_version"] = "stale_model"

        with self.assertRaisesRegex(RuntimeError, "MODEL_VERSION"):
            run_post_close_update.validate_api_payloads(payloads)

    def test_validate_api_payloads_rejects_index_policy_version_mismatch(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/index"]["position_policy_version"] = "stale_policy"

        with self.assertRaisesRegex(RuntimeError, "POSITION_POLICY_VERSION"):
            run_post_close_update.validate_api_payloads(payloads)

    def test_validate_api_payloads_rejects_stale_validation_basis(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/research/latest/model-validation"]["payload"]["comparison"]["v3"]["nav_curve"][0]["date"] = "2026-06-17"

        with self.assertRaisesRegex(RuntimeError, "model validation basis_trade_date"):
            run_post_close_update.validate_api_payloads(payloads)

    def test_validate_api_payloads_rejects_health_metric_mismatch(self) -> None:
        payloads = copy.deepcopy(valid_api_payloads())
        payloads["/api/research/latest/model-health"]["payload"]["model_health"]["backtest_metrics"]["sharpe_ratio"] = 0.25

        with self.assertRaisesRegex(RuntimeError, "model health sharpe_ratio"):
            run_post_close_update.validate_api_payloads(payloads)

    def test_incomplete_market_data_skip_result_reports_missing_fields(self) -> None:
        error = market_scoring.MarketSnapshotValidationError(
            "capital_flow.main_net_inflow_100m_cny: required numeric value; "
            "sector_rotation.top5_industries_by_return: required non-empty list"
        )

        with (
            patch.object(run_post_close_update, "verify_api", return_value={"validation": {"ok": True}}),
            patch.object(run_post_close_update.build_market_dataset, "tushare_client", return_value=object()),
            patch.object(
                run_post_close_update.build_market_dataset,
                "fetch_latest_complete_trade_date",
                return_value=("20260623", object(), object()),
            ),
        ):
            result = run_post_close_update.incomplete_market_data_skip_result(date(2026, 6, 23), error)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "latest candidate trading day data is incomplete")
        self.assertEqual(result["basis_trade_date"], "2026-06-23")
        self.assertEqual(
            result["missing_fields"],
            [
                "capital_flow.main_net_inflow_100m_cny",
                "sector_rotation.top5_industries_by_return",
            ],
        )
        self.assertEqual(result["api"]["validation"]["ok"], True)

    def test_service_version_result_exposes_local_versions(self) -> None:
        payload = serve_market_web.service_version_result()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["model_version"], market_scoring.MODEL_VERSION)
        self.assertEqual(payload["position_policy_version"], market_scoring.POSITION_POLICY_VERSION)
        self.assertEqual(payload["allocation_policy_version"], market_scoring.ALLOCATION_POLICY_VERSION)

    def test_latest_record_prefers_basis_date_over_backfill_scored_at(self) -> None:
        latest_trade_day = {
            "run_id": "latest-trade-day",
            "basis_trade_date": "2026-07-06",
            "scored_at": "2026-07-07T09:16:17+08:00",
        }
        late_backfill = {
            "run_id": "late-backfill",
            "basis_trade_date": "2026-07-03",
            "scored_at": "2026-07-07T09:27:27+08:00",
        }

        self.assertEqual(
            run_post_close_update.latest_record({"records": [latest_trade_day, late_backfill]})["run_id"],
            "latest-trade-day",
        )

        with patch.object(serve_market_web, "score_records", return_value=[latest_trade_day, late_backfill]):
            payload = serve_market_web.latest_market_score_result()

        self.assertEqual(payload["record"]["run_id"], "latest-trade-day")


if __name__ == "__main__":
    unittest.main()
