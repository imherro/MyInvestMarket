"""Map the frozen cycle state to a stock-account equity range."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATE_MACHINE_PATH = DATA / "cycle_engine_state_machine_v1.json"
STATE_MACHINE_AUDIT_PATH = DATA / "cycle_engine_state_machine_audit_v1.json"
OUTPUT_PATH = DATA / "cycle_engine_position_policy_v1.json"

RANGES = {
    "deep_bear": (20, 40),
    "bottoming": (40, 60),
    "early_bull": (70, 90),
    "bull": (80, 100),
    "late_bull": (60, 80),
    "distribution": (30, 50),
    "bear": (0, 20),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _range_text(bounds: tuple[int, int]) -> str:
    return f"{bounds[0]}%-{bounds[1]}%"


def _policy_row(row: dict[str, Any]) -> dict[str, Any]:
    state = row["stable_state"]
    bounds = RANGES.get(state)
    if bounds is None:
        reason = "insufficient_history" if state == "insufficient_history" else "ambiguous_state_no_defined_range"
        return {
            "month": row["month"],
            "basis_trade_date": row["basis_trade_date"],
            "stable_state": state,
            "equity_min_pct": None,
            "equity_max_pct": None,
            "policy_reason": reason,
        }
    return {
        "month": row["month"],
        "basis_trade_date": row["basis_trade_date"],
        "stable_state": state,
        "equity_min_pct": bounds[0],
        "equity_max_pct": bounds[1],
        "policy_reason": f"stable_state_{state}",
    }


def build(state_machine: dict[str, Any], audit: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    if audit.get("passed") is not True:
        raise RuntimeError("Phase 3.1 State Machine audit did not pass")
    rows = [_policy_row(row) for row in state_machine["records"]]
    latest = rows[-1] if rows else None
    return {
        "schema": "cycle_engine_position_policy_v1",
        "description": "Research-only stock-account equity range mapped from the frozen stable cycle state.",
        "research_only": True,
        "source_state_machine_sha256": source_sha256,
        "record_count": len(rows),
        "records": rows,
        "latest": {
            "latest_month": latest["month"] if latest else None,
            "latest_state": latest["stable_state"] if latest else None,
            "recommended_equity_range": _range_text((latest["equity_min_pct"], latest["equity_max_pct"])) if latest and latest["equity_min_pct"] is not None else None,
        },
    }


def generate() -> dict[str, Any]:
    state_machine = json.loads(STATE_MACHINE_PATH.read_text(encoding="utf-8"))
    audit = json.loads(STATE_MACHINE_AUDIT_PATH.read_text(encoding="utf-8"))
    return build(state_machine, audit, _sha256(STATE_MACHINE_PATH))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    output = generate()
    if args.generate:
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["latest"], ensure_ascii=False))


if __name__ == "__main__":
    main()
