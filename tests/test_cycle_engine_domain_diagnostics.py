from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cycle_engine_domain_diagnostics as diagnostics  # noqa: E402


class DomainDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase2 = json.loads((ROOT / "data/cycle_engine_domain_signals_v1.json").read_text(encoding="utf-8"))
        cls.phase2_audit = json.loads((ROOT / "data/cycle_engine_domain_signals_audit_v1.json").read_text(encoding="utf-8"))
        cls.targets = json.loads((ROOT / "data/cycle_engine_evaluation_targets_v1.json").read_text(encoding="utf-8"))
        cls.output = json.loads((ROOT / "data/cycle_engine_domain_diagnostics_v1.json").read_text(encoding="utf-8"))

    def test_frozen_phase2_gate_and_audit_pass(self) -> None:
        self.assertEqual(hashlib.sha256((ROOT / "data/cycle_engine_domain_signals_v1.json").read_bytes()).hexdigest(), diagnostics.FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)
        result = diagnostics.audit(self.output, self.phase2, self.phase2_audit, self.targets)
        self.assertTrue(result["passed"], result)
        self.assertEqual(self.output["record_count"], 200)
        self.assertEqual((self.output["start_month"], self.output["end_month"]), ("2010-01", "2026-08"))

    def test_coverage_and_distribution_are_consistent(self) -> None:
        for domain in diagnostics.DOMAINS:
            coverage = self.output["coverage"][domain]
            distribution = self.output["state_distribution"][domain]
            self.assertEqual(sum(item["month_count"] for item in distribution["states"].values()), distribution["ready_month_count"])
            self.assertEqual(coverage["ready_month_count"], distribution["ready_month_count"])

    def test_transition_and_run_length_fixture(self) -> None:
        records = [
            {"month": "2020-01", "valuation": {"state": "cheap", "ready": True}},
            {"month": "2020-02", "valuation": {"state": "cheap", "ready": True}},
            {"month": "2020-03", "valuation": {"state": "neutral", "ready": True}},
            {"month": "2020-04", "valuation": {"state": "neutral", "ready": True}},
        ]
        result = diagnostics.transitions(records, "valuation")
        self.assertEqual(result["transition_matrix"]["cheap->cheap"]["transition_count"], 1)
        self.assertEqual(result["transition_matrix"]["cheap->neutral"]["transition_count"], 1)
        self.assertEqual(result["median_state_duration_months"], 2.0)
        self.assertEqual(diagnostics.target_run_lengths(["cheap", "neutral", "neutral", "cheap"], "cheap"), [1, 1])

    def test_conflict_duration_uses_only_hit_runs(self) -> None:
        records = []
        for month, valuation, trend in (("2020-01", "cheap", "damaged"), ("2020-02", "neutral", "damaged"), ("2020-03", "neutral", "damaged"), ("2020-04", "cheap", "damaged")):
            records.append({"month": month, "valuation": {"state": valuation, "ready": True}, "earnings": {"state": "mixed", "ready": True}, "macro_confirmation": {"state": "mixed", "ready": True}, "trend": {"state": trend, "ready": True}})
        self.assertEqual(diagnostics.conflicts(records)["valuation_cheap_damaged"]["longest_duration"], 1)

    def test_nonoverlap_origins_are_spaced(self) -> None:
        for benchmark in self.output["evaluation"]["benchmarks"].values():
            for horizon_key, horizon in benchmark.items():
                h = int(horizon_key.split("_")[1][:-1])
                for domain in diagnostics.CORE:
                    for state_data in horizon[domain].values():
                        origins = state_data["origin_months"]
                        self.assertEqual(len(origins), len(set(origins)))
                        for cohort in range(h):
                            months = sorted(diagnostics.month_index(month) for month in origins if diagnostics.month_index(month) % h == cohort)
                            self.assertTrue(all(b - a >= h for a, b in zip(months, months[1:])))

    def test_phase2_mutation_is_hard_rejected(self) -> None:
        mutated = copy.deepcopy(self.phase2)
        mutated["records"][0]["valuation"]["state"] = "expensive"
        with patch.object(diagnostics, "load_sources", return_value=(mutated, self.phase2_audit, self.targets)):
            with self.assertRaises(RuntimeError):
                diagnostics.generate()

    def test_phase2_audit_failure_is_hard_rejected(self) -> None:
        with patch.object(diagnostics, "PHASE2_AUDIT_PATH", ROOT / "data/cycle_engine_domain_signals_audit_v1.json"):
            with patch.object(diagnostics, "load_sources", return_value=(self.phase2, {"passed": False}, self.targets)):
                with self.assertRaises(RuntimeError):
                    diagnostics.generate()

    def test_target_mutation_only_changes_evaluation(self) -> None:
        mutated_targets = copy.deepcopy(self.targets)
        target = next(record for record in mutated_targets["records"] if record["month"] == "2012-12")
        target["benchmarks"]["csi300"]["forward_6m"]["forward_return_pct"] = 999.0
        original = diagnostics.build(self.phase2, self.targets)
        changed = diagnostics.build(self.phase2, mutated_targets)
        for key in ("coverage", "state_distribution", "transitions", "combinations", "conflicts", "timeline", "window_extracts"):
            self.assertEqual(original[key], changed[key])
        self.assertNotEqual(original["evaluation"], changed["evaluation"])

    def test_no_global_score_state_or_position_output(self) -> None:
        text = json.dumps(self.output, ensure_ascii=False).lower()
        for token in ("cycle_score", "bull_bear_score", "market_score", "cycle_state", "regime", "recommended_position", "equity_position", "allocation", "buy_signal", "sell_signal", "state_machine"):
            self.assertNotIn(token, text)
        self.assertTrue(self.output["phase3_design_evidence"]["state_forward_return_summary"])
        self.assertTrue(self.output["phase3_design_evidence"]["state_sample_sizes"])
        self.assertTrue(self.output["phase3_design_evidence"]["insufficient_sample_flags"])


if __name__ == "__main__":
    unittest.main()
