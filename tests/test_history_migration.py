from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import migrate_market_score_history  # noqa: E402
import serve_market_web  # noqa: E402


def current_record(run_id: str = "current-run") -> dict:
    modules = {
        key: {
            "label": meta["label"],
            "weight": meta["weight"],
            "score": meta["weight"] * 0.5,
            "score_pct": 50,
            "summary": "test",
            "evidence": [],
            "metrics": {},
        }
        for key, meta in market_scoring.MODULES.items()
    }
    return {
        "run_id": run_id,
        "model_version": market_scoring.MODEL_VERSION,
        "position_policy_version": market_scoring.POSITION_POLICY_VERSION,
        "account_scope": "stock_account",
        "scored_at": "2026-06-22T16:00:00+08:00",
        "basis_trade_date": "2026-06-18",
        "snapshot_sha256": run_id,
        "market_regime": "中性震荡偏结构",
        "market_opportunity_score": 50,
        "opportunity_score": 50,
        "crowding_penalty": 15,
        "pre_cap_market_position_score": 35,
        "market_position_score": 35,
        "base_market_position_score": 35,
        "recommended_equity_position_range": "20%-40%",
        "base_equity_position_range": "20%-40%",
        "equity_position_range": "20%-40%",
        "confidence": "medium",
        "risk_caps": [],
        "modules": modules,
        "crowding": {"penalty": 15, "items": []},
        "data_quality": {"missing_fields": [], "warnings": []},
    }


def legacy_record(run_id: str, snapshot_sha256: str = "legacy-sha") -> dict:
    return {
        "run_id": run_id,
        "model_version": "a_share_market_score_v1",
        "scored_at": "2026-06-18T10:00:00+08:00",
        "basis_trade_date": "2026-06-17",
        "snapshot_sha256": snapshot_sha256,
        "market_position_score": 35,
        "recommended_equity_position_range": "20%-40%",
    }


class HistoryMigrationTest(unittest.TestCase):
    def test_migration_marks_legacy_records_and_archives_duplicate_legacy_records(self) -> None:
        history = {
            "schema_version": 1,
            "updated_at": "2026-06-22T10:00:00+08:00",
            "records": [
                legacy_record("legacy-1"),
                legacy_record("legacy-2"),
                legacy_record("legacy-3", snapshot_sha256="legacy-sha-2"),
                current_record(),
            ],
        }

        result = market_scoring.migrate_history_legacy_records(history, migrated_at="2026-06-22T18:00:00+08:00")
        migrated = result["history"]

        self.assertTrue(result["changed"])
        self.assertEqual(result["legacy_marked_count"], 2)
        self.assertEqual(result["legacy_archived_count"], 1)
        self.assertEqual([record["run_id"] for record in migrated["records"]], ["legacy-1", "legacy-3", "current-run"])
        self.assertTrue(migrated["records"][0]["legacy_schema"])
        self.assertEqual(migrated["records"][0]["legacy_reason"], "legacy_model_version")
        self.assertEqual(migrated["legacy_archive"][0]["run_id"], "legacy-2")
        self.assertEqual(migrated["legacy_archive"][0]["archived_reason"], "duplicate_legacy_record")

    def test_migration_is_idempotent(self) -> None:
        history = {
            "schema_version": 1,
            "records": [legacy_record("legacy-1"), legacy_record("legacy-2"), current_record()],
        }

        first = market_scoring.migrate_history_legacy_records(history, migrated_at="2026-06-22T18:00:00+08:00")
        second = market_scoring.migrate_history_legacy_records(first["history"], migrated_at="2026-06-22T19:00:00+08:00")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(first["history"], second["history"])

    def test_legacy_schema_records_do_not_participate_in_default_history(self) -> None:
        migrated = market_scoring.migrate_history_legacy_records(
            {"records": [legacy_record("legacy-1"), current_record()]},
            migrated_at="2026-06-22T18:00:00+08:00",
        )["history"]

        current = serve_market_web.filtered_history(migrated)
        with_legacy = serve_market_web.filtered_history(migrated, include_legacy=True)

        self.assertEqual([record["run_id"] for record in current["records"]], ["current-run"])
        self.assertEqual(current["legacy_record_count"], 1)
        self.assertEqual([record["run_id"] for record in with_legacy["records"]], ["legacy-1", "current-run"])

    def test_migration_script_dry_run_does_not_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            original = {"schema_version": 1, "records": [legacy_record("legacy-1"), current_record()]}
            history_path.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")

            result = migrate_market_score_history.run_migration(history_path, dry_run=True)
            saved = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertFalse(result["written"])
        self.assertEqual(saved, original)


if __name__ == "__main__":
    unittest.main()
