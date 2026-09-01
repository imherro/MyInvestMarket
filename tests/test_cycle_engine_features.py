from __future__ import annotations

import copy
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cycle_engine_features as engine  # noqa: E402
import validate_cycle_dataset_contract as freeze  # noqa: E402


class CycleEngineFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads((ROOT / "data/cycle_dataset_v1.json").read_text(encoding="utf-8-sig"))
        cls.contract = json.loads((ROOT / "data/cycle_dataset_contract_v1.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((ROOT / "data/cycle_dataset_freeze_manifest_v1.json").read_text(encoding="utf-8"))

    def test_generated_evidence_is_present_and_audited(self) -> None:
        evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        audit = json.loads((ROOT / "data/cycle_engine_features_audit_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(evidence["records"]), 200)
        self.assertTrue(audit["passed"], audit)
        self.assertEqual(evidence["source_frozen_records_sha256"], self.manifest["frozen_records_sha256"])

    def test_engine_stops_when_frozen_gate_fails(self) -> None:
        failed = {"valid": False, "errors": ["frozen history hash mismatch"]}
        with patch.object(freeze, "validate", return_value=failed):
            with self.assertRaises(engine.FrozenDatasetInvalid):
                engine.load_source()

    def test_registry_paths_are_exactly_the_frozen_paths(self) -> None:
        self.assertEqual(
            {item["path"] for item in self.contract["model_input_registry"]},
            {item["path"] for item in freeze.build_registry()},
        )

    def test_native_percentile_and_fear_are_identity_transforms(self) -> None:
        evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        row = evidence["records"][-1]["features"]
        for path in ("valuation.indices.csi300.pe_ttm.percentile_expanding", "valuation.indices.csi500.pb.percentile_expanding", "sentiment.a_fear.fear_score"):
            feature = row[path]
            self.assertEqual(feature["expanding_rank_pct"], feature["raw_value"])
        self.assertEqual(row["valuation.indices.csi300.pe_ttm.percentile_expanding"]["normalization_source"], "dataset_native_percentile")
        self.assertEqual(row["sentiment.a_fear.fear_score"]["normalization_source"], "native_a_fear_score")

    def test_boolean_features_are_not_ranked(self) -> None:
        evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        feature = evidence["records"][-1]["features"]["trend.indices.csi1000.above_ma250.value"]
        self.assertIsNone(feature["expanding_rank_pct"])
        self.assertEqual(feature["normalization_source"], "boolean_identity")

    def test_rank_formula_includes_current_value_and_handles_ties(self) -> None:
        self.assertEqual(engine.rank_pct([10.0], 10.0), 50.0)
        self.assertEqual(engine.rank_pct([1.0, 2.0, 2.0], 2.0), 66.666667)
        self.assertEqual(engine.rank_pct([1.0, 2.0, 3.0], 3.0), 83.333333)

    def test_missing_values_do_not_enter_normalization_history(self) -> None:
        evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        feature = evidence["records"][0]["features"]["earnings.all_a_net_profit_yoy_pct.value"]
        self.assertFalse(feature["available"])
        self.assertIsNone(feature["expanding_rank_pct"])
        self.assertEqual(feature["normalization_history_observations"], 0)
        self.assertTrue(feature["expected_missing"])

    def test_future_extreme_value_does_not_change_prior_rank(self) -> None:
        records = freeze.records_for_hash(self.payload)
        baseline = engine.build_features(records, self.contract, self.manifest)
        extended = copy.deepcopy(records)
        future = copy.deepcopy(extended[-1])
        future["month"] = "2026-09"
        future["basis_trade_date"] = "2026-09-30"
        future["valuation"]["csi300_erp_pct"]["value"] = 999999.0
        extended.append(future)
        changed = engine.build_features(extended, self.contract, self.manifest)
        path = "valuation.csi300_erp_pct.value"
        self.assertEqual(baseline[24]["features"][path]["expanding_rank_pct"], changed[24]["features"][path]["expanding_rank_pct"])

    def test_historical_mutation_only_affects_current_and_later_ranks(self) -> None:
        records = freeze.records_for_hash(self.payload)
        baseline = engine.build_features(records, self.contract, self.manifest)
        changed_records = copy.deepcopy(records)
        changed_record = next(record for record in changed_records if record["month"] == "2015-06")
        changed_record["valuation"]["csi300_erp_pct"]["value"] = 999.0
        changed = engine.build_features(changed_records, self.contract, self.manifest)
        path = "valuation.csi300_erp_pct.value"
        before = [index for index, record in enumerate(records) if record["month"] < "2015-06"]
        self.assertTrue(before)
        self.assertEqual(
            [baseline[index]["features"][path]["expanding_rank_pct"] for index in before],
            [changed[index]["features"][path]["expanding_rank_pct"] for index in before],
        )
        current_index = next(index for index, record in enumerate(records) if record["month"] == "2015-06")
        self.assertNotEqual(baseline[current_index]["features"][path]["expanding_rank_pct"], changed[current_index]["features"][path]["expanding_rank_pct"])

    def test_unauthorized_feature_injection_is_audited(self) -> None:
        rows = engine.build_features(freeze.records_for_hash(self.payload), self.contract, self.manifest)
        rows[0]["features"]["legacy.market_score"] = {"path": "legacy.market_score", "available": True, "pit_safe": True, "raw_value": 50, "feature_family": "legacy", "model_candidate": False, "unit": "score"}
        audit = engine.build_audit(rows, freeze.records_for_hash(self.payload), self.contract, self.manifest)
        self.assertGreater(audit["unauthorized_input_count"], 0)
        self.assertFalse(audit["passed"])

    def test_feature_paths_do_not_contain_legacy_inputs(self) -> None:
        evidence = json.loads((ROOT / "data/cycle_engine_features_v1.json").read_text(encoding="utf-8"))
        forbidden = ("market_score", "regime", "risk", "crowding", "flow", "theme", "momentum_5d", "four_sleeve")
        paths = [path for row in evidence["records"] for path in row["features"]]
        self.assertFalse(any(any(token in path for token in forbidden) for path in paths))


if __name__ == "__main__":
    unittest.main()
