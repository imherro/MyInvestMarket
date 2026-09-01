from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_cycle_dataset as cycle  # noqa: E402
import validate_cycle_dataset_contract as freeze  # noqa: E402


class CycleDatasetFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads((ROOT / "data/cycle_dataset_v1.json").read_text(encoding="utf-8-sig"))
        cls.contract = json.loads((ROOT / "data/cycle_dataset_contract_v1.json").read_text(encoding="utf-8"))
        cls.matrix = json.loads((ROOT / "data/cycle_dataset_feature_availability_v1.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((ROOT / "data/cycle_dataset_freeze_manifest_v1.json").read_text(encoding="utf-8"))
        cls.golden = json.loads((ROOT / "data/cycle_dataset_golden_spots_v1.json").read_text(encoding="utf-8"))

    def test_generated_artifacts_validate(self) -> None:
        result = freeze.validate(self.payload, self.contract, self.matrix, self.manifest, self.golden)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["unexpected_required_input_missing_count"], 0)

    def test_record_key_order_does_not_change_frozen_hash(self) -> None:
        original = freeze.sha256(freeze.records_for_hash(self.payload, freeze.FROZEN_THROUGH))
        reordered = copy.deepcopy(self.payload)
        reordered["records"] = [dict(reversed(list(record.items()))) for record in reversed(reordered["records"])]
        actual = freeze.sha256(freeze.records_for_hash(reordered, freeze.FROZEN_THROUGH))
        self.assertEqual(actual, original)

    def test_metadata_changes_do_not_change_record_hash(self) -> None:
        original = freeze.sha256(freeze.records_for_hash(self.payload, freeze.FROZEN_THROUGH))
        changed = copy.deepcopy(self.payload)
        changed["generated_at"] = "2099-01-01T00:00:00+08:00"
        changed["refresh_metadata"] = {"source": "test"}
        self.assertEqual(freeze.sha256(freeze.records_for_hash(changed, freeze.FROZEN_THROUGH)), original)

    def test_append_after_freeze_does_not_change_frozen_hash(self) -> None:
        original = freeze.sha256(freeze.records_for_hash(self.payload, freeze.FROZEN_THROUGH))
        appended = copy.deepcopy(self.payload)
        appended["records"].append({"month": "2026-09", "basis_trade_date": "2026-09-30"})
        self.assertEqual(freeze.sha256(freeze.records_for_hash(appended, freeze.FROZEN_THROUGH)), original)

    def test_frozen_record_change_changes_hash(self) -> None:
        original = freeze.sha256(freeze.records_for_hash(self.payload, freeze.FROZEN_THROUGH))
        changed = copy.deepcopy(self.payload)
        changed["records"][-1]["month"] = "2026-08"
        changed["records"][-1]["basis_trade_date"] = "2026-08-31"
        changed["records"][-1]["dataset_version"] = "tampered"
        self.assertNotEqual(freeze.sha256(freeze.records_for_hash(changed, freeze.FROZEN_THROUGH)), original)

    def test_required_path_deletion_and_type_drift_fail(self) -> None:
        deleted = copy.deepcopy(self.payload)
        del deleted["records"][-1]["earnings"]["pmi"]["value"]
        result = freeze.validate(deleted, self.contract, self.matrix)
        self.assertFalse(result["valid"])
        self.assertTrue(any("required path missing" in error for error in result["errors"]))

        wrong_type = copy.deepcopy(self.payload)
        wrong_type["records"][-1]["earnings"]["pmi"]["above_50"] = "true"
        result = freeze.validate(wrong_type, self.contract, self.matrix)
        self.assertFalse(result["valid"])
        self.assertTrue(any("field type mismatch" in error for error in result["errors"]))

    def test_full_core_field_disappearance_is_unexpected(self) -> None:
        paths = [
            "valuation.indices.csi300.pe_ttm.value",
            "valuation.indices.csi500.pe_ttm.value",
            "valuation.china_10y_government_bond_yield_pct.value",
            "valuation.csi300_erp_pct.value",
            "earnings.all_a_net_profit_yoy_pct.value",
            "earnings.nonfinancial_a_net_profit_yoy_pct.value",
            "earnings.all_a_roe_ttm_pct.value",
            "earnings.nonfinancial_a_roe_ttm_pct.value",
            "earnings.pmi.value",
            "trend.indices.csi300.ma250_deviation_pct.value",
        ]
        for path in paths:
            payload = copy.deepcopy(self.payload)
            for record in payload["records"]:
                target = record
                parts = path.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = None
            result = freeze.validate(payload, self.contract, self.matrix)
            self.assertFalse(result["valid"], path)
            self.assertGreater(result["unexpected_required_input_missing_count"], 0, path)

    def test_leading_truncation_is_unexpected(self) -> None:
        payload = copy.deepcopy(self.payload)
        for record in payload["records"]:
            if record["month"] < "2015-01":
                record["valuation"]["indices"]["csi300"]["pe_ttm"]["value"] = None
        result = freeze.validate(payload, self.contract, self.matrix)
        self.assertFalse(result["valid"])
        self.assertGreater(result["unexpected_required_input_missing_count"], 0)

    def test_future_append_passes_full_validation_and_preserves_frozen_hash(self) -> None:
        payload = copy.deepcopy(self.payload)
        future = copy.deepcopy(payload["records"][-1])
        future["month"] = "2026-09"
        future["basis_trade_date"] = "2026-09-30"
        payload["records"].append(future)
        matrix = freeze.build_matrix(payload["records"], self.contract["model_input_registry"], self.contract["expected_missing_policy"])
        manifest = copy.deepcopy(self.manifest)
        manifest["record_count"] = len(payload["records"])
        manifest["end_month"] = "2026-09"
        manifest["current_records_sha256"] = freeze.sha256(freeze.records_for_hash(payload))
        manifest["feature_availability_sha256"] = freeze.sha256(matrix)
        result = freeze.validate(payload, self.contract, matrix, manifest, self.golden)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(manifest["frozen_records_sha256"], self.manifest["frozen_records_sha256"])

    def test_excluded_registry_entry_fails(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["model_input_registry"][0]["path"] = "current_v3.4_market_score"
        result = freeze.validate(self.payload, contract, self.matrix)
        self.assertFalse(result["valid"])
        self.assertIn("excluded field is in model registry", result["errors"])

    def test_expected_prelaunch_and_a_fear_gaps_are_not_unexpected(self) -> None:
        csi1000 = self.matrix["fields"]["trend.indices.csi1000.ma250_deviation_pct.value"]
        self.assertGreater(csi1000["expected_missing_count"], 0)
        self.assertEqual(csi1000["unexpected_missing_count"], 0)
        fear = self.matrix["fields"]["sentiment.a_fear.fear_score"]
        self.assertGreater(fear["expected_missing_count"], 0)
        self.assertEqual(fear["unexpected_missing_count"], 0)

    def test_golden_drift_fails(self) -> None:
        golden = copy.deepcopy(self.golden)
        golden["months"]["2026-08"]["valuation.csi300_erp_pct.value"] += 1
        result = freeze.validate(self.payload, self.contract, self.matrix, golden=golden)
        self.assertFalse(result["valid"])
        self.assertTrue(any("golden drift" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
