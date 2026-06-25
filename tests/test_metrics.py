from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import metrics  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_sharpe_ratio_matches_independent_sample_std_baseline(self) -> None:
        returns = [0.01, -0.02, 0.03, 0.01]
        avg = sum(returns) / len(returns)
        variance = sum((value - avg) ** 2 for value in returns) / (len(returns) - 1)
        expected = avg / math.sqrt(variance) * math.sqrt(metrics.TRADING_DAYS_PER_YEAR)

        self.assertAlmostEqual(metrics.sharpe_ratio(returns), expected, places=12)

    def test_max_drawdown_is_positive_magnitude(self) -> None:
        nav = [1.0, 1.1, 1.0, 1.2, 0.9]

        self.assertAlmostEqual(metrics.max_drawdown(nav), 0.25)
        self.assertGreaterEqual(metrics.max_drawdown(nav), 0)

    def test_performance_summary_contains_required_metrics(self) -> None:
        returns = [0.02, -0.01, 0.03]
        nav = metrics.nav_from_returns(returns)
        summary = metrics.performance_summary(nav, returns, [0.3, 0.5, 0.4])

        for key in ["cagr", "sharpe_ratio", "max_drawdown", "calmar_ratio", "turnover", "win_rate"]:
            self.assertIn(key, summary)
        self.assertAlmostEqual(summary["win_rate"], 2 / 3)

    def test_risk_cap_reduction_effect_measures_high_risk_drawdown_cut(self) -> None:
        rows = [
            {"benchmark_return": -0.10, "strategy_return": -0.02, "baseline_position": 1.0, "risk_penalty_score": 80},
            {"benchmark_return": -0.08, "strategy_return": -0.016, "baseline_position": 1.0, "risk_penalty_score": 75},
            {"benchmark_return": 0.02, "strategy_return": 0.01, "baseline_position": 0.5, "risk_penalty_score": 10},
        ]

        effect = metrics.risk_cap_reduction_effect(rows)

        self.assertEqual(effect["sample_count"], 2)
        self.assertGreaterEqual(effect["drawdown_reduction"], 0.15)


if __name__ == "__main__":
    unittest.main()
