from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cycle_engine_position_policy as policy  # noqa: E402


class PositionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state_machine = json.loads((ROOT / "data/cycle_engine_state_machine_v1.json").read_text(encoding="utf-8"))
        cls.audit = json.loads((ROOT / "data/cycle_engine_state_machine_audit_v1.json").read_text(encoding="utf-8"))
        cls.output = json.loads((ROOT / "data/cycle_engine_position_policy_v1.json").read_text(encoding="utf-8"))

    def test_all_defined_states_map_to_fixed_ranges(self) -> None:
        states = list(policy.RANGES)
        rows = policy.build({"records": [{"month": f"2020-{i + 1:02d}", "basis_trade_date": "2020-01-31", "stable_state": state} for i, state in enumerate(states)]}, {"passed": True}, "sha") ["records"]
        self.assertEqual([(row["equity_min_pct"], row["equity_max_pct"]) for row in rows], list(policy.RANGES.values()))

    def test_unavailable_states_have_no_range(self) -> None:
        output = policy.build({"records": [{"month": "2010-01", "basis_trade_date": "2010-01-29", "stable_state": "insufficient_history"}, {"month": "2012-01", "basis_trade_date": "2012-01-31", "stable_state": "ambiguous"}]}, {"passed": True}, "sha")
        self.assertEqual(output["records"][0]["equity_min_pct"], None)
        self.assertEqual(output["records"][1]["equity_max_pct"], None)

    def test_failed_state_machine_audit_rejects_generation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "audit did not pass"):
            policy.build({"records": []}, {"passed": False}, "sha")

    def test_current_latest_is_late_bull_60_to_80(self) -> None:
        output = policy.generate()
        self.assertEqual(output["latest"], {"latest_month": "2026-08", "latest_state": "late_bull", "recommended_equity_range": "60%-80%"})
        self.assertEqual(output["record_count"], len(self.state_machine["records"]))

    def test_output_contains_no_unrequested_signal_layers(self) -> None:
        text = json.dumps(self.output, ensure_ascii=False).lower()
        for token in ("score", "etf", "allocation", "buy_signal", "sell_signal"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
