from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_market_dataset  # noqa: E402
import market_scoring  # noqa: E402


class MacroFreshnessContractTest(unittest.TestCase):
    def test_latest_series_value_uses_observation_at_or_before_basis_date(self) -> None:
        q = build_market_dataset.Quality()
        series = pd.Series(
            [4.2, 9.9],
            index=[pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-19")],
        )

        result = build_market_dataset.latest_series_value_at_or_before(
            series,
            "macro.us_10y_treasury_yield_pct",
            q,
            date(2026, 6, 18),
            "FRED:DGS10",
        )

        self.assertEqual(result["date"], "2026-06-18")
        self.assertEqual(result["value"], 4.2)
        freshness = q.feature_freshness["macro.us_10y_treasury_yield_pct"]
        self.assertEqual(freshness["basis_date"], "2026-06-18")
        self.assertEqual(freshness["observation_date"], "2026-06-18")
        self.assertEqual(freshness["lag_days"], 0)
        self.assertEqual(freshness["ignored_future_observations"], 1)
        self.assertTrue(any("future-dated" in warning for warning in q.warnings))

    def test_all_future_series_values_are_missing_after_cutoff(self) -> None:
        q = build_market_dataset.Quality()
        series = pd.Series([9.9], index=[pd.Timestamp("2026-06-19")])

        result = build_market_dataset.latest_series_value_at_or_before(
            series,
            "macro.dxy",
            q,
            date(2026, 6, 18),
            "yfinance:DX-Y.NYB",
        )

        self.assertIsNone(result)
        self.assertIn("macro.dxy", q.missing_fields)
        freshness = q.feature_freshness["macro.dxy"]
        self.assertEqual(freshness["status"], "missing_after_cutoff")
        self.assertEqual(freshness["ignored_future_observations"], 1)

    def test_macro_scoring_excludes_future_dated_rows(self) -> None:
        snapshot = {
            "date": "2026-06-18",
            "macro": {
                "us_10y_treasury_yield_pct": {"date": "2026-06-19", "value": 3.5},
                "dxy": {"date": "2026-06-19", "value": 96},
                "usd_cny": {"date": "2026-06-19", "value": 6.7},
                "china_10y_government_bond_yield_pct": {"date": "2026-06-19", "value_pct": 1.7},
            },
        }

        result = market_scoring.macro(snapshot)

        self.assertEqual(result["score"], 5.0)
        self.assertIsNone(result["metrics"]["us_10y_yield_pct"]["value"])
        self.assertIsNone(result["metrics"]["dxy"]["value"])
        self.assertIsNone(result["metrics"]["usd_cny"]["value"])
        self.assertIsNone(result["metrics"]["china_10y_yield_pct"]["value"])

    def test_future_dated_macro_rows_emit_scoring_warnings(self) -> None:
        snapshot = {
            "date": "2026-06-18",
            "macro": {
                "dxy": {"date": "2026-06-19", "value": 96},
                "fred_key_indicators": {
                    "FEDFUNDS": {"date": "2026-06-20", "value": 4.5},
                },
            },
        }

        warnings = market_scoring.future_dated_feature_warnings(snapshot)

        self.assertTrue(any("macro.dxy" in warning for warning in warnings))
        self.assertTrue(any("macro.fred_key_indicators.FEDFUNDS" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
