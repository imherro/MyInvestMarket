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

import build_cycle_dataset as cycle  # noqa: E402
import cycle_rates  # noqa: E402


def raw_rates(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{cycle_rates.DATE_COLUMN: observation, cycle_rates.CURVE_COLUMN: curve, cycle_rates.TEN_YEAR_COLUMN: value} for observation, curve, value in rows])


class CycleRatesTests(unittest.TestCase):
    def test_snapshot_is_point_in_time_and_staleness_bounded(self) -> None:
        rates = cycle_rates.normalise_rates(raw_rates([
            ("2024-01-10", cycle_rates.CURVE_NAME, 2.5),
            ("2024-01-20", cycle_rates.CURVE_NAME, 2.4),
        ]))
        before_future = cycle_rates.snapshot(rates, date(2024, 1, 15))
        self.assertTrue(before_future["available"])
        self.assertEqual(before_future["value"], 2.5)
        self.assertEqual(before_future["observation_date"], "2024-01-10")
        self.assertEqual(before_future["lag_days"], 5)
        stale = cycle_rates.snapshot(rates, date(2024, 2, 1))
        self.assertFalse(stale["available"])
        self.assertEqual(stale["reason"], "China 10Y observation too stale")
        self.assertEqual(stale["observation_date"], "2024-01-20")

    def test_only_exact_chinabond_government_curve_is_retained(self) -> None:
        rates = cycle_rates.normalise_rates(raw_rates([
            ("2024-01-10", cycle_rates.CURVE_NAME, 2.5),
            ("2024-01-10", "\u4e2d\u503a\u653f\u7b56\u6027\u94f6\u884c\u503a\u6536\u76ca\u7387\u66f2\u7ebf", 2.6),
            ("2024-01-10", "\u4e2d\u503a\u5546\u4e1a\u94f6\u884c\u666e\u901a\u503a\u6536\u76ca\u7387\u66f2\u7ebf(AAA)", 2.7),
        ]))
        self.assertEqual(len(rates), 1)
        self.assertEqual(float(rates.iloc[0]["yield_10y_pct"]), 2.5)

    def test_conflicting_same_date_is_excluded_from_snapshot(self) -> None:
        rates = cycle_rates.normalise_rates(raw_rates([
            ("2024-01-10", cycle_rates.CURVE_NAME, 2.5),
            ("2024-01-10", cycle_rates.CURVE_NAME, 2.7),
        ]))
        self.assertEqual(len(cycle_rates.source_conflicts(rates)), 1)
        snapshot = cycle_rates.snapshot(rates, date(2024, 1, 10))
        self.assertFalse(snapshot["available"])
        self.assertIn("no China 10Y observation", snapshot["reason"])

    def test_date_windows_are_contiguous_and_under_one_year(self) -> None:
        windows = cycle_rates.date_windows(date(2024, 1, 1), date(2025, 1, 1))
        self.assertEqual(windows[0][0], date(2024, 1, 1))
        self.assertEqual(windows[-1][1], date(2025, 1, 1))
        for left, right in windows:
            self.assertLess((right - left).days, 365)
        for (_, left_end), (right_start, _) in zip(windows, windows[1:]):
            self.assertEqual(right_start, left_end + pd.Timedelta(days=1).to_pytimedelta())

    def test_cache_duplicate_refresh_and_failure_fallback(self) -> None:
        rows = raw_rates([("2024-01-10", cycle_rates.CURVE_NAME, 2.5)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rates.json"
            fetcher = lambda _start, _end: rows
            rates, _, metadata, error = cycle_rates.source_from_cache_or_api_status(path, date(2024, 1, 1), date(2024, 1, 31), refresh_date=date(2024, 2, 1), fetcher=fetcher)
            self.assertIsNone(error)
            self.assertEqual(len(rates), 1)
            rates, _, metadata, error = cycle_rates.source_from_cache_or_api_status(path, date(2024, 1, 1), date(2024, 1, 31), refresh_date=date(2024, 2, 2), fetcher=fetcher)
            self.assertIsNone(error)
            self.assertEqual(len(rates), 1)
            before = path.read_bytes()
            broken = lambda _start, _end: (_ for _ in ()).throw(RuntimeError("ChinaBond unavailable"))
            returned, _, failed_meta, error = cycle_rates.source_from_cache_or_api_status(path, date(2024, 1, 1), date(2024, 2, 1), fetcher=broken)
            self.assertEqual(len(returned), 1)
            self.assertIn("ChinaBond unavailable", error)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(failed_meta["last_successful_refresh_date"], metadata["last_successful_refresh_date"])

    def test_no_cache_failure_is_unavailable_and_metadata_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rates.json"
            broken = lambda _start, _end: (_ for _ in ()).throw(RuntimeError("ChinaBond unavailable"))
            rates, _, _, error = cycle_rates.source_from_cache_or_api_status(path, date(2024, 1, 1), date(2024, 1, 31), fetcher=broken)
            self.assertIsNone(rates)
            self.assertIn("ChinaBond unavailable", error)
            initial = cycle_rates.normalise_rates(raw_rates([("2024-01-10", cycle_rates.CURVE_NAME, 2.5)]))
            path.write_text(json.dumps(cycle_rates.cache_payload(initial, [], date(2024, 2, 1), {"custom": "kept"}), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(cycle_rates.load_cache_metadata(path)["custom"], "kept")

    def test_offline_cache_read_does_not_update_refresh_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rates.json"
            initial = cycle_rates.normalise_rates(raw_rates([("2024-01-10", cycle_rates.CURVE_NAME, 2.5)]))
            path.write_text(json.dumps(cycle_rates.cache_payload(initial, [], date(2024, 2, 1)), ensure_ascii=False), encoding="utf-8")
            _, _, metadata, error = cycle_rates.source_from_cache_or_api_status(
                path,
                date(2024, 1, 1),
                date(2024, 3, 1),
                refresh=False,
                refresh_date=date(2024, 3, 1),
                fetcher=lambda _start, _end: self.fail("offline read must not fetch"),
            )
            self.assertIsNone(error)
            self.assertEqual(metadata["last_successful_refresh_date"], "2024-02-01")

    def test_erp_formula_lineage_and_missing_inputs(self) -> None:
        earnings_yield = cycle.feature(7.2, date(2024, 1, 31), "test", observation_date=date(2024, 1, 29))
        rates = cycle_rates.normalise_rates(raw_rates([("2024-01-30", cycle_rates.CURVE_NAME, 1.8)]))
        bond = cycle_rates.snapshot(rates, date(2024, 1, 31))
        erp = cycle.erp_snapshot(earnings_yield, bond, date(2024, 1, 31))
        self.assertEqual(erp["value"], 5.4)
        self.assertEqual(erp["observation_date"], "2024-01-30")
        self.assertEqual(erp["earnings_yield_observation_date"], "2024-01-29")
        self.assertEqual(erp["bond_yield_observation_date"], "2024-01-30")
        self.assertFalse(cycle.erp_snapshot(cycle.unavailable(date(2024, 1, 31), "test", "missing"), bond, date(2024, 1, 31))["available"])
        future_bond = cycle_rates.snapshot(cycle_rates.normalise_rates(raw_rates([("2024-02-01", cycle_rates.CURVE_NAME, 1.8)])), date(2024, 1, 31))
        self.assertFalse(future_bond["available"])
        self.assertFalse(cycle.erp_snapshot(earnings_yield, future_bond, date(2024, 1, 31))["available"])

    def test_erp_lineage_violation_fails_cycle_audit(self) -> None:
        base = {"available": True, "observation_date": "2024-01-30", "value": 7.2}
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [{"month": "2024-01", "basis_trade_date": "2024-01-31", "valuation": {"indices": {"csi300": {"pe_ttm": {"available": True, "observation_date": "2024-01-30", "history_end_date": "2024-01-30", "history_ready": True}, "pb": {"available": True, "observation_date": "2024-01-30", "history_end_date": "2024-01-30", "history_ready": True}}}, "csi300_earnings_yield_pct": base, "china_10y_government_bond_yield_pct": {"available": True, "observation_date": "2024-01-31", "value": 2.0}, "csi300_erp_pct": {"available": True, "observation_date": "2024-01-30", "value": 5.2}}, "earnings": {}, "trend": {}, "data_quality": {"coverage": {"valuation_pct": 0, "earnings_pct": 0, "trend_pct": 0, "a_fear_pct": 0}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["erp_lineage_violation_count"], 1)
        self.assertFalse(audit["structural_passed"])

    def test_erp_history_requires_sixty_available_months(self) -> None:
        records = []
        for ordinal in range(60):
            records.append({"month": f"2020-{ordinal + 1:02d}", "valuation": {"csi300_erp_pct": {"available": True, "observation_date": "2020-01-31"}}})
        cycle.decorate_erp_history(records)
        self.assertFalse(records[58]["valuation"]["csi300_erp_pct"]["history_ready"])
        self.assertTrue(records[59]["valuation"]["csi300_erp_pct"]["history_ready"])
        self.assertEqual(records[59]["valuation"]["csi300_erp_pct"]["history_observations"], 60)


if __name__ == "__main__":
    unittest.main()
