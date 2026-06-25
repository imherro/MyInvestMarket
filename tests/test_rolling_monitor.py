from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rolling_monitor  # noqa: E402


class RollingMonitorTest(unittest.TestCase):
    def test_rolling_sharpe_series_has_one_value_per_return(self) -> None:
        returns = [0.01, 0.02, -0.005, 0.01, -0.003]
        series = rolling_monitor.rolling_sharpe_series(returns, 3)

        self.assertEqual(len(series), len(returns))
        self.assertTrue(all(math.isfinite(value) for value in series))

    def test_monitor_backtest_detects_sharpe_decay_consistently(self) -> None:
        rows = [
            {"strategy_return": 0.018 + (index % 3) * 0.002, "market_regime": "expansion"}
            for index in range(40)
        ]
        rows.extend(
            {"strategy_return": -0.01 - (index % 3) * 0.001, "market_regime": "distribution"}
            for index in range(20)
        )
        result = rolling_monitor.monitor_backtest({"returns": rows})

        self.assertTrue(result["available"])
        self.assertLess(result["rolling_sharpe_20d"], result["rolling_sharpe_60d"])
        self.assertTrue(result["sharpe_decay"])


if __name__ == "__main__":
    unittest.main()
