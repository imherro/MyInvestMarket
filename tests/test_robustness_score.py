from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import robustness_score  # noqa: E402


class RobustnessScoreTest(unittest.TestCase):
    def test_unstable_system_scores_below_50(self) -> None:
        score = robustness_score.score_from_components(
            oos_performance=20,
            causal_strength=25,
            stability_score=40,
            stress_test_score=45,
        )

        self.assertLess(score, 50)

    def test_stable_system_scores_above_70(self) -> None:
        score = robustness_score.score_from_components(
            oos_performance=80,
            causal_strength=75,
            stability_score=90,
            stress_test_score=85,
        )

        self.assertGreater(score, 70)

    def test_grade_thresholds(self) -> None:
        self.assertEqual(robustness_score.grade(85), "A-")
        self.assertEqual(robustness_score.grade(72), "B")


if __name__ == "__main__":
    unittest.main()
