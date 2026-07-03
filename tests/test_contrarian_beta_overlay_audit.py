from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit_contrarian_beta_overlay  # noqa: E402
import market_scoring  # noqa: E402


class ContrarianBetaOverlayAuditTest(unittest.TestCase):
    def test_parameter_audit_passes(self) -> None:
        result = audit_contrarian_beta_overlay.run_audit()

        self.assertTrue(result["passed"])
        self.assertEqual(result["model_version"], market_scoring.MODEL_VERSION)
        self.assertEqual(result["position_policy_version"], market_scoring.POSITION_POLICY_VERSION)
        self.assertEqual(result["parameters"]["valuation_enable_min"], 60)
        self.assertEqual(result["parameters"]["intensity_enable_min"], 55)

    def test_boundary_cases_cover_activation_and_hard_blocks(self) -> None:
        cases = {item["key"]: item for item in audit_contrarian_beta_overlay.audit_cases()}

        self.assertTrue(cases["ideal_deep_bear_repair"]["overlay"]["active"])
        self.assertGreaterEqual(cases["ideal_deep_bear_repair"]["overlay"]["add_score"], 20)
        self.assertFalse(cases["valuation_below_threshold"]["overlay"]["active"])
        self.assertFalse(cases["capital_stampede_guard"]["overlay"]["active"])
        self.assertTrue(
            any("资金踩踏" in item for item in cases["capital_stampede_guard"]["overlay"]["blockers"])
        )
        self.assertFalse(cases["tail_vol_guard"]["overlay"]["active"])
        self.assertTrue(any("尾部风险过高" in item for item in cases["tail_vol_guard"]["overlay"]["blockers"]))

    def test_sensitivity_grid_is_monotonic(self) -> None:
        grid = audit_contrarian_beta_overlay.sensitivity_grid()
        check = audit_contrarian_beta_overlay.monotonic_check(grid)

        self.assertTrue(check["passed"])
        self.assertTrue(any(row["active"] for row in grid))
        self.assertTrue(any(not row["active"] for row in grid))


if __name__ == "__main__":
    unittest.main()
