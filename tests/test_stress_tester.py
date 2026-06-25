from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stress_tester  # noqa: E402


class StressTesterTest(unittest.TestCase):
    def test_stress_test_is_deterministic_under_seed(self) -> None:
        first = stress_tester.run_stress_tests(seed=123)
        second = stress_tester.run_stress_tests(seed=123)

        self.assertEqual(first, second)

    def test_extreme_regimes_trigger_stress_flags(self) -> None:
        result = stress_tester.run_stress_tests(seed=123)

        self.assertTrue(result["scenarios"]["extreme_bear"]["triggered"])
        self.assertTrue(result["scenarios"]["liquidity_crisis"]["triggered"])
        self.assertGreater(result["max_drawdown"], 0)


if __name__ == "__main__":
    unittest.main()
