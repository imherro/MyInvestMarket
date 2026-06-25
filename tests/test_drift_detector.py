from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import drift_detector  # noqa: E402


def regime_records(*, stable: bool) -> list[dict]:
    start = date(2026, 1, 1)
    records = []
    for index in range(90):
        day = (start + timedelta(days=index)).isoformat()
        if stable:
            regime = "expansion" if index % 2 == 0 else "accumulation"
            trend = "strong_trend" if index % 2 == 0 else "early_trend"
            risk = 15.0
        else:
            regime = "expansion" if index < 70 else "contraction"
            trend = "strong_trend" if index < 70 else "weakening_trend"
            risk = 15.0 if index < 70 else 85.0
        records.append(
            {
                "basis_trade_date": day,
                "scored_at": f"{day}T15:30:00+08:00",
                "market_regime_code": regime,
                "trend_state": trend,
                "risk_penalty_score": risk,
            }
        )
    return records


class DriftDetectorTest(unittest.TestCase):
    def test_stable_regime_has_low_drift(self) -> None:
        result = drift_detector.detect_drift(regime_records(stable=True), recent_window=20)

        self.assertTrue(result["available"])
        self.assertLess(result["drift_score"], 30)
        self.assertEqual(result["severity"], "low")

    def test_synthetic_shift_has_high_drift(self) -> None:
        result = drift_detector.detect_drift(regime_records(stable=False), recent_window=20)

        self.assertTrue(result["available"])
        self.assertGreater(result["drift_score"], 60)
        self.assertEqual(result["severity"], "high")
        self.assertIn("regime", result["drift_type"])
        self.assertIn("risk", result["drift_type"])


if __name__ == "__main__":
    unittest.main()
