from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backtest_engine  # noqa: E402
import metrics  # noqa: E402


def synthetic_records() -> list[dict]:
    rows = [
        ("2026-01-01", 100.0, 20.0, "expansion", "strong_trend", 10.0),
        ("2026-01-02", 102.0, 40.0, "expansion", "strong_trend", 15.0),
        ("2026-01-03", 101.0, 30.0, "distribution", "late_trend", 55.0),
        ("2026-01-04", 98.0, 10.0, "contraction", "weakening_trend", 80.0),
        ("2026-01-05", 94.0, 25.0, "contraction", "weakening_trend", 70.0),
    ]
    records = []
    for idx, (day, close, score, regime, trend, risk) in enumerate(rows):
        records.append(
            {
                "run_id": f"run-{idx}",
                "scored_at": f"{day}T15:30:00+08:00",
                "basis_trade_date": day,
                "shanghai_composite": close,
                "market_position_score": score,
                "pre_cap_market_position_score": min(score + 20, 100),
                "base_market_position_score": min(score + 25, 100),
                "market_regime_code": regime,
                "trend_state": trend,
                "risk_penalty_score": risk,
                "risk_caps": [{"reason": "test", "score_cap": score}] if risk >= 70 else [],
            }
        )
    return records


class BacktestEngineTest(unittest.TestCase):
    def test_backtest_is_deterministic(self) -> None:
        records = synthetic_records()

        first = backtest_engine.run_backtest(records)
        second = backtest_engine.run_backtest(copy.deepcopy(records))

        self.assertEqual(first["nav_curve"], second["nav_curve"])
        self.assertEqual(first["returns"], second["returns"])
        self.assertTrue(first["lookahead_safe"])

    def test_position_is_shifted_by_one_bar(self) -> None:
        result = backtest_engine.run_backtest(synthetic_records())
        first_return = result["returns"][0]
        expected_return = (102.0 / 100.0 - 1) * 0.20

        self.assertEqual(result["signal_delay_bars"], 1)
        self.assertEqual(first_return["source_signal_date"], "2026-01-01")
        self.assertEqual(first_return["date"], "2026-01-02")
        self.assertAlmostEqual(first_return["strategy_return"], expected_return)

    def test_zero_delay_is_rejected_to_prevent_lookahead(self) -> None:
        with self.assertRaises(ValueError):
            backtest_engine.run_backtest(synthetic_records(), signal_delay_bars=0)

    def test_regime_alpha_contribution(self) -> None:
        result = backtest_engine.run_backtest(synthetic_records())
        contribution = metrics.regime_hit_return_map(result["returns"])

        self.assertGreater(contribution["expansion"]["avg_return"], contribution["contraction"]["avg_return"])

    def test_trend_alpha_contribution(self) -> None:
        result = backtest_engine.run_backtest(synthetic_records())
        contribution = metrics.trend_state_alpha_contribution(result["returns"])["by_trend_state"]

        self.assertGreater(contribution["strong_trend"]["avg_return"], contribution["weakening_trend"]["avg_return"])


if __name__ == "__main__":
    unittest.main()
