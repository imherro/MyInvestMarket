from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_cycle_dataset as cycle  # noqa: E402


class CycleDatasetTests(unittest.TestCase):
    def test_financial_observation_announced_after_basis_is_invisible(self) -> None:
        frame = pd.DataFrame([
            {"ann_date": "20240501", "end_date": "20240331", "value": 1},
            {"ann_date": "20240515", "end_date": "20240331", "value": 2},
        ])
        row = cycle.latest_financial_observation(frame, date(2024, 5, 10))
        self.assertEqual(row["value"], 1)

    def test_financial_observation_announced_on_basis_is_visible(self) -> None:
        frame = pd.DataFrame([{"ann_date": "20240510", "end_date": "20240331", "value": 1}])
        row = cycle.latest_financial_observation(frame, date(2024, 5, 10))
        self.assertEqual(row["value"], 1)

    def test_valuation_percentile_uses_only_history_at_basis(self) -> None:
        frame = pd.DataFrame([
            {"trade_date": "20240101", "pe_ttm": 10, "pb": 1},
            {"trade_date": "20240102", "pe_ttm": 20, "pb": 2},
            {"trade_date": "20250101", "pe_ttm": 1, "pb": 0.5},
        ])
        row = cycle.valuation_snapshot(frame, date(2024, 1, 2), "test")
        self.assertEqual(row["pe_ttm"]["percentile_expanding"], 100.0)

    def test_ma250_does_not_consume_future_prices(self) -> None:
        dates = pd.bdate_range("2023-01-02", periods=251)
        frame = pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "close": list(range(1, 252))})
        basis = dates[249].date()
        row = cycle.trend_snapshot(frame, basis, "test")
        self.assertAlmostEqual(row["ma250_deviation_pct"]["value"], (250 / 125.5 - 1) * 100, places=4)

    def test_months_and_basis_dates_must_be_unique(self) -> None:
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [
            {"month": "2024-01", "basis_trade_date": "2024-01-31", "data_quality": {"coverage": {}}},
            {"month": "2024-01", "basis_trade_date": "2024-01-31", "data_quality": {"coverage": {}}},
        ]}
        audit = cycle.audit_dataset(payload)
        self.assertGreater(audit["duplicate_count"], 0)
        self.assertFalse(audit["passed"])

    def test_months_must_be_strictly_ascending(self) -> None:
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [
            {"month": "2024-02", "basis_trade_date": "2024-02-29", "data_quality": {"coverage": {}}},
            {"month": "2024-01", "basis_trade_date": "2024-01-31", "data_quality": {"coverage": {}}},
        ]}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["order_violation_count"], 1)
        self.assertFalse(audit["passed"])

    def test_missing_earnings_are_not_neutral(self) -> None:
        result = cycle.unavailable_earnings(date(2024, 1, 31), "unavailable")
        self.assertIsNone(result["all_a_roe_ttm_pct"]["value"])
        self.assertFalse(result["all_a_roe_ttm_pct"]["available"])

    def test_a_fear_unavailable_is_nonblocking(self) -> None:
        original = cycle.DATA_DIR
        try:
            cycle.DATA_DIR = Path(self.id())
            row = cycle.a_fear_snapshot(date(2015, 1, 30))
        finally:
            cycle.DATA_DIR = original
        self.assertFalse(row["available"])

    def test_pit_audit_rejects_injected_future_observation(self) -> None:
        future = cycle.feature(1.0, date(2024, 1, 31), "test", observation_date=date(2024, 2, 1))
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [{
            "month": "2024-01", "basis_trade_date": "2024-01-31",
            "valuation": {"x": future}, "earnings": {}, "trend": {},
            "data_quality": {"coverage": {"valuation_pct": 0, "earnings_pct": 0, "trend_pct": 0, "a_fear_pct": 0}},
        }]}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["pit_violation_count"], 1)
        self.assertFalse(audit["passed"])


if __name__ == "__main__":
    unittest.main()
