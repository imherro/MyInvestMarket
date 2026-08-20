from __future__ import annotations

import math
import tempfile
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a_fear  # noqa: E402
import build_a_fear_dataset  # noqa: E402


def option_rows(prefix: str, maturity: str, days: int, volatility: float) -> list[dict]:
    forward = 4000.0
    strike = 4000.0
    years = days / 365
    rate = 0.015
    return [
        {
            "ts_code": f"{prefix}-{maturity}-{call_put}",
            "call_put": call_put,
            "exercise_price": strike,
            "maturity_date": maturity,
            "settle": a_fear.black76_price(forward, strike, years, rate, volatility, call_put),
            "close": None,
            "oi": 100,
        }
        for call_put in ("C", "P")
    ]


class BuildAFearDatasetTests(unittest.TestCase):
    def test_family_iv_interpolates_to_fixed_30_days(self) -> None:
        basis = date(2026, 8, 1)
        rows = option_rows("IO", "20260821", 20, 0.20) + option_rows("IO", "20260910", 40, 0.30)
        result = build_a_fear_dataset.fixed_30d_family_iv(pd.DataFrame(rows), "IO", basis, 0.015)
        expected_variance = (0.20**2 * 20 / 365 + 0.30**2 * 40 / 365) / 2
        expected = math.sqrt(expected_variance / (30 / 365))
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["iv_30d"], expected, places=7)
        self.assertEqual(len(result["expiry_evidence"]), 2)

    def test_rate_uses_latest_observation_at_or_before_trade_date(self) -> None:
        frame = pd.DataFrame(
            [
                {"date": "20260801", "1m": 1.4},
                {"date": "20260805", "1m": 1.5},
                {"date": "20260810", "1m": 1.6},
            ]
        )
        rate, source_date, fallback = build_a_fear_dataset.rate_at_or_before(frame, "20260806")
        self.assertEqual(source_date, "20260805")
        self.assertAlmostEqual(rate, 0.015)
        self.assertFalse(fallback)

    def test_bootstrap_rebuild_is_explicit(self) -> None:
        original = {
            "version": a_fear.VERSION,
            "basis_trade_date": "2026-08-19",
            "input_hash": "old",
            "confidence": "medium",
        }
        replacement = {**original, "input_hash": "new", "fear_score": 80}
        with tempfile.TemporaryDirectory() as temp_dir:
            history = Path(temp_dir) / "history.json"
            latest = Path(temp_dir) / "latest.json"
            build_a_fear_dataset.write_json(
                history,
                {"schema_version": 1, "version": a_fear.VERSION, "records": [original]},
            )
            with self.assertRaises(RuntimeError):
                build_a_fear_dataset.merge_scored_history([replacement], history, latest)
            result = build_a_fear_dataset.merge_scored_history(
                [replacement], history, latest, bootstrap_rebuild=True
            )
        self.assertEqual(result["latest"]["input_hash"], "new")


if __name__ == "__main__":
    unittest.main()
