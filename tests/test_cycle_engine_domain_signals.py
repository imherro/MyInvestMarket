from __future__ import annotations

import copy
import json
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cycle_engine_domain_signals as domain  # noqa: E402


class DomainSignalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        cls.evidence_audit = json.loads((ROOT / "data/cycle_engine_features_audit_v1.json").read_text(encoding="utf-8"))
        cls.output = json.loads((ROOT / "data/cycle_engine_domain_signals_v1.json").read_text(encoding="utf-8"))

    @staticmethod
    def row(month: str = "2020-01", ready: bool = True) -> dict:
        return {"month": month, "basis_trade_date": month + "-01", "features": {}}

    @staticmethod
    def put(row: dict, path: str, value, rank_value=None, ready=True, unit="percent") -> None:
        row["features"][path] = {"raw_value": value, "expanding_rank_pct": rank_value, "normalization_history_ready": ready, "unit": unit}

    def test_generated_output_and_audit_pass(self) -> None:
        result = domain.audit(self.output, self.evidence, self.evidence_audit)
        self.assertTrue(result["passed"], result)
        self.assertEqual(len(self.output["records"]), 200)
        self.assertEqual(self.output["start_month"], "2010-01")
        self.assertEqual(self.output["end_month"], "2026-08")
        self.assertEqual(len(self.output["reduction_policy"]), 34)
        self.assertNotIn("cycle_score", json.dumps(self.output))
        self.assertNotIn("market_score", json.dumps(self.output))

    def test_fixed_reduction_policy_has_no_duplicate_or_unapproved_paths(self) -> None:
        candidates = {path for path, value in self.evidence["records"][-1]["features"].items() if value["model_candidate"]}
        policy = domain.reduction_policy(candidates)
        self.assertEqual(set(policy), candidates)
        self.assertEqual(len(set(policy.values())), 7)
        self.assertNotIn("valuation.csi300_earnings_yield_pct.value", policy)
        self.assertNotIn("valuation.china_10y_government_bond_yield_pct.value", policy)

    def test_valuation_uses_three_subsignals_and_erp_direction(self) -> None:
        row = self.row()
        self.put(row, "valuation.indices.csi300.pe_ttm.percentile_expanding", 1, 10)
        self.put(row, "valuation.indices.csi300.pb.percentile_expanding", 1, 20)
        self.put(row, "valuation.indices.csi500.pe_ttm.percentile_expanding", 1, 20)
        self.put(row, "valuation.indices.csi500.pb.percentile_expanding", 1, 30)
        self.put(row, "valuation.csi300_erp_pct.value", 1, 75)
        result = domain.valuation(row)
        self.assertEqual(result["state"], "cheap")
        self.assertEqual(result["cheap_count"], 3)
        self.assertEqual(result["participating_components"], ["csi300", "csi500", "erp"])
        self.assertEqual(result["components"]["erp"]["state"], "cheap")
        self.assertEqual(result["components"]["csi1000"]["state"], "unavailable")
        self.assertIn("csi1000", result["unavailable_components"])
        self.assertNotIn("valuation.csi300_earnings_yield_pct.value", json.dumps(result))

    def test_two_component_median_is_the_average(self) -> None:
        row = self.row()
        self.put(row, "valuation.indices.csi300.pe_ttm.percentile_expanding", 1, 25)
        self.put(row, "valuation.indices.csi300.pb.percentile_expanding", 1, 40)
        self.put(row, "valuation.indices.csi500.pe_ttm.percentile_expanding", 1, 50)
        self.put(row, "valuation.indices.csi500.pb.percentile_expanding", 1, 50)
        self.put(row, "valuation.csi300_erp_pct.value", 1, 50)
        result = domain.valuation(row)
        self.assertEqual(result["components"]["csi300"]["state"], "neutral")

    def test_earnings_states_and_strict_natural_month_change(self) -> None:
        current = self.row("2020-04")
        prior = self.row("2020-01")
        for row, growth, quality, growth_raw in ((current, 60, 70, 8), (prior, 50, 50, 8)):
            self.put(row, "earnings.all_a_net_profit_yoy_pct.value", growth_raw, growth)
            self.put(row, "earnings.nonfinancial_a_net_profit_yoy_pct.value", growth_raw, growth)
            self.put(row, "earnings.all_a_roe_ttm_pct.value", 10, quality)
            self.put(row, "earnings.nonfinancial_a_roe_ttm_pct.value", 10, quality)
        recent = self.row("2020-03")
        for path in ("earnings.all_a_net_profit_yoy_pct.value", "earnings.nonfinancial_a_net_profit_yoy_pct.value", "earnings.all_a_roe_ttm_pct.value", "earnings.nonfinancial_a_roe_ttm_pct.value"):
            self.put(recent, path, 0, 0)
        result = domain.earnings(current, {"2020-04": current, "2020-01": prior, "2020-03": recent})
        self.assertEqual(result["growth_rank_change_3m"], 10)
        self.assertEqual(result["quality_rank_change_3m"], 20)
        self.assertEqual(result["state"], "expansion")

    def test_trend_reduces_six_features_to_one_state(self) -> None:
        row = self.row()
        fields = {"ma250_deviation_pct": (1, 90), "above_ma250": (True, None), "ma250_slope_3m_pct": (1, 70), "return_6m_pct": (5, 70), "return_12m_pct": (20, 90), "drawdown_12m_high_pct": (-1, 50)}
        for name, (value, rank_value) in fields.items():
            self.put(row, f"trend.indices.csi300.{name}.value", value, rank_value, unit="boolean" if name == "above_ma250" else "percent")
        self.assertEqual(domain.trend_index(row, "csi300")["state"], "extended")
        self.assertEqual(domain.trend_index(row, "csi300")["ready"], True)

    def test_readiness_and_a_fear_boundaries(self) -> None:
        for value, expected in ((0, "calm"), (20, "normal"), (40, "watch"), (60, "high_fear"), (80, "extreme_fear"), (100, "extreme_fear")):
            row = self.row()
            self.put(row, "sentiment.a_fear.fear_score", value, value)
            self.assertEqual(domain.sentiment(row)["state"], expected)
        by_month = {row["month"]: row for row in self.output["records"]}
        self.assertEqual(by_month["2026-08"]["sentiment_overlay"]["observations"], 25)
        self.assertFalse(by_month["2026-08"]["sentiment_overlay"]["model_ready"])
        self.assertFalse(by_month["2012-11"]["earnings"]["ready"])
        self.assertEqual(by_month["2012-11"]["earnings"]["state"], "insufficient_history")

    def test_csi1000_prelaunch_and_readiness_boundary(self) -> None:
        by_month = {row["month"]: row for row in self.output["records"]}
        self.assertFalse(by_month["2014-09"]["trend"]["csi1000"]["ready"])
        self.assertFalse(by_month["2014-10"]["trend"]["csi1000"]["ready"])
        self.assertFalse(by_month["2017-08"]["trend"]["csi1000"]["ready"])
        self.assertTrue(by_month["2017-09"]["trend"]["csi1000"]["ready"])
        self.assertEqual(by_month["2017-08"]["trend"]["csi1000"]["state"], "insufficient_history")

    def test_audit_mutations_fail(self) -> None:
        mutations = (("source_evidence_sha256", "source_evidence_hash_violation_count"), ("forbidden", "forbidden_output_violation_count"))
        for kind, counter in mutations:
            mutated = copy.deepcopy(self.output)
            if kind == "source_evidence_sha256":
                mutated["source_evidence_sha256"] = "bad"
            else:
                mutated["market_score"] = 1
            result = domain.audit(mutated, self.evidence, self.evidence_audit)
            self.assertGreater(result[counter], 0)
            self.assertFalse(result["passed"])
        failed = domain.audit(self.output, self.evidence, {"passed": False})
        self.assertGreater(failed["source_evidence_audit_violation_count"], 0)
        self.assertFalse(failed["passed"])
        mutated = copy.deepcopy(self.output)
        mutated["future_return"] = 1
        result = domain.audit(mutated, self.evidence, self.evidence_audit)
        self.assertGreater(result["future_information_dependency_count"], 0)
        self.assertFalse(result["passed"])

    def test_future_evidence_does_not_change_prior_domain_semantics(self) -> None:
        future = copy.deepcopy(self.evidence)
        future["records"][-1]["features"]["valuation.csi300_erp_pct.value"]["raw_value"] = 999999
        original = domain.build(self.evidence)
        changed = domain.build(future)
        cutoff = "2025-12"
        original_prior = [copy.deepcopy(row) for row in original["records"] if row["month"] <= cutoff]
        changed_prior = [copy.deepcopy(row) for row in changed["records"] if row["month"] <= cutoff]
        for row in original_prior + changed_prior:
            row.pop("source_evidence_sha256", None)
        self.assertEqual(original_prior, changed_prior)

    def test_phase2_does_not_reference_future_diagnostic_inputs(self) -> None:
        source = inspect.getsource(domain)
        for name in ("cycle_engine_evaluation_targets", "cycle_engine_feature_diagnostics", "cycle_engine_walk_forward_diagnostics", "cycle_engine_nonoverlap_diagnostics"):
            self.assertNotIn(name, source)

    def test_generation_does_not_modify_phase1_or_dataset_freeze_files(self) -> None:
        paths = [
            ROOT / "data/cycle_engine_features_v1.json", ROOT / "data/cycle_engine_features_audit_v1.json",
            ROOT / "data/cycle_dataset_v1.json", ROOT / "data/cycle_dataset_contract_v1.json",
            ROOT / "data/cycle_dataset_feature_availability_v1.json", ROOT / "data/cycle_dataset_golden_spots_v1.json",
            ROOT / "data/cycle_dataset_freeze_manifest_v1.json",
        ]
        before = {path: path.read_bytes() for path in paths}
        domain.generate()
        self.assertEqual(before, {path: path.read_bytes() for path in paths})


if __name__ == "__main__":
    unittest.main()
