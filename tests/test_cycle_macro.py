from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cycle_macro  # noqa: E402


def tushare_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"month": month, "pmi010000": value} for month, value in rows])


def schedule_frame(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"month": month, "publish_date": published, "title": "制造业PMI", "issuing_org": "国家统计局", "data_api": "cn_pmi"} for month, published in rows])


def ak_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([["中国官方制造业PMI", pd.Timestamp(published).date(), value, None, None] for published, value in rows], columns=["商品", "日期", "今值", "预期值", "前值"])


class CycleMacroTests(unittest.TestCase):
    def test_snapshot_uses_publish_date_not_data_month(self) -> None:
        rows, conflicts, _ = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}],
            [],
            [],
            [{"publish_date": "2024-02-01", "crosscheck_value": 50.2}],
        )
        before = cycle_macro.snapshot(rows, conflicts, date(2024, 1, 31))
        self.assertFalse(before["available"])
        after = cycle_macro.snapshot(rows, conflicts, date(2024, 2, 1))
        self.assertTrue(after["available"])
        self.assertEqual(after["data_month"], "2024-01")
        self.assertEqual(after["observation_date"], "2024-02-01")

    def test_snapshot_uses_latest_published_pmi(self) -> None:
        rows, conflicts, _ = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}, {"data_month": "2024-02", "pmi": 49.1, "value_source": cycle_macro.VALUE_SOURCE}],
            [],
            [],
            [{"publish_date": "2024-02-01", "crosscheck_value": 50.2}, {"publish_date": "2024-03-01", "crosscheck_value": 49.1}],
        )
        result = cycle_macro.snapshot(rows, conflicts, date(2024, 3, 2))
        self.assertEqual(result["data_month"], "2024-02")
        self.assertEqual(result["change_1m"], -1.1)

    def test_schedule_publish_date_has_priority(self) -> None:
        schedule = cycle_macro.normalise_schedule(schedule_frame([("2024-01", "2024-01-31")]))
        rows, conflicts, counters = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}], [], schedule, []
        )
        self.assertEqual(rows[0]["publish_date"], "2024-01-31")
        self.assertEqual(rows[0]["publish_date_source"], cycle_macro.SCHEDULE_SOURCE)
        self.assertEqual(counters["schedule_direct"], 1)
        self.assertFalse(conflicts)

    def test_akshare_fallback_requires_value_and_window_match(self) -> None:
        rows, conflicts, counters = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}],
            [], [], [{"publish_date": "2024-02-01", "crosscheck_value": 50.2}]
        )
        self.assertEqual(rows[0]["publish_date_source"], cycle_macro.FALLBACK_SOURCE)
        self.assertEqual(counters["akshare_fallback"], 1)
        self.assertEqual(rows[0]["crosscheck_diff"], 0.0)
        self.assertFalse(conflicts)

    def test_fallback_value_mismatch_is_not_accepted(self) -> None:
        rows, conflicts, counters = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}],
            [], [], [{"publish_date": "2024-02-01", "crosscheck_value": 49.0}]
        )
        self.assertIsNone(rows[0].get("publish_date"))
        self.assertEqual(counters["crosscheck_mismatch"], 1)
        self.assertFalse(conflicts)

    def test_multiple_release_events_are_conflict_and_unavailable(self) -> None:
        schedule = cycle_macro.normalise_schedule(schedule_frame([("2024-01", "2024-01-31"), ("2024-01", "2024-02-01")]))
        rows, conflicts, _ = cycle_macro.canonical_records(
            [{"data_month": "2024-01", "pmi": 50.2, "value_source": cycle_macro.VALUE_SOURCE}], [], schedule, []
        )
        self.assertEqual(len(conflicts), 1)
        self.assertFalse(cycle_macro.snapshot(rows, conflicts, date(2024, 2, 2))["available"])

    def test_non_pmi_schedule_events_are_ignored(self) -> None:
        frame = pd.DataFrame([{"month": "2024-01", "publish_date": "2024-01-31", "title": "CPI", "issuing_org": "国家统计局", "data_api": "cn_cpi"}])
        self.assertEqual(cycle_macro.normalise_schedule(frame), [])

    def test_duplicate_month_with_different_values_is_a_source_conflict(self) -> None:
        rows, conflicts = cycle_macro.normalise_tushare(tushare_frame([("2024-01", 50.2), ("2024-01", 50.3)]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["identity"]["data_month"], "2024-01")

    def test_same_value_with_different_release_date_is_a_release_conflict(self) -> None:
        existing = [{"data_month": "2024-01", "pmi": 50.2, "publish_date": "2024-01-31"}]
        fresh = [{"data_month": "2024-01", "pmi": 50.2, "publish_date": "2024-02-01"}]
        merged, conflicts = cycle_macro.merge_records(existing, fresh)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("publish_dates", conflicts[0])

    def test_changes_only_use_published_history_at_basis(self) -> None:
        rows = [
            {"data_month": "2023-12", "pmi": 49.0, "publish_date": "2023-12-31"},
            {"data_month": "2024-01", "pmi": 50.0, "publish_date": "2024-01-31"},
            {"data_month": "2024-02", "pmi": 51.0, "publish_date": "2024-02-29"},
            {"data_month": "2024-03", "pmi": 52.0, "publish_date": "2024-03-31"},
        ]
        result = cycle_macro.snapshot(rows, [], date(2024, 2, 29))
        self.assertEqual(result["data_month"], "2024-02")
        self.assertEqual(result["change_1m"], 1.0)
        self.assertEqual(result["change_3m"], None)

    def test_cache_duplicate_refresh_and_failure_keeps_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pmi.json"
            pro = type("Pro", (), {"cn_pmi": lambda self, **kwargs: tushare_frame([("2024-01", 50.2)]), "cn_schedule": lambda self, **kwargs: schedule_frame([])})()
            fetch = lambda: ak_frame([("2024-02-01", 50.2)])
            first = cycle_macro.source_from_cache_or_api_status(pro, path, date(2024, 1, 1), date(2024, 2, 29), refresh=True, refresh_date=date(2024, 3, 1), ak_fetcher=fetch)
            self.assertIsNone(first[3])
            second = cycle_macro.source_from_cache_or_api_status(pro, path, date(2024, 1, 1), date(2024, 2, 29), refresh=True, refresh_date=date(2024, 3, 2), ak_fetcher=fetch)
            self.assertEqual(len(second[0]), 1)
            before_failure = path.read_bytes()
            broken = type("Broken", (), {"cn_pmi": lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("source down")), "cn_schedule": lambda self, **kwargs: schedule_frame([])})()
            failed = cycle_macro.source_from_cache_or_api_status(broken, path, date(2024, 1, 1), date(2024, 2, 29), refresh=True, ak_fetcher=fetch)
            self.assertEqual(len(failed[0]), 1)
            self.assertIn("source down", failed[3])
            self.assertEqual(path.read_bytes(), before_failure)
            self.assertEqual(first[2]["last_successful_refresh_date"], "2024-03-01")

    def test_offline_does_not_call_source_or_change_refresh_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pmi.json"
            rows = [{"data_month": "2024-01", "pmi": 50.2, "publish_date": "2024-02-01"}]
            path.write_text(json.dumps(cycle_macro.cache_payload(rows, [], date(2024, 3, 1)), ensure_ascii=False), encoding="utf-8")
            result = cycle_macro.source_from_cache_or_api_status(None, path, date(2024, 1, 1), date(2024, 3, 1), refresh=False, refresh_date=date(2024, 4, 1))
            self.assertIsNone(result[3])
            self.assertEqual(result[2]["last_successful_refresh_date"], "2024-03-01")


if __name__ == "__main__":
    unittest.main()
