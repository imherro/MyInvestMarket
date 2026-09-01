from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cycle_engine_state_machine as machine  # noqa: E402


class StateMachineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = json.loads((ROOT / "data/cycle_engine_cycle_state_candidate_v1.json").read_text(encoding="utf-8"))
        cls.candidate_audit = json.loads((ROOT / "data/cycle_engine_cycle_state_candidate_audit_v1.json").read_text(encoding="utf-8"))
        cls.output = json.loads((ROOT / "data/cycle_engine_state_machine_v1.json").read_text(encoding="utf-8"))

    @staticmethod
    def records(states: list[str], macro: str = "positive", fear: int = 20) -> list[dict]:
        result = []
        for index, state in enumerate(states):
            result.append({"month": f"2020-{index + 1:02d}", "basis_trade_date": f"2020-{index + 1:02d}-28", "core_ready": state != "insufficient_history", "candidate_state": state, "reason_codes": [state], "macro_confirmation_state": macro, "macro_alignment": "supportive", "sentiment_overlay": {"state": "normal", "score": fear, "available": True, "observations": 1, "model_ready": False, "role": "overlay_only"}})
        return result

    def test_generated_output_and_audit_pass(self) -> None:
        result = machine.audit(self.output, self.candidate, self.candidate_audit)
        self.assertTrue(result["passed"], result)
        self.assertEqual(self.output["first_core_ready_month"], "2013-03")
        self.assertEqual(self.output["source_candidate_sha256"], machine.FROZEN_PHASE3_CANDIDATE_SHA256)
        self.assertLess(self.output["diagnostics"]["raw_vs_stable"]["stable_monthly_state_change_rate"], self.output["diagnostics"]["raw_vs_stable"]["raw_monthly_state_change_rate"])
        self.assertEqual(self.output["diagnostics"]["ambiguous"]["stable_after_initialization_count"], 0)

    def test_two_hit_confirmation_and_ambiguous_grace(self) -> None:
        rows = machine._step(self.records(["bull", "late_bull", "late_bull"]))
        self.assertEqual([row["stable_state"] for row in rows], ["bull", "bull", "late_bull"])
        self.assertEqual(rows[1]["transition_status"], "pending_started")
        self.assertEqual(rows[2]["transition_status"], "transition_confirmed")
        rows = machine._step(self.records(["bear", "bottoming", "ambiguous", "bottoming"]))
        self.assertEqual(rows[2]["stable_state"], "bear")
        self.assertEqual(rows[3]["stable_state"], "bottoming")
        self.assertEqual(rows[3]["transition_status"], "transition_confirmed")
        self.assertEqual(rows[3]["transition_to"], "bottoming")

    def test_expiry_competition_and_current_state_cancel(self) -> None:
        rows = machine._step(self.records(["bear", "bottoming", "ambiguous", "ambiguous", "bottoming"]))
        self.assertEqual(rows[3]["transition_status"], "pending_expired")
        self.assertEqual(rows[4]["transition_status"], "pending_started")
        rows = machine._step(self.records(["bull", "late_bull", "bear", "bear"]))
        self.assertEqual(rows[2]["transition_status"], "pending_replaced")
        self.assertEqual(rows[2]["pending_target"], "bear")
        rows = machine._step(self.records(["bull", "late_bull", "bull"]))
        self.assertEqual(rows[2]["transition_status"], "held_same")
        self.assertEqual(rows[2]["stable_reason_codes"], ["pending_cancelled_by_current_state"])
        self.assertIsNone(rows[2]["pending_target"])

    def test_pending_cancelled_diagnostic_counts_only_real_cancellations(self) -> None:
        rows = machine._step(self.records(["bull", "bull", "late_bull", "bull"]))
        diagnostics = machine._diagnostics(rows)
        self.assertEqual(diagnostics["pending"]["pending_cancelled_by_current_state_count"], 1)
        self.assertEqual(sum("pending_cancelled_by_current_state" in row["stable_reason_codes"] for row in rows), 1)
        mutated = copy.deepcopy(self.output)
        mutated["diagnostics"]["pending"]["pending_cancelled_by_current_state_count"] += 46
        result = machine.audit(mutated, self.candidate, self.candidate_audit)
        self.assertGreater(result["transition_diagnostics_violation_count"], 0)
        self.assertFalse(result["passed"])

    def test_initialization_and_ambiguous_hold(self) -> None:
        rows = machine._step(self.records(["insufficient_history", "ambiguous", "bull", "ambiguous", "ambiguous"]))
        self.assertEqual(rows[0]["stable_state"], "insufficient_history")
        self.assertFalse(rows[0]["initialized"])
        self.assertEqual(rows[1]["transition_status"], "uninitialized_ambiguous")
        self.assertEqual(rows[2]["transition_status"], "initialized")
        self.assertEqual(rows[3]["stable_state"], "bull")
        self.assertEqual(rows[4]["stable_state"], "bull")
        self.assertEqual(rows[4]["transition_status"], "held_ambiguous")

    def test_macro_and_sentiment_do_not_change_state_machine(self) -> None:
        baseline = machine.build(self.candidate)
        mutated = copy.deepcopy(self.candidate)
        for row in mutated["records"]:
            row["macro_alignment"] = "contradictory"
            row["sentiment_overlay"]["state"] = "extreme_fear"
            row["sentiment_overlay"]["score"] = 100
        changed = machine.build(mutated)
        fields = ("stable_state", "initialized", "transition_status", "transition_from", "transition_to", "pending_target", "pending_count", "pending_gap_months")
        self.assertEqual([[row[field] for field in fields] for row in baseline["records"]], [[row[field] for field in fields] for row in changed["records"]])

    def test_audit_mutations_and_hash_gates(self) -> None:
        cases = (("stable_state", "stable_state_violation_count"), ("pending_target", "pending_state_violation_count"), ("pending_count", "pending_state_violation_count"), ("pending_gap_months", "pending_state_violation_count"), ("transition_from", "transition_metadata_violation_count"))
        for field, counter in cases:
            mutated = copy.deepcopy(self.output)
            row = next(item for item in mutated["records"] if item["core_ready"])
            row[field] = "mutated" if field not in ("pending_count", "pending_gap_months") else 9
            result = machine.audit(mutated, self.candidate, self.candidate_audit)
            self.assertGreater(result[counter], 0, field)
            self.assertFalse(result["passed"])
        candidate_mutation = copy.deepcopy(self.candidate)
        candidate_mutation["records"][0]["candidate_state"] = "bull"
        rebuilt = machine.build(candidate_mutation)
        result = machine.audit(rebuilt, candidate_mutation, self.candidate_audit)
        self.assertGreater(result["source_candidate_hash_violation_count"], 0)
        self.assertFalse(result["passed"])
        failed = machine.audit(self.output, self.candidate, {"passed": False})
        self.assertGreater(failed["source_candidate_audit_violation_count"], 0)
        self.assertFalse(failed["passed"])

    def test_diagnostic_and_future_mutations_are_rejected(self) -> None:
        for path, counter in (("raw_vs_stable", "stability_improvement_violation_count"), ("transitions", "transition_diagnostics_violation_count"), ("pending", "transition_diagnostics_violation_count")):
            mutated = copy.deepcopy(self.output)
            if path == "raw_vs_stable":
                mutated["diagnostics"][path]["stable_monthly_state_change_rate"] += 1
            elif path == "transitions":
                mutated["diagnostics"][path]["confirmed_transition_count"] += 1
            else:
                mutated["diagnostics"][path]["pending_started_count"] += 1
            result = machine.audit(mutated, self.candidate, self.candidate_audit)
            self.assertGreater(result[counter], 0, path)
            self.assertFalse(result["passed"])
        mutated = copy.deepcopy(self.output)
        mutated["records"][0]["diagnostics"] = {"forward_12m": 1}
        result = machine.audit(mutated, self.candidate, self.candidate_audit)
        self.assertGreater(result["future_information_dependency_count"], 0)
        self.assertFalse(result["passed"])

    def test_audit_replay_is_independent_and_output_is_restricted(self) -> None:
        source = inspect.getsource(machine.audit) + inspect.getsource(machine._audit_replay)
        for token in ("build(", "_step(", "state_machine(", "transition_step(", "update_pending("):
            self.assertNotIn(token, source)
        text = json.dumps(self.output, ensure_ascii=False).lower()
        for token in ("cycle_score", "position", "allocation", "buy_signal", "sell_signal", "backtest", "forward_return"):
            self.assertNotIn(token, text)

    def test_candidate_artifact_is_unchanged(self) -> None:
        path = ROOT / "data/cycle_engine_cycle_state_candidate_v1.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), "9764e56c8b094d7d5927964bfdee20ba62efb98da55edbb9a2e50cbfc87e161a")


if __name__ == "__main__":
    unittest.main()
