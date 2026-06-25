from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import calibration_trigger  # noqa: E402
from tests.test_model_health import health_records  # noqa: E402


class CalibrationTriggerTest(unittest.TestCase):
    def test_high_drift_triggers_calibration(self) -> None:
        result = calibration_trigger.evaluate_calibration_trigger(health_records(drift=True))

        self.assertTrue(result["trigger"])
        self.assertTrue(result["reason"])
        self.assertTrue(result["suggested_params"])

    def test_stable_model_does_not_trigger_calibration(self) -> None:
        result = calibration_trigger.evaluate_calibration_trigger(health_records(drift=False))

        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], [])
        self.assertEqual(result["suggested_params"], {})


if __name__ == "__main__":
    unittest.main()
