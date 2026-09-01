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
import cycle_earnings  # noqa: E402
import cycle_macro  # noqa: E402
import cycle_roe  # noqa: E402


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

    @staticmethod
    def balance(period: str, values: dict[str, float], ann: str, comp_type: str = "1", report_type: str = "1") -> pd.DataFrame:
        return cycle_roe.normalise_balance(pd.DataFrame([
            {"ts_code": code, "ann_date": ann, "f_ann_date": ann, "end_date": period, "report_type": report_type, "comp_type": comp_type, cycle_roe.EQUITY_FIELD: value, "update_flag": "0"}
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

    def test_valuation_warmup_uses_pre_2010_history_and_excludes_future(self) -> None:
        frame = pd.DataFrame([
            {"trade_date": "20070102", "pe_ttm": 100, "pb": 10},
            {"trade_date": "20080102", "pe_ttm": 90, "pb": 9},
            {"trade_date": "20090102", "pe_ttm": 80, "pb": 8},
            {"trade_date": "20100104", "pe_ttm": 85, "pb": 8.5},
            {"trade_date": "20200102", "pe_ttm": 1, "pb": 0.1},
        ])
        row = cycle.valuation_snapshot(frame, date(2010, 1, 31), "test")["pe_ttm"]
        self.assertEqual(row["history_observations"], 4)
        self.assertEqual(row["history_start_date"], "2007-01-02")
        self.assertEqual(row["history_end_date"], "2010-01-04")
        self.assertEqual(row["percentile_expanding"], 50.0)
        self.assertNotEqual(row["percentile_expanding"], 100.0)
        self.assertFalse(row["history_ready"])

    def test_valuation_history_ready_boundary_and_pre_inception_reason(self) -> None:
        dates = pd.bdate_range("2007-01-02", periods=504)
        frame = pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "pe_ttm": range(504), "pb": range(504)})
        ready = cycle.valuation_snapshot(frame, dates[-1].date(), "test")["pe_ttm"]
        self.assertTrue(ready["history_ready"])
        shorter = cycle.valuation_snapshot(frame.iloc[:-1], dates[-2].date(), "test")["pe_ttm"]
        self.assertFalse(shorter["history_ready"])
        future_only = pd.DataFrame({"trade_date": ["20141017"], "pe_ttm": [10], "pb": [1]})
        pre = cycle.valuation_snapshot(future_only, date(2010, 1, 29), "test")["pe_ttm"]
        self.assertFalse(pre["available"])
        self.assertTrue(pre["pre_inception"])
        self.assertEqual(pre["reason"], "valuation history not yet available for index")
        failed = cycle.valuation_snapshot(pd.DataFrame(columns=["trade_date", "pe_ttm", "pb"]), date(2010, 1, 29), "test", "endpoint unavailable")["pe_ttm"]
        self.assertFalse(failed["pre_inception"])
        self.assertEqual(failed["source_error"], "endpoint unavailable")

    def test_derived_earnings_yield_inherits_pe_observation_date(self) -> None:
        basis = date(2026, 8, 31)
        valuations = {name: pd.DataFrame({"trade_date": ["20260828"], "pe_ttm": [10], "pb": [1]}) for name in cycle.INDEXES}
        valuation = cycle.valuation_domain(valuations, {}, basis)
        pe = valuation["indices"]["csi300"]["pe_ttm"]
        earnings_yield = valuation["csi300_earnings_yield_pct"]
        self.assertEqual(earnings_yield["observation_date"], pe["observation_date"])
        self.assertEqual(earnings_yield["lag_days"], 3)
        self.assertEqual(earnings_yield["value"], 10.0)

    def test_unavailable_csi1000_source_is_not_backfilled_or_used_by_derived_yield(self) -> None:
        basis = date(2010, 1, 29)
        valuations = {name: pd.DataFrame(columns=["trade_date", "pe_ttm", "pb"]) for name in cycle.INDEXES}
        valuation = cycle.valuation_domain(valuations, {"csi1000": "empty index_dailybasic response"}, basis)
        csi1000 = valuation["indices"]["csi1000"]["pe_ttm"]
        self.assertFalse(csi1000["available"])
        self.assertFalse(csi1000["pre_inception"])
        self.assertEqual(csi1000["source_error"], "empty index_dailybasic response")
        self.assertFalse(valuation["csi300_earnings_yield_pct"]["available"])

    def test_valuation_audit_rejects_future_observation_and_bad_lineage(self) -> None:
        pe = {"available": True, "observation_date": "2024-02-01", "history_end_date": "2024-02-01", "history_ready": True}
        pb = {"available": True, "observation_date": "2024-01-31", "history_end_date": "2024-01-31", "history_ready": True}
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [{"month": "2024-01", "basis_trade_date": "2024-01-31", "valuation": {"indices": {"csi300": {"pe_ttm": pe, "pb": pb}}, "csi300_earnings_yield_pct": {"available": True, "observation_date": "2024-01-31"}}, "earnings": {}, "trend": {}, "data_quality": {"coverage": {"valuation_pct": 0, "earnings_pct": 0, "trend_pct": 0, "a_fear_pct": 0}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertGreater(audit["valuation_future_observation_count"], 0)
        self.assertEqual(audit["derived_lineage_violation_count"], 1)
        self.assertFalse(audit["structural_passed"])

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

    def test_pmi_future_publication_fails_structural_audit(self) -> None:
        pmi = cycle_macro.unavailable(date(2024, 1, 31), "unavailable")
        pmi.update({"available": True, "pit_safe": True, "value": 50.2, "observation_date": "2024-02-01", "publish_date": "2024-02-01"})
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [{
            "month": "2024-01", "basis_trade_date": "2024-01-31", "valuation": {}, "earnings": {"pmi": pmi}, "trend": {},
            "data_quality": {"coverage": {"valuation_pct": 0, "earnings_pct": 0, "trend_pct": 0, "a_fear_pct": 0}},
        }], "pmi_source_cache": {"conflict_count": 0, "release_conflict_count": 0, "crosscheck_mismatch_count": 0, "metadata": {}, "audit_counters": {}}}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["pmi_future_publication_count"], 1)
        self.assertFalse(audit["structural_passed"])

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
        income = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 1, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 2, "update_flag": "0"},
        ]))
        conflicts = cycle_earnings.source_conflicts(income)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), conflicts)), encoding="utf-8")
            _, _, loaded_conflicts = cycle_earnings.load_cache(path)
        self.assertEqual(loaded_conflicts, conflicts)

    def test_current_selector_rejects_later_single_quarter_and_parent_company_types(self) -> None:
        frame = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240420", "f_ann_date": "20240420", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 100, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "2", "comp_type": "1", "n_income_attr_p": 20, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240501", "f_ann_date": "20240501", "end_date": "20240331", "report_type": "6", "comp_type": "1", "n_income_attr_p": 999, "update_flag": "0"},
        ]))
        selected = cycle_earnings.select_current_statement(frame, date(2024, 5, 2))
        self.assertEqual(selected.iloc[0]["report_type"], "1")
        self.assertEqual(selected.iloc[0]["n_income_attr_p"], 100)

    def test_prior_selector_prefers_visible_adjusted_consolidated_statement(self) -> None:
        frame = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20230430", "f_ann_date": "20230430", "end_date": "20230331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 100, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20230331", "report_type": "4", "comp_type": "1", "n_income_attr_p": 120, "update_flag": "0"},
        ]))
        early = cycle_earnings.select_prior_comparable_statement(frame, date(2024, 4, 1))
        late = cycle_earnings.select_prior_comparable_statement(frame, date(2024, 5, 1))
        self.assertEqual(early.iloc[0]["report_type"], "1")
        self.assertEqual(late.iloc[0]["report_type"], "4")

    def test_ambiguous_source_conflict_is_excluded_from_statement_selection(self) -> None:
        frame = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 100, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 200, "update_flag": "0"},
        ]))
        self.assertTrue(cycle_earnings.select_current_statement(frame, date(2024, 5, 1)).empty)

    def test_selector_is_independent_of_api_order(self) -> None:
        rows = [
            {"ts_code": "000001.SZ", "ann_date": "20240420", "f_ann_date": "20240420", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 100, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20240425", "f_ann_date": "20240425", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 120, "update_flag": "1"},
        ]
        left = cycle_earnings.select_current_statement(cycle_earnings.normalise_income(pd.DataFrame(rows)), date(2024, 5, 1))
        right = cycle_earnings.select_current_statement(cycle_earnings.normalise_income(pd.DataFrame(list(reversed(rows)))), date(2024, 5, 1))
        self.assertEqual(left.iloc[0]["n_income_attr_p"], right.iloc[0]["n_income_attr_p"])

    def test_nonfinancial_denominator_is_classified_nonfinancial_universe(self) -> None:
        current = cycle_earnings.normalise_income(pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "1", "n_income_attr_p": 110, "update_flag": "0"},
            {"ts_code": "000002.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "2", "n_income_attr_p": 100, "update_flag": "0"},
            {"ts_code": "000003.SZ", "ann_date": "20240430", "f_ann_date": "20240430", "end_date": "20240331", "report_type": "1", "comp_type": "", "n_income_attr_p": 100, "update_flag": "0"},
        ]))
        prior = current.copy(); prior["end_date"] = "20230331"
        result = cycle_earnings.aggregate_side(current, prior, {"000001.SZ", "000002.SZ", "000003.SZ"}, True, date(2024, 5, 1), "20240331")
        self.assertEqual(result["eligible_stock_count"], 1)
        self.assertEqual(result["unknown_comp_type_count"], 1)

    def test_incremental_cache_appends_new_quarter_and_deduplicates_repeat_refresh(self) -> None:
        class FakePro:
            def income_vip(self, period: str, fields: str) -> pd.DataFrame:
                if period != "20260930":
                    return pd.DataFrame()
                return pd.DataFrame([{"ts_code": "000001.SZ", "ann_date": "20261020", "f_ann_date": "20261020", "end_date": period, "report_type": "1", "comp_type": "1", "n_income_attr_p": 100, "update_flag": "0"}])

            def stock_basic(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        q2 = self.income("20260630", {"000001.SZ": 90}, "20260820")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(q2, self.stocks(1), [], date(2026, 8, 31))), encoding="utf-8")
            first, _, _ = cycle_earnings.source_from_cache_or_api(FakePro(), path, 2026, 2026, date(2026, 10, 31))
            second, _, _ = cycle_earnings.source_from_cache_or_api(FakePro(), path, 2026, 2026, date(2026, 10, 31))
            self.assertIn("20260930", set(first["end_date"]))
            self.assertEqual(len(first), len(second))
            self.assertEqual(cycle_earnings.load_cache_metadata(path)["latest_period"], "20260930")

    def test_new_revision_only_changes_months_after_its_announcement_date(self) -> None:
        current = self.income("20240331", {"000001.SZ": 120}, "20240430")
        prior_original = self.income("20230331", {"000001.SZ": 100}, "20230430")
        revision = cycle_earnings.normalise_income(pd.DataFrame([{"ts_code": "000001.SZ", "ann_date": "20240520", "f_ann_date": "20240520", "end_date": "20230331", "report_type": "4", "comp_type": "1", "n_income_attr_p": 110, "update_flag": "1"}]))
        periods = {"20240331": current, "20230331": cycle_earnings.append_income(prior_original, revision)}
        before = cycle_earnings.profit_growth_snapshot(periods, self.stocks(1), date(2024, 5, 1))["all_a"]
        after = cycle_earnings.profit_growth_snapshot(periods, self.stocks(1), date(2024, 5, 31))["all_a"]
        self.assertEqual(before["value"], 20.0)
        self.assertNotEqual(after["value"], before["value"])
        self.assertEqual(after["prior_comparator_report_types_used"], ["4"])

    def test_cache_freshness_respects_statutory_disclosure_deadlines(self) -> None:
        income = cycle_earnings.normalise_income(pd.concat([self.income(period, {"000001.SZ": 1}, "20260820") for period in ("20260331", "20260630")], ignore_index=True))
        meta = cycle_earnings.cache_metadata(income, [], date(2026, 8, 31))
        september = cycle_earnings.audit_cache_freshness(income, meta, date(2026, 9, 30), 2026)
        october = cycle_earnings.audit_cache_freshness(income, meta, date(2026, 10, 31), 2026)
        self.assertFalse(september["stale"])
        self.assertTrue(october["stale"])
        self.assertIn("20260930", october["missing_expected_periods"])

    def test_annual_period_is_not_required_before_april_thirtieth(self) -> None:
        income = cycle_earnings.normalise_income(pd.concat([self.income(period, {"000001.SZ": 1}, "20261020") for period in ("20260331", "20260630", "20260930")], ignore_index=True))
        meta = cycle_earnings.cache_metadata(income, [], date(2027, 4, 1))
        self.assertFalse(cycle_earnings.audit_cache_freshness(income, meta, date(2027, 4, 29), 2026)["stale"])
        self.assertTrue(cycle_earnings.audit_cache_freshness(income, meta, date(2027, 4, 30), 2026)["stale"])

    def test_stock_lifecycle_enriches_delisting_without_rewriting_history(self) -> None:
        existing = cycle_earnings.normalise_stocks(pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": ""}]))
        fresh = cycle_earnings.normalise_stocks(pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": "20270630"}]))
        merged, conflicts = cycle_earnings.append_stocks(existing, fresh)
        self.assertEqual(conflicts, [])
        self.assertEqual(cycle_earnings.eligible_universe(merged, "20260331"), {"000001.SZ"})
        self.assertNotIn("000001.SZ", cycle_earnings.eligible_universe(merged, "20270630"))

    def test_stock_metadata_conflict_is_recorded(self) -> None:
        existing = cycle_earnings.normalise_stocks(pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": "20270630"}]))
        fresh = cycle_earnings.normalise_stocks(pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100102", "delist_date": "20270701"}]))
        _, conflicts = cycle_earnings.append_stocks(existing, fresh)
        self.assertEqual({row["field"] for row in conflicts}, {"list_date", "delist_date"})

    def test_refresh_failure_uses_old_cache_without_modifying_it(self) -> None:
        class BrokenPro:
            def income_vip(self, **_: object) -> pd.DataFrame:
                raise RuntimeError("income endpoint unavailable")

            def stock_basic(self, **_: object) -> pd.DataFrame:
                raise RuntimeError("stock endpoint unavailable")

        income = self.income("20260630", {"000001.SZ": 90}, "20260820")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), [], date(2026, 8, 15))), encoding="utf-8")
            before = path.read_bytes()
            result_income, result_stocks, conflicts, metadata, error = cycle_earnings.source_from_cache_or_api_status(BrokenPro(), path, 2026, 2026, date(2026, 8, 31), refresh=True)
            freshness = cycle_earnings.audit_cache_freshness(result_income, metadata, date(2026, 8, 31), 2026, error)
            audit = cycle.audit_dataset({"dataset_version": cycle.DATASET_VERSION, "records": [], "earnings_source_cache": {"conflict_count": len(conflicts), "conflicts": conflicts, "metadata": metadata, **freshness, "offline": False}})
            self.assertEqual(len(result_income), len(income))
            self.assertEqual(len(result_stocks), 1)
            self.assertIn("income endpoint unavailable", error)
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(audit["structural_passed"])
            self.assertFalse(audit["freshness_passed"])
            self.assertFalse(audit["passed"])

    def test_no_cache_and_refresh_failure_returns_unavailable_source(self) -> None:
        class BrokenPro:
            def income_vip(self, **_: object) -> pd.DataFrame:
                raise RuntimeError("income endpoint unavailable")

        with tempfile.TemporaryDirectory() as directory:
            income, stocks, _, _, error = cycle_earnings.source_from_cache_or_api_status(BrokenPro(), Path(directory) / "cache.json", 2026, 2026, date(2026, 8, 31))
        self.assertIsNone(income)
        self.assertIsNone(stocks)
        self.assertIn("income endpoint unavailable", error)

    def test_successful_refresh_uses_injected_access_date_not_dataset_as_of(self) -> None:
        class FakePro:
            def income_vip(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

            def stock_basic(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        income = self.income("20260630", {"000001.SZ": 90}, "20260820")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), [], date(2026, 8, 15))), encoding="utf-8")
            _, _, _, metadata, error = cycle_earnings.source_from_cache_or_api_status(FakePro(), path, 2026, 2026, date(2026, 8, 31), refresh_date=date(2026, 9, 2))
        self.assertIsNone(error)
        self.assertEqual(metadata["last_successful_refresh_date"], "2026-09-02")
        self.assertNotEqual(metadata["last_successful_refresh_date"], "2026-08-31")

    def test_metadata_round_trip_preserves_conflicts_and_custom_fields(self) -> None:
        income = self.income("20260630", {"000001.SZ": 90}, "20260820")
        metadata = {"last_successful_refresh_date": "2026-08-15", "stock_metadata_conflicts": [{"ts_code": "000001.SZ", "field": "delist_date"}], "refresh_error": "historic audit detail", "future_schema_field": {"retained": True}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), [], metadata=metadata)), encoding="utf-8")
            loaded = cycle_earnings.load_cache_metadata(path)
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), [], metadata=loaded)), encoding="utf-8")
            round_trip = cycle_earnings.load_cache_metadata(path)
        self.assertEqual(round_trip["stock_metadata_conflicts"], metadata["stock_metadata_conflicts"])
        self.assertEqual(round_trip["future_schema_field"], metadata["future_schema_field"])
        self.assertEqual(round_trip["refresh_error"], metadata["refresh_error"])
        self.assertEqual(round_trip["last_successful_refresh_date"], "2026-08-15")

    def test_offline_read_does_not_change_last_successful_refresh(self) -> None:
        income = self.income("20260630", {"000001.SZ": 90}, "20260820")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(__import__("json").dumps(cycle_earnings.cache_payload(income, self.stocks(1), [], date(2026, 8, 15))), encoding="utf-8")
            _, _, _, metadata, error = cycle_earnings.source_from_cache_or_api_status(None, path, 2026, 2026, date(2026, 8, 31), refresh=False)
        self.assertIsNone(error)
        self.assertEqual(metadata["last_successful_refresh_date"], "2026-08-15")

    def test_affected_source_conflicts_only_lists_conflicts_with_cycle_months(self) -> None:
        conflict = {"identity": {"ts_code": "000001.SZ", "end_date": "20240331", "report_type": "1", "_effective_ann_str": "20240430", "update_flag": "0"}}
        payload = {"dataset_version": cycle.DATASET_VERSION, "earnings_source_cache": {"conflict_count": 1, "conflicts": [conflict], "metadata": {}}, "records": [{"month": "2024-05", "basis_trade_date": "2024-05-31", "earnings": {"all_a_net_profit_yoy_pct": {"report_period": "20240331", "prior_year_report_period": "20230331"}}, "data_quality": {"coverage": {}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["affected_months"], ["2024-05"])
        self.assertEqual(audit["affected_source_identities"], [conflict])
        unaffected = cycle.audit_dataset({**payload, "records": [{**payload["records"][0], "month": "2024-04", "basis_trade_date": "2024-04-29"}]})
        self.assertEqual(unaffected["affected_month_count"], 0)
        self.assertEqual(unaffected["affected_source_identities"], [])

    def test_roe_ttm_uses_q1_formula_and_aggregate_equity(self) -> None:
        codes = {"000001.SZ": 20, "000002.SZ": 2}
        income = {
            "20240331": self.income("20240331", codes, "20240430"),
            "20231231": self.income("20231231", {"000001.SZ": 100, "000002.SZ": 10}, "20240131"),
            "20230331": self.income("20230331", {"000001.SZ": 10, "000002.SZ": 1}, "20230430"),
        }
        balance = {"20240331": self.balance("20240331", {"000001.SZ": 1000, "000002.SZ": 10}, "20240430"), "20230331": self.balance("20230331", {"000001.SZ": 800, "000002.SZ": 10}, "20230430")}
        result = cycle_roe.roe_snapshot(income, balance, self.stocks(2), date(2024, 5, 1), "20240331")["all_a"]
        self.assertAlmostEqual(result["ttm_parent_profit"], 121.0)
        self.assertAlmostEqual(result["average_parent_equity"], 910.0)
        self.assertAlmostEqual(result["value"], 121 / 910 * 100, places=4)

    def test_roe_ttm_formulas_for_h1_q3_and_fy(self) -> None:
        def frame(period: str, value: float) -> pd.DataFrame:
            return self.income(period, {"000001.SZ": value}, "20241030")
        income = {"20240630": frame("20240630", 30), "20240930": frame("20240930", 50), "20241231": frame("20241231", 120), "20230630": frame("20230630", 15), "20230930": frame("20230930", 25), "20231231": frame("20231231", 100)}
        self.assertEqual(float(cycle_roe.ttm_profit_by_code(income, "20240630", date(2024, 11, 1))[0].iloc[0]), 115)
        self.assertEqual(float(cycle_roe.ttm_profit_by_code(income, "20240930", date(2024, 11, 1))[0].iloc[0]), 125)
        self.assertEqual(float(cycle_roe.ttm_profit_by_code(income, "20241231", date(2024, 11, 1))[0].iloc[0]), 120)

    def test_roe_prior_equity_prefers_visible_adjusted_statement(self) -> None:
        income = {"20240331": self.income("20240331", {"000001.SZ": 20}, "20240430"), "20231231": self.income("20231231", {"000001.SZ": 100}, "20240131"), "20230331": self.income("20230331", {"000001.SZ": 10}, "20230430")}
        balance = {"20240331": self.balance("20240331", {"000001.SZ": 1000}, "20240430"), "20230331": cycle_roe.normalise_balance(pd.concat([self.balance("20230331", {"000001.SZ": 800}, "20230430"), self.balance("20230331", {"000001.SZ": 900}, "20240501", report_type="4")], ignore_index=True))}
        early = cycle_roe.roe_snapshot(income, balance, self.stocks(1), date(2024, 5, 1), "20240331")["all_a"]
        self.assertEqual(early["prior_equity_report_types_used"], ["4"])
        self.assertEqual(early["prior_year_parent_equity"], 900.0)

    def test_roe_rejects_future_component_and_nonpositive_aggregate_equity(self) -> None:
        income = {"20240331": self.income("20240331", {"000001.SZ": 20}, "20240430"), "20231231": self.income("20231231", {"000001.SZ": 100}, "20240601"), "20230331": self.income("20230331", {"000001.SZ": 10}, "20230430")}
        balance = {"20240331": self.balance("20240331", {"000001.SZ": -10}, "20240430"), "20230331": self.balance("20230331", {"000001.SZ": -10}, "20230430")}
        future = cycle_roe.roe_snapshot(income, balance, self.stocks(1), date(2024, 5, 1), "20240331")["all_a"]
        self.assertFalse(future["available"])
        income["20231231"] = self.income("20231231", {"000001.SZ": 100}, "20240131")
        negative = cycle_roe.roe_snapshot(income, balance, self.stocks(1), date(2024, 5, 1), "20240331")["all_a"]
        self.assertFalse(negative["available"])
        self.assertEqual(negative["reason"], "non-positive aggregate average equity")

    def test_roe_nonfinancial_excludes_financial_and_unknown_comp_types(self) -> None:
        income = {
            "20240331": cycle_earnings.normalise_income(pd.concat([self.income("20240331", {"000001.SZ": 20}, "20240430", "1"), self.income("20240331", {"000002.SZ": 20}, "20240430", "2"), self.income("20240331", {"000003.SZ": 20}, "20240430", "")], ignore_index=True)),
            "20231231": cycle_earnings.normalise_income(pd.concat([self.income("20231231", {"000001.SZ": 100}, "20240131", "1"), self.income("20231231", {"000002.SZ": 100}, "20240131", "2"), self.income("20231231", {"000003.SZ": 100}, "20240131", "")], ignore_index=True)),
            "20230331": cycle_earnings.normalise_income(pd.concat([self.income("20230331", {"000001.SZ": 10}, "20230430", "1"), self.income("20230331", {"000002.SZ": 10}, "20230430", "2"), self.income("20230331", {"000003.SZ": 10}, "20230430", "")], ignore_index=True)),
        }
        balance = {period: cycle_roe.normalise_balance(pd.concat([self.balance(period, {"000001.SZ": 100}, ann, "1"), self.balance(period, {"000002.SZ": 100}, ann, "2"), self.balance(period, {"000003.SZ": 100}, ann, "")], ignore_index=True)) for period, ann in (("20240331", "20240430"), ("20230331", "20230430"))}
        roe = cycle_roe.roe_snapshot(income, balance, self.stocks(3), date(2024, 5, 1), "20240331")
        self.assertEqual(roe["nonfinancial_a"]["eligible_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["matched_stock_count"], 1)

    def test_roe_nonfinancial_universe_is_a_subset_of_historical_all_a_universe(self) -> None:
        income = {"20240331": self.income("20240331", {"000001.SZ": 20, "000002.SZ": 2000}, "20240430"), "20231231": self.income("20231231", {"000001.SZ": 100, "000002.SZ": 10000}, "20240131"), "20230331": self.income("20230331", {"000001.SZ": 10, "000002.SZ": 1000}, "20230430")}
        balance = {"20240331": self.balance("20240331", {"000001.SZ": 100, "000002.SZ": 10000}, "20240430"), "20230331": self.balance("20230331", {"000001.SZ": 100, "000002.SZ": 10000}, "20230430")}
        stocks = pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": ""}, {"ts_code": "000002.SZ", "list_date": "20250101", "delist_date": ""}])
        roe = cycle_roe.roe_snapshot(income, balance, cycle_earnings.normalise_stocks(stocks), date(2024, 5, 1), "20240331")
        self.assertEqual(roe["all_a"]["eligible_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["eligible_stock_count"], 1)
        self.assertEqual(roe["all_a"]["matched_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["matched_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["ttm_parent_profit"], 110.0)
        self.assertEqual(roe["nonfinancial_a"]["current_parent_equity"], 100.0)
        self.assertEqual(roe["nonfinancial_a"]["prior_year_parent_equity"], 100.0)
        self.assertEqual(roe["nonfinancial_a"]["all_a_eligible_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["classified_nonfinancial_eligible_stock_count"], 1)

    def test_roe_later_delisted_company_remains_in_historical_nonfinancial_universe(self) -> None:
        income = {"20240331": self.income("20240331", {"000001.SZ": 20}, "20240430"), "20231231": self.income("20231231", {"000001.SZ": 100}, "20240131"), "20230331": self.income("20230331", {"000001.SZ": 10}, "20230430")}
        balance = {"20240331": self.balance("20240331", {"000001.SZ": 100}, "20240430"), "20230331": self.balance("20230331", {"000001.SZ": 100}, "20230430")}
        stocks = cycle_earnings.normalise_stocks(pd.DataFrame([{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": "20250101"}]))
        roe = cycle_roe.roe_snapshot(income, balance, stocks, date(2024, 5, 1), "20240331")
        self.assertEqual(roe["all_a"]["eligible_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["eligible_stock_count"], 1)
        self.assertEqual(roe["nonfinancial_a"]["matched_stock_count"], 1)

    def test_roe_audit_fails_on_nonfinancial_subset_violation(self) -> None:
        base = {"available": True, "announcement_date": "2024-04-30", "current_statement_report_type": "1", "prior_equity_report_types_used": ["1"]}
        payload = {"dataset_version": cycle.DATASET_VERSION, "records": [{"month": "2024-05", "basis_trade_date": "2024-05-31", "valuation": {}, "trend": {}, "earnings": {"all_a_roe_ttm_pct": {**base, "eligible_stock_count": 1, "matched_stock_count": 1}, "nonfinancial_a_roe_ttm_pct": {**base, "eligible_stock_count": 2, "matched_stock_count": 2}}, "data_quality": {"coverage": {"valuation_pct": 0, "earnings_pct": 0, "trend_pct": 0, "a_fear_pct": 0}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertEqual(audit["roe_nonfinancial_universe_violation_count"], 1)
        self.assertEqual(audit["roe_nonfinancial_matched_violation_count"], 1)
        self.assertEqual(audit["roe_universe_violation_months"], ["2024-05"])
        self.assertFalse(audit["structural_passed"])

    def test_committed_cycle_history_obeys_roe_subset_invariants(self) -> None:
        payload = json.loads((ROOT / "data" / "cycle_dataset_v1.json").read_text(encoding="utf-8"))
        audit = cycle.audit_dataset(payload)
        self.assertEqual(len(payload["records"]), 200)
        self.assertEqual(audit["roe_nonfinancial_universe_violation_count"], 0)
        self.assertEqual(audit["roe_nonfinancial_matched_violation_count"], 0)
        self.assertEqual(audit["roe_universe_violation_months"], [])

    def test_roe_balance_cache_failure_uses_existing_rows(self) -> None:
        class BrokenPro:
            def balancesheet_vip(self, **_: object) -> pd.DataFrame:
                raise RuntimeError("balance endpoint unavailable")

        balance = self.balance("20260630", {"000001.SZ": 100}, "20260820")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roe.json"
            path.write_text(__import__("json").dumps(cycle_roe.cache_payload(balance, [], date(2026, 8, 15))), encoding="utf-8")
            before = path.read_bytes()
            returned, _, _, error = cycle_roe.source_from_cache_or_api_status(BrokenPro(), path, 2026, 2026, date(2026, 8, 31))
            after = path.read_bytes()
        self.assertEqual(len(returned), 1)
        self.assertIn("balance endpoint unavailable", error)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
