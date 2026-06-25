from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import causal_analysis  # noqa: E402


def causal_rows() -> list[dict]:
    rows = []
    for index in range(50):
        rows.append({"strategy_return": 0.01 + index * 0.0001, "market_regime": "expansion", "trend_state": "strong_trend"})
    for index in range(50):
        rows.append({"strategy_return": -0.008 - index * 0.0001, "market_regime": "contraction", "trend_state": "weakening_trend"})
    return rows


class CausalAnalysisTest(unittest.TestCase):
    def test_regime_permutation_changes_effect_strength(self) -> None:
        rows = causal_rows()
        observed = causal_analysis.effect_strength(rows, "market_regime")
        shuffled = causal_analysis.effect_strength(causal_analysis.shuffle_labels(rows, "market_regime", seed=7), "market_regime")

        self.assertGreater(observed, shuffled)

    def test_random_labels_have_near_zero_causal_effect(self) -> None:
        rows = [
            {"strategy_return": 0.01 if index % 2 == 0 else -0.01, "market_regime": "expansion" if index % 2 == 0 else "contraction"}
            for index in range(100)
        ]
        shuffled = causal_analysis.shuffle_labels(rows, "market_regime", seed=11)

        self.assertLess(causal_analysis.effect_strength(shuffled, "market_regime"), 0.05)

    def test_analysis_outputs_required_fields(self) -> None:
        result = causal_analysis.analyze_causal_impact(rows=causal_rows(), permutations=20)

        self.assertTrue(result["available"])
        self.assertIn("regime_causal_effect", result)
        self.assertIn("risk_causal_reduction", result)


if __name__ == "__main__":
    unittest.main()
