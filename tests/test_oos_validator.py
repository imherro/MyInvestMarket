from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import oos_validator  # noqa: E402


def oos_records() -> list[dict]:
    start = date(2026, 1, 1)
    close = 100.0
    records = []
    for index in range(90):
        close *= 1.002 if index < 70 else 0.999
        day = (start + timedelta(days=index)).isoformat()
        records.append(
            {
                "run_id": f"run-{index}",
                "basis_trade_date": day,
                "scored_at": f"{day}T15:30:00+08:00",
                "shanghai_composite": close,
                "market_position_score": 70,
                "pre_cap_market_position_score": 75,
                "base_market_position_score": 80,
                "market_regime_code": "expansion",
                "trend_state": "strong_trend",
            }
        )
    return records


class OOSValidatorTest(unittest.TestCase):
    def test_train_validation_test_are_strictly_separated(self) -> None:
        train, validation, test = oos_validator.split_records(oos_records())
        check = oos_validator.leakage_check(train, validation, test)

        self.assertTrue(check["ok"])
        self.assertLess(train[-1]["basis_trade_date"], validation[0]["basis_trade_date"])
        self.assertLess(validation[-1]["basis_trade_date"], test[0]["basis_trade_date"])

    def test_oos_validator_reports_no_future_leakage(self) -> None:
        result = oos_validator.validate_oos(oos_records())

        self.assertTrue(result["available"])
        self.assertTrue(result["leakage_check"]["ok"])
        self.assertIn("oos_sharpe", result)


if __name__ == "__main__":
    unittest.main()
