import sys
import unittest
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, "scripts")
import build_cycle_dataset as cycle  # noqa: E402


def price_frame(count: int, start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=count)
    return pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "close": [100.0 + i for i in range(count)]})


class TrendPITTests(unittest.TestCase):
    def test_canonical_fields_and_future_price_are_excluded(self) -> None:
        frame = price_frame(314)
        frame.loc[len(frame)] = ["20300101", 999999.0]
        row = cycle.trend_snapshot(frame, date(2021, 3, 31), "test")
        self.assertEqual(set(cycle.TREND_FIELDS), set(row))
        self.assertLess(row["close"]["value"], 999999.0)
        self.assertEqual(row["close"]["observation_date"], row["close"]["history_end_date"])

    def test_last_null_close_does_not_pair_date_with_previous_close(self) -> None:
        frame = price_frame(314)
        frame.loc[len(frame)] = ["20210316", None]
        row = cycle.trend_snapshot(frame, date(2021, 3, 16), "test")
        self.assertEqual(row["close"]["observation_date"], "2021-03-15")
        self.assertNotEqual(row["close"]["observation_date"], "2021-03-16")

    def test_ma250_and_history_ready_boundaries(self) -> None:
        for count, available, ready in ((249, False, False), (250, True, False), (312, True, False), (313, True, True)):
            row = cycle.trend_snapshot(price_frame(count), date(2022, 1, 1), "test")
            self.assertEqual(row["ma250"]["available"], available if count >= 250 else False)
            self.assertEqual(row["close"]["history_ready"], ready)

    def test_formulas_use_trading_observation_intervals(self) -> None:
        frame = price_frame(313)
        row = cycle.trend_snapshot(frame, date(2021, 3, 15), "test")
        close = row["close"]["value"]
        ma = row["ma250"]["value"]
        self.assertAlmostEqual(row["ma250_deviation_pct"]["value"], (close / ma - 1) * 100, places=4)
        self.assertEqual(row["above_ma250"]["value"], close >= ma)
        self.assertAlmostEqual(row["return_6m_pct"]["value"], (close / row["return_6m_pct"]["reference_close_126_observations_ago"] - 1) * 100, places=4)
        self.assertAlmostEqual(row["return_12m_pct"]["value"], (close / row["return_12m_pct"]["reference_close_252_observations_ago"] - 1) * 100, places=4)
        self.assertAlmostEqual(row["ma250_slope_3m_pct"]["value"], (ma / row["ma250_slope_3m_pct"]["reference_ma250_63_observations_ago"] - 1) * 100, places=4)

    def test_drawdown_is_inclusive_252_observations_and_never_positive(self) -> None:
        frame = price_frame(313)
        row = cycle.trend_snapshot(frame, date(2022, 1, 1), "test")
        self.assertLessEqual(row["drawdown_12m_high_pct"]["value"], 0)
        frame.loc[0, "close"] = 1000000.0
        row = cycle.trend_snapshot(frame, date(2022, 1, 1), "test")
        self.assertEqual(row["drawdown_12m_high_pct"]["value"], 0.0)
        frame.loc[0, "trade_date"] = "20190101"
        row = cycle.trend_snapshot(frame, date(2022, 1, 1), "test")
        self.assertLessEqual(row["drawdown_12m_high_pct"]["value"], 0)

    def test_pre_inception_is_distinct_from_source_error(self) -> None:
        frame = price_frame(314, "2022-01-01")
        pre = cycle.trend_snapshot(frame, date(2021, 12, 31), "test")
        self.assertTrue(pre["close"]["pre_inception"])
        self.assertIsNone(pre["close"]["source_error"])
        failed = cycle.trend_snapshot(pd.DataFrame(columns=["trade_date", "close"]), date(2022, 1, 1), "test", "API failed")
        self.assertFalse(failed["close"]["pre_inception"])
        self.assertEqual(failed["close"]["source_error"], "API failed")

    def test_official_launch_date_blocks_backfilled_history_before_launch(self) -> None:
        frame = price_frame(600, "2005-01-01")
        before = cycle.trend_snapshot(frame, date(2014, 10, 16), "test", official_launch_date=date(2014, 10, 17))
        self.assertTrue(before["close"]["pre_inception"])
        self.assertFalse(before["close"]["available"])
        self.assertEqual(before["close"]["reason"], "index not officially published at basis date")
        after = cycle.trend_snapshot(frame, date(2014, 10, 17), "test", official_launch_date=date(2014, 10, 17))
        self.assertTrue(after["close"]["available"])
        self.assertTrue(after["ma250"]["history_ready"])
        self.assertEqual(after["close"]["official_launch_date"], "2014-10-17")

    def test_audit_rejects_prelaunch_available_trend(self) -> None:
        basis = date(2014, 10, 16)
        trend = cycle.trend_snapshot(price_frame(400, "2005-01-01"), basis, "test", official_launch_date=date(2014, 10, 17))
        trend["close"]["available"] = True
        trend["close"]["value"] = 1.0
        payload = {"dataset_version": cycle.DATASET_VERSION, "trend_source_metadata": {"csi1000": {"official_launch_date": "2014-10-17", "source_conflict_count": 0}}, "records": [{"month": "2014-10", "basis_trade_date": basis.isoformat(), "valuation": {}, "earnings": {}, "trend": {"indices": {"csi1000": trend}}, "data_quality": {"coverage": {"trend_pct": 100}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertGreater(audit["trend_prelaunch_visibility_violation_count"], 0)
        self.assertFalse(audit["structural_passed"])

    def test_chunk_windows_are_contiguous(self) -> None:
        windows = cycle.valuation_date_windows(date(2005, 1, 1), date(2026, 8, 31), 5)
        self.assertEqual(windows[0][0], date(2005, 1, 1))
        self.assertEqual(windows[-1][1], date(2026, 8, 31))
        for left, right in zip(windows, windows[1:]):
            self.assertEqual(left[1] + timedelta(days=1), right[0])

    def test_same_date_close_dedup_and_conflict_metadata(self) -> None:
        frame = price_frame(313)
        same = frame.iloc[-1].copy()
        duplicate = pd.concat([frame, pd.DataFrame([same])], ignore_index=True)
        row = cycle.trend_snapshot(duplicate, date(2022, 1, 1), "test")
        self.assertTrue(row["close"]["available"])
        conflict = pd.concat([frame, pd.DataFrame([{ "trade_date": same["trade_date"], "close": 999.0, "_source_conflict": True }])], ignore_index=True)
        row = cycle.trend_snapshot(conflict, date(2022, 1, 1), "test")
        self.assertNotEqual(row["close"]["value"], 999.0)

    def test_trend_audit_rejects_future_alignment_formula_and_positive_drawdown(self) -> None:
        basis = date(2022, 1, 31)
        trend = cycle.trend_snapshot(price_frame(313), basis, "test")
        trend["return_6m_pct"]["observation_date"] = "2022-02-01"
        trend["ma250_deviation_pct"]["value"] += 1
        trend["drawdown_12m_high_pct"]["value"] = 1
        payload = {"dataset_version": cycle.DATASET_VERSION, "trend_source_metadata": {"csi300": {"source_conflict_count": 0}}, "records": [{"month": "2022-01", "basis_trade_date": basis.isoformat(), "valuation": {}, "earnings": {}, "trend": {"indices": {"csi300": trend}}, "data_quality": {"coverage": {"trend_pct": 100}}}]}
        audit = cycle.audit_dataset(payload)
        self.assertGreater(audit["trend_future_observation_count"], 0)
        self.assertGreater(audit["trend_observation_alignment_violation_count"], 0)
        self.assertGreater(audit["trend_formula_violation_count"], 0)
        self.assertGreater(audit["trend_invalid_drawdown_count"], 0)
        self.assertFalse(audit["structural_passed"])


if __name__ == "__main__":
    unittest.main()
