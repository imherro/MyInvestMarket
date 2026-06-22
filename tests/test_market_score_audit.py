from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import market_scoring  # noqa: E402
import migrate_market_score_history  # noqa: E402
from tests.test_history_migration import current_record, legacy_record  # noqa: E402
from tests.test_score_record_schema import valid_score_record  # noqa: E402


def audit_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class MarketScoreAuditTest(unittest.TestCase):
    def test_temp_history_path_uses_adjacent_audit_log_even_if_default_is_patched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            with patch.object(market_scoring, "DEFAULT_HISTORY_PATH", history_path):
                audit_path = market_scoring.history_audit_log_path(history_path)

        self.assertEqual(audit_path.name, "history_audit.jsonl")
        self.assertEqual(audit_path.parent, history_path.parent)

    def test_append_writes_structured_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            result = market_scoring.append_score_record(valid_score_record(), history_path)
            events = audit_events(Path(result["audit_path"]))

        self.assertTrue(result["appended"])
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "history_append")
        self.assertEqual(event["run_id"], "schema-test-run")
        self.assertEqual(event["dedupe_key"]["basis_trade_date"], "2026-06-18")
        self.assertTrue(event["appended"])
        self.assertFalse(event["duplicate"])
        self.assertEqual(event["schema_version"], market_scoring.SCORE_SCHEMA_VERSION)

    def test_duplicate_writes_structured_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            market_scoring.append_score_record(valid_score_record(), history_path)
            duplicate = copy.deepcopy(valid_score_record())
            duplicate["run_id"] = "schema-test-duplicate"
            result = market_scoring.append_score_record(duplicate, history_path)
            events = audit_events(Path(result["audit_path"]))

        self.assertFalse(result["appended"])
        self.assertTrue(result["duplicate"])
        event = events[-1]
        self.assertEqual(event["event_type"], "history_duplicate")
        self.assertEqual(event["run_id"], "schema-test-run")
        self.assertFalse(event["appended"])
        self.assertTrue(event["duplicate"])
        self.assertEqual(event["details"]["candidate_run_id"], "schema-test-duplicate")

    def test_failed_append_writes_reason_to_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            invalid = valid_score_record()
            invalid.pop("run_id")
            audit_path = market_scoring.history_audit_log_path(history_path)

            with self.assertRaises(market_scoring.ScoreRecordValidationError):
                market_scoring.append_score_record(invalid, history_path)
            events = audit_events(audit_path)

        self.assertFalse(history_path.exists())
        self.assertEqual(events[-1]["event_type"], "history_append_failed")
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("run_id", events[-1]["reason"])
        self.assertFalse(events[-1]["appended"])
        self.assertFalse(events[-1]["duplicate"])

    def test_migration_script_writes_structured_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"
            history_path.write_text(
                json.dumps({"schema_version": 1, "records": [legacy_record("legacy-1"), current_record()]}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = migrate_market_score_history.run_migration(history_path)
            events = audit_events(Path(result["audit_path"]))

        self.assertTrue(result["written"])
        event = events[-1]
        self.assertEqual(event["event_type"], "history_migration")
        self.assertFalse(event["appended"])
        self.assertFalse(event["duplicate"])
        self.assertEqual(event["schema_version"], market_scoring.SCORE_SCHEMA_VERSION)
        self.assertEqual(event["details"]["legacy_marked_count"], 1)
        self.assertEqual(event["details"]["legacy_archived_count"], 0)


if __name__ == "__main__":
    unittest.main()
