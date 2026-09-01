import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cycle_freeze_drift_audit as audit  # noqa: E402


class FreezeDriftAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = json.loads((ROOT / "data/cycle_engine_domain_diagnostics_v1.json").read_text(encoding="utf-8"))
        cls.baseline = audit._git_baseline()

    def test_baseline_has_no_core_historical_drift(self):
        result = audit.audit(self.baseline, self.current)
        self.assertTrue(result["core_historical_facts_unchanged"])
        self.assertGreater(result["statistical_semantic_change_count"], 0)

    def test_phase3_changes_are_classified_as_semantic(self):
        result = audit.audit(self.baseline, self.current)
        self.assertEqual(result["classification_counts"]["statistical_semantic_change"], 460)
        self.assertTrue(all(item["path"].startswith("phase3_design_evidence.") for item in result["statistical_semantic_changes"]))

    def test_audit_reports_nested_value_mutation(self):
        mutated = copy.deepcopy(self.current)
        mutated["timeline"][0]["month"] = "2099-01"
        result = audit.audit(self.baseline, mutated)
        self.assertFalse(result["core_historical_facts_unchanged"])
        self.assertEqual(result["core_historical_fact_checks"]["timeline"], False)

    def test_audit_does_not_import_production_diagnostics(self):
        source = Path(audit.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import cycle_engine_domain_diagnostics", source)
        self.assertNotIn("from cycle_engine_domain_diagnostics", source)


if __name__ == "__main__":
    unittest.main()
