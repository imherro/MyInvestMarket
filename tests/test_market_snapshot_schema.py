from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_market_dataset  # noqa: E402
import market_scoring  # noqa: E402
from tests.test_market_scenarios import base_snapshot, rolling_features  # noqa: E402


class MarketSnapshotSchemaTest(unittest.TestCase):
    def test_validate_market_snapshot_accepts_valid_snapshot(self) -> None:
        validation = market_scoring.validate_market_snapshot(base_snapshot())

        self.assertTrue(validation["ok"])
        self.assertEqual(validation["basis_trade_date"], "2026-06-18")
        self.assertIn("market.indices", validation["checked_fields"])

    def test_score_snapshot_rejects_missing_required_field_with_reason(self) -> None:
        snapshot = base_snapshot()
        snapshot.pop("breadth")

        with self.assertRaisesRegex(market_scoring.MarketSnapshotValidationError, "breadth"):
            market_scoring.score_snapshot(snapshot, snapshot_bytes=b"missing-breadth")

    def test_score_snapshot_rejects_mismatched_market_date_with_reason(self) -> None:
        snapshot = base_snapshot()
        snapshot["market"]["as_of_trade_date"] = "2026-06-17"

        with self.assertRaisesRegex(market_scoring.MarketSnapshotValidationError, "market.as_of_trade_date"):
            market_scoring.score_snapshot(snapshot, snapshot_bytes=b"bad-date")

    def test_score_snapshot_rejects_invalid_core_lists_with_reason(self) -> None:
        snapshot = base_snapshot()
        snapshot["sector_rotation"]["top5_industries_by_return"] = []

        with self.assertRaisesRegex(market_scoring.MarketSnapshotValidationError, "top5_industries_by_return"):
            market_scoring.score_snapshot(snapshot, snapshot_bytes=b"bad-sector-list")

    def test_valid_snapshot_scores_after_schema_validation(self) -> None:
        with patch.object(market_scoring, "rolling_market_features", return_value=rolling_features()):
            record = market_scoring.score_snapshot(base_snapshot(), snapshot_bytes=b"valid-snapshot")

        self.assertTrue(record["snapshot_validation"]["ok"])
        self.assertGreater(record["market_opportunity_score"], 0)

    def test_build_dataset_validation_uses_same_snapshot_schema(self) -> None:
        valid = build_market_dataset.validate_built_dataset(base_snapshot())
        invalid = copy.deepcopy(base_snapshot())
        invalid["capital_flow"]["turnover_distribution"]["small_cap"].pop("share")

        self.assertTrue(valid["ok"])
        with self.assertRaisesRegex(market_scoring.MarketSnapshotValidationError, "small_cap.share"):
            build_market_dataset.validate_built_dataset(invalid)


if __name__ == "__main__":
    unittest.main()
