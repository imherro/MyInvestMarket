from __future__ import annotations

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
import cycle_earnings  # noqa: E402


class CycleDatasetTests(unittest.TestCase):
    @staticmethod
    def stocks(count: int) -> pd.DataFrame:
        return pd.DataFrame([{"ts_code": f"{index:06d}.SZ", "list_date": "20100101", "delist_date": ""} for index in range(1, count + 1)])

    @staticmethod
    def income(period: str, values: dict[str, float], ann: str, comp_type: str = "1") -> pd.DataFrame:
        return cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": code, "ann_date": ann, "f_ann_date": ann, "end_date": period, "report_type": "1", "comp_type": comp_type, "n_income_attr_p": value, "update_flag": "0"}
            for code, value in values.items()
        ]))

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

    def test_coverage_69_percent_keeps_previous_quarter(self) -> None:
        codes = [f"{index:06d}.SZ" for index in range(1, 14)]
        periods = {
            "20240331": self.income("20240331", {code: 110 for code in codes[:9]}, "20240430"),
            "20230331": self.income("20230331", {code: 100 for code in codes[:9]}, "20230430"),
            "20231231": self.income("20231231", {code: 120 for code in codes}, "20240120"),
            "20221231": self.income("20221231", {code: 100 for code in codes}, "20230120"),
        }
        result = cycle_earnings.profit_growth_snapshot(periods, self.stocks(13), date(2024, 5, 1))
        self.assertEqual(result["all_a"]["report_period"], "20231231")

    def test_coverage_70_percent_allows_new_quarter(self) -> None:
        codes = [f"{index:06d}.SZ" for index in range(1, 11)]
        periods = {
            "20240331": self.income("20240331", {code: 110 for code in codes[:7]}, "20240430"),
            "20230331": self.income("20230331", {code: 100 for code in codes[:7]}, "20230430"),
        }
        result = cycle_earnings.profit_growth_snapshot(periods, self.stocks(10), date(2024, 5, 1))
        self.assertEqual(result["all_a"]["report_period"], "20240331")

    def test_profit_growth_uses_identical_matched_company_set(self) -> None:
        current = self.income("20240331", {"000001.SZ": 100, "000002.SZ": 200, "000003.SZ": 900}, "20240430")
        prior = self.income("20230331", {"000001.SZ": 50, "000002.SZ": 100}, "20230430")
        result = cycle_earnings.aggregate_side(current, prior, {"000001.SZ", "000002.SZ", "000003.SZ"}, False, date(2024, 5, 1), "20240331")
        self.assertEqual(result["matched_stock_count"], 2)
        self.assertEqual(result["current_aggregate_profit"], 300.0)
        self.assertEqual(result["prior_aggregate_profit"], 150.0)

    def test_later_delisted_stock_stays_in_historical_universe_and_later_ipo_does_not(self) -> None:
        stocks = pd.DataFrame([
            {"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": "20250101"},
            {"ts_code": "000002.SZ", "list_date": "20250101", "delist_date": ""},
        ])
        self.assertEqual(cycle_earnings.eligible_universe(cycle_earnings.normalise_stocks(stocks), "20240331"), {"000001.SZ"})

    def test_nonfinancial_excludes_financial_and_unknown_comp_types(self) -> None:
        current = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 110, "update_flag": "0"},
            {"ts_code": "000002.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "2", "n_income_attr_p": 999, "update_flag": "0"},
            {"ts_code": "000003.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "", "n_income_attr_p": 999, "update_flag": "0"},
        ]))
        prior = current.copy()
        prior["end_date"] = "20230331"
        result = cycle_earnings.aggregate_side(current, prior, {"000001.SZ", "000002.SZ", "000003.SZ"}, True, date(2024, 5, 1), "20240331")
        self.assertEqual(result["matched_stock_count"], 1)
        self.assertLess(result["classification_coverage_rate"], 100)

    def test_nonpositive_prior_profit_is_unavailable(self) -> None:
        current = self.income("20240331", {"000001.SZ": 10}, "20240430")
        prior = self.income("20230331", {"000001.SZ": -1}, "20230430")
        result = cycle_earnings.aggregate_side(current, prior, {"000001.SZ"}, False, date(2024, 5, 1), "20240331")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "non-positive aggregate prior-year profit")

    def test_same_company_multiple_versions_only_uses_visible_latest_version(self) -> None:
        frame = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240420", "f_ann_date": "20240420", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 10, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240520", "f_ann_date": "20240520", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 20, "update_flag": "1"},
        ]))
        self.assertEqual(cycle_earnings.visible_deduped(frame, date(2024, 5, 1)).iloc[0]["n_income_attr_p"], 10)
        self.assertEqual(cycle_earnings.visible_deduped(frame, date(2024, 5, 30)).iloc[0]["n_income_attr_p"], 20)

    def test_cache_conflicts_are_retained_not_silently_discarded(self) -> None:
        income = self.income("20240331", {"000001.SZ": 1}, "20240430")
        conflicts = [{"identity": {"ts_code": "000001.SZ"}, "value_count": 2}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), conflicts)), encoding="utf-8")
            _, _, loaded_conflicts = cycle_earnings.load_cache(path)
        self.assertEqual(loaded_conflicts, conflicts)


if __name__ == "__main__":
    unittest.main()
