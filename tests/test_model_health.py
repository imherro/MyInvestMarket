from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import model_health  # noqa: E402


def health_records(*, drift: bool) -> list[dict]:
    start = date(2026, 1, 1)
    close = 100.0
    records = []
    for index in range(90):
        day = (start + timedelta(days=index)).isoformat()
        if drift and index >= 70:
            close *= 0.99
            regime = "contraction"
            trend = "weakening_trend"
            risk = 85.0
            score = 15.0
        else:
            close *= 1.002
            regime = "expansion"
            trend = "strong_trend"
            risk = 15.0
            score = 80.0
        records.append(
            {
                "run_id": f"run-{index}",
                "basis_trade_date": day,
                "scored_at": f"{day}T15:30:00+08:00",
                "shanghai_composite": close,
                "market_position_score": score,
                "pre_cap_market_position_score": min(score + 10, 100),
                "base_market_position_score": min(score + 15, 100),
                "market_regime_code": regime,
                "trend_state": trend,
                "risk_penalty_score": risk,
                "risk_caps": [{"reason": "test", "score_cap": score}] if risk >= 70 else [],
            }
        )
    return records


class ModelHealthTest(unittest.TestCase):
    def test_high_drift_reduces_health_score(self) -> None:
        stable = model_health.compute_model_health(health_records(drift=False))
        shifted = model_health.compute_model_health(health_records(drift=True))

        self.assertGreater(stable["health_score"], shifted["health_score"])
        self.assertIn(shifted["status"], {"warning", "degraded"})

    def test_high_sharpe_raises_performance_component(self) -> None:
        low = model_health.performance_score({"sharpe_ratio": -1.0, "max_drawdown": 0.2, "win_rate": 0.3})
        high = model_health.performance_score({"sharpe_ratio": 2.0, "max_drawdown": 0.02, "win_rate": 0.7})

        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
