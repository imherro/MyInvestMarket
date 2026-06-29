from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit_allocation_policy_v2  # noqa: E402
import market_scoring  # noqa: E402


class AllocationPolicyV2AuditTest(unittest.TestCase):
    def test_scenario_audit_passes_all_review_cases(self) -> None:
        result = audit_allocation_policy_v2.run_audit()

        self.assertEqual(result["allocation_policy_version"], market_scoring.ALLOCATION_POLICY_VERSION)
        self.assertEqual(result["scenario_count"], 5)
        self.assertTrue(result["passed"])
        self.assertEqual(
            set(result["summary"].keys()),
            {
                "bear_bottom_repair",
                "healthy_impulse_trend",
                "bubble_top",
                "top_rebound",
                "extreme_selloff",
            },
        )

    def test_bubble_and_rebound_do_not_expand_alpha(self) -> None:
        scenarios = {item["key"]: item for item in audit_allocation_policy_v2.run_audit()["scenarios"]}

        self.assertEqual(scenarios["bubble_top"]["sleeve_ranges"]["alpha_active"], "1%-5%")
        self.assertEqual(scenarios["top_rebound"]["sleeve_ranges"]["alpha_active"], "3%-8%")
        self.assertEqual(scenarios["bubble_top"]["sleeve_ranges"]["liquidity"], "60%-80%")
        self.assertEqual(scenarios["top_rebound"]["sleeve_ranges"]["liquidity"], "40%-60%")

    def test_healthy_trend_can_hold_high_risk_assets_but_extreme_selloff_cannot(self) -> None:
        scenarios = {item["key"]: item for item in audit_allocation_policy_v2.run_audit()["scenarios"]}

        self.assertEqual(scenarios["healthy_impulse_trend"]["policy"]["total_risk_asset_range"], "90%-100%")
        self.assertEqual(scenarios["healthy_impulse_trend"]["sleeve_ranges"]["liquidity"], "0%-10%")
        self.assertEqual(scenarios["healthy_impulse_trend"]["sleeve_ranges"]["alpha_active"], "40%-43%")
        self.assertEqual(scenarios["extreme_selloff"]["policy"]["total_risk_asset_range"], "0%-20%")
        self.assertEqual(scenarios["extreme_selloff"]["sleeve_ranges"]["liquidity"], "80%-100%")


if __name__ == "__main__":
    unittest.main()
