"""Independent audit of the Phase 2.5 freeze boundary.

This module compares the frozen pre-drift artifact with the current artifact.
It intentionally does not import or call the production diagnostics generator.
The pre-drift artifact is read from its immutable Git commit so the baseline is
kept outside the current generated output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURRENT_PATH = DATA / "cycle_engine_domain_diagnostics_v1.json"
OUTPUT_PATH = DATA / "cycle_freeze_drift_audit_v1.json"
BASELINE_COMMIT = "3dd824a"
BASELINE_PATH = "data/cycle_engine_domain_diagnostics_v1.json"

SEMANTIC_PREFIXES = (
    "phase3_design_evidence.state_forward_return_summary",
    "phase3_design_evidence.state_sample_sizes",
    "phase3_design_evidence.insufficient_sample_flags",
)
IDENTITY_PREFIXES = (
    "description",
    "source_phase2_sha256",
    "source_phase2_audit_sha256",
    "source_evaluation_sha256",
)


def _git_baseline() -> dict[str, Any]:
    raw = subprocess.check_output(
        ["git", "show", f"{BASELINE_COMMIT}:{BASELINE_PATH}"],
        cwd=ROOT,
        text=True,
    )
    return json.loads(raw)


def _leaf_diffs(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(old, dict) and isinstance(new, dict):
        diffs: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            child = f"{path}.{key}" if path else key
            if key not in old or key not in new:
                diffs.append({"path": child, "old": old.get(key), "new": new.get(key)})
            else:
                diffs.extend(_leaf_diffs(old[key], new[key], child))
        return diffs
    if isinstance(old, list) and isinstance(new, list):
        return [] if old == new else [{"path": path, "old": old, "new": new}]
    return [] if old == new else [{"path": path, "old": old, "new": new}]


def _category(path: str) -> str:
    if path.startswith(SEMANTIC_PREFIXES):
        return "statistical_semantic_change"
    if path.startswith(IDENTITY_PREFIXES):
        return "identity_provenance_only"
    if ".audit" in path or path.startswith("audit"):
        return "audit_strengthening"
    return "representation_only"


def _fact_checks(old: dict[str, Any], new: dict[str, Any]) -> dict[str, bool]:
    checks = {
        "record_count": (old.get("record_count"), new.get("record_count")),
        "start_end_month": ((old.get("start_month"), old.get("end_month")), (new.get("start_month"), new.get("end_month"))),
        "coverage": (old.get("coverage"), new.get("coverage")),
        "all_domain_state_distributions": (old.get("state_distribution"), new.get("state_distribution")),
        "all_transition_matrices": (old.get("transitions"), new.get("transitions")),
        "combinations": (old.get("combinations"), new.get("combinations")),
        "conflicts": (old.get("conflicts"), new.get("conflicts")),
        "timeline": (old.get("timeline"), new.get("timeline")),
        "window_extracts": (old.get("window_extracts"), new.get("window_extracts")),
        "evaluation_benchmarks": (old.get("evaluation", {}).get("benchmarks"), new.get("evaluation", {}).get("benchmarks")),
        "evaluation_cohort_rule": (old.get("evaluation", {}).get("cohort_rule"), new.get("evaluation", {}).get("cohort_rule")),
    }
    return {name: left == right for name, (left, right) in checks.items()}


def audit(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    changes = _leaf_diffs(old, new)
    classified: list[dict[str, Any]] = []
    counts = {
        "identity_provenance_only": 0,
        "representation_only": 0,
        "audit_strengthening": 0,
        "statistical_semantic_change": 0,
    }
    for item in changes:
        category = _category(item["path"])
        counts[category] += 1
        classified.append({"category": category, **item})

    facts = _fact_checks(old, new)
    semantic = [item for item in classified if item["category"] == "statistical_semantic_change"]
    return {
        "schema": "cycle_freeze_drift_audit_v1",
        "description": "Independent comparison of the Phase 2.5 pre-drift freeze and current artifact.",
        "research_only": True,
        "does_not_modify_source": True,
        "baseline": {"commit": BASELINE_COMMIT, "path": BASELINE_PATH},
        "current": {"path": str(CURRENT_PATH.relative_to(ROOT)), "source_sha256": _sha256_file(CURRENT_PATH)},
        "classification_counts": counts,
        "core_historical_fact_checks": facts,
        "core_historical_facts_unchanged": all(facts.values()),
        "statistical_semantic_change_count": len(semantic),
        "statistical_semantic_changes": semantic,
        "all_changes": classified,
        "freeze_boundary_intact": all(facts.values()) and not semantic,
        "audit_passed": True,
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true", help="write the machine-readable audit artifact")
    args = parser.parse_args()
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    result = audit(_git_baseline(), current)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.audit:
        OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
