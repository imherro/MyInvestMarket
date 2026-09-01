from __future__ import annotations

import copy
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cycle_engine_evaluation_targets as evaluation  # noqa: E402


class CycleEngineEvaluationTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = json.loads((ROOT / "data/cycle_dataset_v1.json").read_text(encoding="utf-8-sig"))
        cls.targets = json.loads((ROOT / "data/cycle_engine_evaluation_targets_v1.json").read_text(encoding="utf-8"))

    def test_targets_are_explicitly_evaluation_only(self) -> None:
        self.assertTrue(self.targets["evaluation_only"])
        self.assertTrue(self.targets["uses_future_information"])
        self.assertEqual(len(self.targets["records"]), 200)

    def test_broad_proxy_uses_returns_not_average_levels(self) -> None:
        rows, errors = evaluation.build_broad_proxy(self.dataset["records"])
        self.assertFalse(errors)
        self.assertIsNone(rows[0]["broad_monthly_return"])
        self.assertEqual(rows[0]["broad_proxy_index"], 100.0)
        second = rows[1]
        expected = 0.5 * second["monthly_returns"]["csi300"] + 0.5 * second["monthly_returns"]["csi500"]
        self.assertAlmostEqual(second["broad_monthly_return"], expected)

    def test_forward_target_uses_natural_month(self) -> None:
        record = self.targets["records"][0]
        metric = record["benchmarks"]["broad_proxy"]["forward_12m"]
        self.assertEqual(metric["target_month"], "2011-01")
        self.assertEqual(metric["target_available"], True)

    def test_shift_month_is_calendar_based(self) -> None:
        self.assertEqual(evaluation.shift_month("2015-01", 12), "2016-01")
        self.assertEqual(evaluation.shift_month("2015-01", 1), "2015-02")

    def test_three_month_risk_field_is_explicitly_unavailable(self) -> None:
        metric = self.targets["records"][0]["benchmarks"]["csi300"]["forward_3m"]
        self.assertFalse(metric["risk_metric_available"])
        self.assertIsNone(metric["max_drawdown_pct"])

    def test_required_historical_spots_are_present(self) -> None:
        self.assertEqual(
            [record["month"] for record in self.targets["historical_spots"]],
            list(evaluation.SPOT_MONTHS),
        )

    def test_tail_is_null_and_unavailable(self) -> None:
        record = self.targets["records"][-1]
        for benchmark in evaluation.BENCHMARKS:
            for horizon in evaluation.HORIZONS:
                metric = record["benchmarks"][benchmark][f"forward_{horizon}m"]
                self.assertFalse(metric["target_available"])
                self.assertIsNone(metric["forward_return_pct"])
                self.assertIsNone(metric["max_drawdown_pct"])

    def test_max_drawdown_is_peak_to_trough(self) -> None:
        self.assertEqual(evaluation.max_drawdown([100, 120, 110, 90, 105]), -25.0)

    def test_audit_passes(self) -> None:
        audit = json.loads((ROOT / "data/cycle_engine_evaluation_targets_audit_v1.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["passed"], audit)
        for key, value in audit.items():
            if key.endswith("_count") and key != "record_count":
                self.assertEqual(value, 0, key)

    def test_audit_detects_return_tampering(self) -> None:
        tampered = copy.deepcopy(self.targets)
        tampered["records"][0]["benchmarks"]["csi300"]["forward_12m"]["forward_return_pct"] = 999.0
        audit = evaluation.audit_targets(tampered, self.dataset)
        self.assertFalse(audit["passed"])
        self.assertGreater(audit["return_formula_violation_count"], 0)

    def test_audit_detects_target_month_tampering(self) -> None:
        tampered = copy.deepcopy(self.targets)
        tampered["records"][0]["benchmarks"]["csi300"]["forward_3m"]["target_month"] = "2015-03"
        audit = evaluation.audit_targets(tampered, self.dataset)
        self.assertFalse(audit["passed"])
        self.assertGreater(audit["horizon_alignment_violation_count"], 0)

    def test_frozen_source_gate_rejects_dataset_mutation(self) -> None:
        mutated = copy.deepcopy(self.dataset)
        mutated["records"][0]["trend"]["indices"]["csi300"]["close"]["value"] += 0.01
        with patch.object(evaluation, "load_dataset", return_value=mutated):
            with self.assertRaises(evaluation.FrozenEvaluationSourceInvalid):
                evaluation.generate()

    def test_missing_month_is_reported_and_not_skipped(self) -> None:
        missing = copy.deepcopy(self.dataset)
        missing["records"] = [r for r in missing["records"] if r["month"] != "2015-02"]
        tampered = evaluation.build_targets(missing)
        tampered["source_frozen_records_sha256"] = evaluation.EXPECTED_FROZEN_RECORDS_SHA256
        audit = evaluation.audit_targets(tampered, missing)
        self.assertFalse(audit["passed"])
        self.assertGreater(audit["source_month_gap_count"], 0)

    def test_audit_detects_drawdown_tampering(self) -> None:
        tampered = copy.deepcopy(self.targets)
        tampered["records"][0]["benchmarks"]["csi500"]["forward_12m"]["max_drawdown_pct"] = 0.0
        audit = evaluation.audit_targets(tampered, self.dataset)
        self.assertFalse(audit["passed"])
        self.assertGreater(audit["max_drawdown_formula_violation_count"], 0)

    def test_audit_rejects_evaluation_flags_removed(self) -> None:
        tampered = copy.deepcopy(self.targets)
        tampered["records"][0]["evaluation_only"] = False
        audit = evaluation.audit_targets(tampered, self.dataset)
        self.assertFalse(audit["passed"])
        self.assertGreater(audit["evidence_contamination_count"], 0)


if __name__ == "__main__":
    unittest.main()
