from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a_fear  # noqa: E402


def observation(day: date, value: float, include_iv: bool = True) -> dict:
    return {
        "basis_trade_date": day.isoformat(),
        "implied_volatility": {
            "io_iv_30d": 0.15 + value / 1000 if include_iv else None,
            "mo_iv_30d": 0.20 + value / 1000 if include_iv else None,
        },
        "downside_volatility": {
            "csi300_20d": 0.10 + value / 1000,
            "csi1000_20d": 0.15 + value / 1000,
        },
        "market_breadth": {
            "decliner_ratio": value / 100,
            "decline_beyond_3pct_ratio": value / 200,
            "limit_down_ratio": value / 1000,
        },
        "tail_loss": {
            "csi300_loss_1d": value / 100,
            "csi300_loss_5d": value / 80,
            "csi1000_loss_1d": value / 90,
            "csi1000_loss_5d": value / 70,
        },
        "source_dates": {"market": day.isoformat()},
        "data_quality": {"warnings": []},
    }


class AFearMathTests(unittest.TestCase):
    def test_black76_solver_recovers_input_volatility(self) -> None:
        expected = 0.2875
        price = a_fear.black76_price(4000, 4050, 30 / 365, 0.015, expected, "P")
        actual = a_fear.implied_volatility_black76(price, 4000, 4050, 30 / 365, 0.015, "P")
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual, expected, places=7)

    def test_total_variance_interpolation_is_continuous(self) -> None:
        expected_variance = (0.20**2 * 20 / 365 + 0.30**2 * 40 / 365) / 2
        expected = math.sqrt(expected_variance / (30 / 365))
        self.assertAlmostEqual(
            a_fear.interpolate_fixed_maturity_iv([(20, 0.20), (40, 0.30)]),
            expected,
            places=10,
        )

    def test_downside_volatility_ignores_upside_squares(self) -> None:
        result = a_fear.downside_volatility([0.02, -0.01, 0.03, -0.02])
        expected = math.sqrt(252 * (0.01**2 + 0.02**2) / 4)
        self.assertAlmostEqual(result, expected)


class AFearScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        start = date(2025, 1, 1)
        self.observations = [observation(start + timedelta(days=index), float(index + 1)) for index in range(12)]

    def test_percentile_does_not_use_future_observations(self) -> None:
        target = self.observations[5]
        score_with_future = a_fear.score_observation(target, self.observations, minimum_sample=3)
        score_without_future = a_fear.score_observation(target, self.observations[:6], minimum_sample=3)
        self.assertEqual(score_with_future["fear_score"], score_without_future["fear_score"])
        self.assertEqual(
            score_with_future["metrics"]["io_iv_30d"]["sample_count"],
            6,
        )

    def test_missing_both_iv_families_publishes_proxy_only(self) -> None:
        missing = [observation(date(2025, 2, 1) + timedelta(days=index), float(index + 1), include_iv=False) for index in range(6)]
        record = a_fear.score_observation(missing[-1], missing, minimum_sample=3)
        self.assertFalse(record["official"])
        self.assertIsNone(record["fear_score"])
        self.assertIsNotNone(record["realized_fear_proxy"])
        self.assertEqual(record["confidence"], "low")

    def test_zero_tail_loss_has_zero_percentile(self) -> None:
        values = [observation(date(2025, 3, 1) + timedelta(days=index), float(index + 1)) for index in range(5)]
        values[-1]["tail_loss"] = {
            "csi300_loss_1d": 0,
            "csi300_loss_5d": 0,
            "csi1000_loss_1d": 0,
            "csi1000_loss_5d": 0,
        }
        record = a_fear.score_observation(values[-1], values, minimum_sample=3)
        self.assertEqual(record["components"]["tail_loss"]["score"], 0)

    def test_series_calculates_changes(self) -> None:
        records = a_fear.score_observation_series(self.observations, minimum_sample=3)
        self.assertIsNotNone(records[-1]["change_1d"])
        self.assertIsNotNone(records[-1]["change_3d"])


class AFearPersistenceTests(unittest.TestCase):
    def test_same_day_is_deduplicated_and_conflict_is_not_overwritten(self) -> None:
        observations = [observation(date(2025, 4, 1) + timedelta(days=index), float(index + 1)) for index in range(4)]
        record = a_fear.score_observation(observations[-1], observations, minimum_sample=3)
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "history.json"
            latest_path = Path(temp_dir) / "latest.json"
            first = a_fear.append_record(record, history_path, latest_path)
            duplicate = a_fear.append_record(record, history_path, latest_path)
            changed = json.loads(json.dumps(record))
            changed["input_hash"] = "different"
            conflict = a_fear.append_record(changed, history_path, latest_path)
            saved = a_fear.load_history(history_path)

        self.assertTrue(first["appended"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(len(saved["records"]), 1)


if __name__ == "__main__":
    unittest.main()
