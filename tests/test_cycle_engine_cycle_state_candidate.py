from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cycle_engine_cycle_state_candidate as candidate  # noqa: E402


class CycleStateCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.phase2 = json.loads((ROOT / "data/cycle_engine_domain_signals_v1.json").read_text(encoding="utf-8"))
        cls.phase2_audit = json.loads((ROOT / "data/cycle_engine_domain_signals_audit_v1.json").read_text(encoding="utf-8"))
        cls.output = json.loads((ROOT / "data/cycle_engine_cycle_state_candidate_v1.json").read_text(encoding="utf-8"))

    @staticmethod
    def source(valuation: str, earnings: str, trend: str, macro: str = "positive", ready: bool = True) -> dict:
        return {
            "month": "2020-01", "basis_trade_date": "2020-01-31",
            "valuation": {"state": valuation, "ready": ready},
            "earnings": {"state": earnings, "ready": ready},
            "trend": {"state": trend, "ready": ready},
            "macro_confirmation": {"state": macro, "ready": True},
            "sentiment_overlay": {"state": "normal", "score": 20, "available": True, "observations": 1, "model_ready": False, "role": "overlay_only"},
        }

    def test_generated_output_and_audit_pass(self) -> None:
        result = candidate.audit(self.output, self.phase2, self.phase2_audit)
        self.assertTrue(result["passed"], result)
        self.assertEqual(self.output["record_count"], 200)
        self.assertEqual(self.output["first_core_ready_month"], "2013-03")
        self.assertEqual(self.output["source_phase2_sha256"], candidate.FROZEN_PHASE2_DOMAIN_SIGNALS_SHA256)

    def test_precedence_and_core_readiness(self) -> None:
        cases = (
            ("cheap", "deterioration", "damaged", "deep_bear"),
            ("cheap", "recovery", "mixed", "bottoming"),
            ("neutral", "bottoming", "bottoming", "bottoming"),
            ("expensive", "deterioration", "extended", "distribution"),
            ("expensive", "recovery", "extended", "late_bull"),
            ("neutral", "recovery", "up", "early_bull"),
            ("neutral", "mixed", "damaged", "bear"),
            ("neutral", "mixed", "up", "bull"),
            ("neutral", "mixed", "mixed", "ambiguous"),
        )
        for valuation, earnings, trend, expected in cases:
            state, _ = candidate.candidate_state(self.source(valuation, earnings, trend))
            self.assertEqual(state, expected)
        state, _ = candidate.candidate_state(self.source("cheap", "deterioration", "damaged", ready=False))
        self.assertEqual(state, "insufficient_history")

    def test_macro_is_confirmation_only(self) -> None:
        for macro in ("positive", "negative", "mixed", "insufficient_data"):
            source = self.source("neutral", "recovery", "up", macro)
            self.assertEqual(candidate.candidate_state(source)[0], "early_bull")
            self.assertEqual(candidate.macro_alignment("early_bull", macro), "supportive" if macro == "positive" else ("contradictory" if macro == "negative" else "neutral"))
        source = self.source("cheap", "deterioration", "damaged", "positive")
        self.assertEqual(candidate.candidate_state(source)[0], "deep_bear")
        self.assertEqual(candidate.macro_alignment("deep_bear", "positive"), "contradictory")

    def test_a_fear_cannot_change_candidate_state(self) -> None:
        before = copy.deepcopy(self.phase2)
        after = copy.deepcopy(self.phase2)
        for row in after["records"]:
            item = row["sentiment_overlay"]
            item["state"], item["score"] = "extreme_fear", 100
        left = candidate.build(before)
        right = candidate.build(after)
        self.assertEqual([row["candidate_state"] for row in left["records"]], [row["candidate_state"] for row in right["records"]])

    def test_future_phase2_mutation_does_not_change_prior_candidate_semantics(self) -> None:
        mutated = copy.deepcopy(self.phase2)
        for row in mutated["records"]:
            if row["month"] > "2025-12":
                row["macro_confirmation"]["state"] = "negative"
                row["sentiment_overlay"]["state"] = "extreme_fear"
        original = candidate.build(self.phase2)
        changed = candidate.build(mutated)
        cutoff = "2025-12"
        self.assertEqual(
            [(row["month"], row["candidate_state"]) for row in original["records"] if row["month"] <= cutoff],
            [(row["month"], row["candidate_state"]) for row in changed["records"] if row["month"] <= cutoff],
        )

    def test_mutations_of_candidate_states_fail_independent_audit(self) -> None:
        for state in ("deep_bear", "bottoming", "distribution", "late_bull", "early_bull", "bear", "bull", "ambiguous"):
            mutated = copy.deepcopy(self.output)
            row = next((item for item in mutated["records"] if item["candidate_state"] == state), None)
            if row is None:
                continue
            row["candidate_state"] = "bull" if state != "bull" else "bear"
            result = candidate.audit(mutated, self.phase2, self.phase2_audit)
            self.assertGreater(result["candidate_rule_violation_count"], 0, state)
            self.assertFalse(result["passed"])

    def test_hash_and_upstream_gates_reject_mutated_phase2(self) -> None:
        mutated = copy.deepcopy(self.phase2)
        mutated["records"][0]["valuation"]["state"] = "expensive"
        rebuilt = candidate.build(mutated)
        result = candidate.audit(rebuilt, mutated, self.phase2_audit)
        self.assertGreater(result["source_phase2_hash_violation_count"], 0)
        self.assertGreater(result["upstream_mutation_count"], 0)
        self.assertFalse(result["passed"])
        failed = candidate.audit(self.output, self.phase2, {"passed": False})
        self.assertGreater(failed["source_phase2_audit_violation_count"], 0)
        self.assertFalse(failed["passed"])

    def test_audit_replay_does_not_call_formal_reducers(self) -> None:
        source = inspect.getsource(candidate.audit) + inspect.getsource(candidate._audit_replay_record)
        for name in ("build(", "candidate_state(", "macro_alignment(", "rules = _rule_matches("):
            self.assertNotIn(name, source)
        module_source = inspect.getsource(candidate)
        for name in ("cycle_engine_domain_diagnostics", "cycle_engine_evaluation_targets", "cycle_engine_nonoverlap_diagnostics"):
            self.assertNotIn(name, module_source)

    def test_output_has_no_numeric_score_or_execution_fields(self) -> None:
        text = json.dumps(self.output, ensure_ascii=False).lower()
        for token in ("cycle_score", "bull_bear_score", "market_score", "position", "allocation", "buy_signal", "sell_signal"):
            self.assertNotIn(token, text)
        self.assertTrue(self.output["research_only"])
        self.assertEqual(set(row["candidate_state"] for row in self.output["records"]) - candidate.ALLOWED_CANDIDATES, set())


if __name__ == "__main__":
    unittest.main()
