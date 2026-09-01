from __future__ import annotations

import copy
import json
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_valuation_boundaries_and_readiness_are_explicit(self) -> None:
        for erp_rank, expected in ((80, "cheap"), (20, "expensive")):
            row = self.row()
            for path, value in (
                ("valuation.indices.csi300.pe_ttm.percentile_expanding", 50),
                ("valuation.indices.csi300.pb.percentile_expanding", 50),
                ("valuation.indices.csi500.pe_ttm.percentile_expanding", 50),
                ("valuation.indices.csi500.pb.percentile_expanding", 50),
                ("valuation.csi300_erp_pct.value", 1),
            ):
                self.put(row, path, value, erp_rank if path.endswith("erp_pct.value") else 50, ready=True)
            result = domain.valuation(row)
            self.assertEqual(result["components"]["erp"]["state"], expected)

        row = self.row()
        for path, value, rank_value in (
            ("valuation.indices.csi300.pe_ttm.percentile_expanding", 1, 20),
            ("valuation.indices.csi300.pb.percentile_expanding", 1, 80),
            ("valuation.indices.csi500.pe_ttm.percentile_expanding", 1, 50),
            ("valuation.indices.csi500.pb.percentile_expanding", 1, 50),
            ("valuation.csi300_erp_pct.value", 1, 50),
        ):
            self.put(row, path, value, rank_value, ready=True)
        result = domain.valuation(row)
        self.assertEqual(result["components"]["csi300"]["state"], "neutral")
        self.assertEqual(result["components"]["csi300"]["ready"], True)

        self.put(row, "valuation.indices.csi300.pe_ttm.percentile_expanding", 1, 20, ready=False)
        result = domain.valuation(row)
        self.assertFalse(result["components"]["csi300"]["ready"])
        self.assertEqual(result["components"]["csi300"]["pe"]["state"], "insufficient_history")
        self.assertEqual(result["components"]["csi300"]["state"], "insufficient_history")
        self.assertEqual(result["cheap_count"], 0)
        self.assertEqual(result["expensive_count"], 0)
        self.assertNotIn("csi300", result["participating_components"])

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
        self.assertFalse(by_month["2012-11"]["valuation"]["ready"])
        self.assertEqual(by_month["2012-11"]["valuation"]["state"], "insufficient_history")
        self.assertIn("normalization_history_observations", by_month["2026-08"]["sentiment_overlay"])

    def test_csi1000_prelaunch_and_readiness_boundary(self) -> None:
        by_month = {row["month"]: row for row in self.output["records"]}
        self.assertFalse(by_month["2014-09"]["trend"]["csi1000"]["ready"])
        self.assertFalse(by_month["2014-10"]["trend"]["csi1000"]["ready"])
        self.assertFalse(by_month["2017-08"]["trend"]["csi1000"]["ready"])
        self.assertTrue(by_month["2017-09"]["trend"]["csi1000"]["ready"])
        self.assertEqual(by_month["2017-08"]["trend"]["csi1000"]["state"], "insufficient_history")
        self.assertEqual(by_month["2017-08"]["trend"]["participating_indices"], ["csi300", "csi500"])
        self.assertEqual(by_month["2017-08"]["trend"]["dispersion"], 2)

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

    def test_domain_rule_mutations_hit_specific_audit_counters(self) -> None:
        cases = (
            ("valuation", "valuation_reduction_violation_count"),
            ("earnings", "earnings_reduction_violation_count"),
            ("macro_confirmation", "macro_confirmation_violation_count"),
            ("trend", "trend_domain_reduction_violation_count"),
            ("sentiment_overlay", "sentiment_overlay_violation_count"),
        )
        for section, counter in cases:
            mutated = copy.deepcopy(self.output)
            if section == "sentiment_overlay":
                mutated["records"][0][section]["state"] = "calm"
            else:
                mutated["records"][0][section]["state"] = "mutated"
            result = domain.audit(mutated, self.evidence, self.evidence_audit)
            self.assertGreater(result[counter], 0, section)
            self.assertFalse(result["passed"])

    def test_sentiment_cannot_leak_into_core_domain(self) -> None:
        mutated = copy.deepcopy(self.output)
        mutated["records"][0]["valuation"]["a_fear"] = 50
        result = domain.audit(mutated, self.evidence, self.evidence_audit)
        self.assertGreater(result["sentiment_core_leakage_count"], 0)
        self.assertFalse(result["passed"])

    def test_audit_uses_independent_replay(self) -> None:
        source = inspect.getsource(domain.audit)
        for name in ("build(", "valuation(", "earnings(", "macro_confirmation(", "trend_index(", "trend(", "sentiment(", "reduce_record("):
            self.assertNotIn(name, source)

    def test_evidence_mutation_hits_fixed_source_gate(self) -> None:
        mutated_evidence = copy.deepcopy(self.evidence)
        mutated_evidence["records"][0]["features"]["valuation.csi300_erp_pct.value"]["raw_value"] = 999999
        result = domain.audit(self.output, mutated_evidence, self.evidence_audit)
        self.assertGreater(result["source_evidence_hash_violation_count"], 0)
        self.assertGreater(result["upstream_mutation_count"], 0)
        self.assertFalse(result["passed"])

    def test_mutated_evidence_and_regenerated_output_cannot_bypass_audit(self) -> None:
        mutated_evidence = copy.deepcopy(self.evidence)
        mutated_evidence["records"][0]["features"]["valuation.csi300_erp_pct.value"]["raw_value"] = 999999
        regenerated = domain.build(mutated_evidence)
        result = domain.audit(regenerated, mutated_evidence, self.evidence_audit)
        self.assertGreater(result["source_evidence_hash_violation_count"], 0)
        self.assertGreater(result["upstream_mutation_count"], 0)
        self.assertFalse(result["passed"])

    def test_independent_audit_rejects_production_reducer_mutation(self) -> None:
        original = domain.valuation

        def wrong_valuation(row):
            value = original(row)
            value["state"] = "cheap"
            return value

        with patch.object(domain, "valuation", side_effect=wrong_valuation):
            regenerated = domain.build(self.evidence)
        result = domain.audit(regenerated, self.evidence, self.evidence_audit)
        self.assertGreater(result["valuation_reduction_violation_count"], 0)
        self.assertFalse(result["passed"])

    def test_natural_month_numeric_change_mutation_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.output)
        record = next(item for item in mutated["records"] if item["earnings"]["growth_rank_change_3m"] is not None)
        record["earnings"]["growth_rank_change_3m"] += 1
        result = domain.audit(mutated, self.evidence, self.evidence_audit)
        self.assertGreater(result["natural_month_change_violation_count"], 0)
        self.assertFalse(result["passed"])

    def test_future_decision_inputs_do_not_change_prior_semantics(self) -> None:
        future = copy.deepcopy(self.evidence)
        for row in future["records"]:
            if row["month"] <= "2025-12":
                continue
            for item in row["features"].values():
                if isinstance(item.get("raw_value"), bool):
                    item["raw_value"] = not item["raw_value"]
                elif isinstance(item.get("raw_value"), (int, float)):
                    item["raw_value"] = 999999
                if item.get("expanding_rank_pct") is not None:
                    item["expanding_rank_pct"] = 0
        original = domain.build(self.evidence)
        changed = domain.build(future)
        def prior(records):
            return [{k: v for k, v in row.items() if k != "source_evidence_sha256"} for row in records if row["month"] <= "2025-12"]
        self.assertEqual(prior(original["records"]), prior(changed["records"]))

    def test_a_fear_change_only_changes_overlay(self) -> None:
        future = copy.deepcopy(self.evidence)
        for row in future["records"]:
            if row["month"] == "2025-12":
                row["features"]["sentiment.a_fear.fear_score"]["raw_value"] = 100
        original = domain.build(self.evidence)
        changed = domain.build(future)
        before = next(row for row in original["records"] if row["month"] == "2025-12")
        after = next(row for row in changed["records"] if row["month"] == "2025-12")
        for section in ("valuation", "earnings", "macro_confirmation", "trend"):
            self.assertEqual(before[section], after[section])
        self.assertNotEqual(before["sentiment_overlay"], after["sentiment_overlay"])

    def test_readiness_mutation_is_a_hard_failure(self) -> None:
        mutated = copy.deepcopy(self.output)
        mutated["records"][0]["valuation"]["ready"] = not mutated["records"][0]["valuation"]["ready"]
        result = domain.audit(mutated, self.evidence, self.evidence_audit)
        self.assertGreater(result["readiness_violation_count"], 0)
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
