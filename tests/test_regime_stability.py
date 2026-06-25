from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from market_state_stability import validate_regime_persistence, validate_state_stability, validate_trend_continuity  # noqa: E402


def record(run_id: str, trade_date: str, regime: str, trend: str) -> dict:
    return {
        "run_id": run_id,
        "basis_trade_date": trade_date,
        "scored_at": f"{trade_date}T16:00:00+08:00",
        "market_regime_code": regime,
        "trend_state": trend,
    }


class RegimeStabilityTest(unittest.TestCase):
    def test_regime_cycle_allows_adjacent_market_phase_changes(self) -> None:
        records = [
            record("r1", "2026-06-01", "contraction", "weakening_trend"),
            record("r2", "2026-06-02", "accumulation", "early_trend"),
            record("r3", "2026-06-03", "expansion", "strong_trend"),
            record("r4", "2026-06-04", "distribution", "late_trend"),
            record("r5", "2026-06-05", "contraction", "weakening_trend"),
        ]

        result = validate_regime_persistence(records)

        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_regime_cycle_rejects_jump_larger_than_one_phase(self) -> None:
        records = [
            record("r1", "2026-06-01", "accumulation", "early_trend"),
            record("r2", "2026-06-02", "distribution", "late_trend"),
        ]

        result = validate_regime_persistence(records)

        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["field"], "market_regime_code")
        self.assertEqual(result["issues"][0]["distance"], 2)

    def test_trend_continuity_rejects_strong_to_weakening_one_day_jump(self) -> None:
        records = [
            record("r1", "2026-06-01", "expansion", "strong_trend"),
            record("r2", "2026-06-02", "contraction", "weakening_trend"),
        ]

        result = validate_trend_continuity(records)

        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["field"], "trend_state")
        self.assertEqual(result["issues"][0]["distance"], 2)

    def test_combined_state_stability_reports_both_layers(self) -> None:
        records = [
            record("r1", "2026-06-01", "accumulation", "early_trend"),
            record("r2", "2026-06-02", "expansion", "strong_trend"),
        ]

        result = validate_state_stability(records)

        self.assertTrue(result["ok"])
        self.assertTrue(result["regime"]["ok"])
        self.assertTrue(result["trend"]["ok"])


if __name__ == "__main__":
    unittest.main()
