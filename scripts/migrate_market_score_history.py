from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import market_scoring


def run_migration(history_path: Path, *, dry_run: bool = False, archive_duplicates: bool = True) -> dict[str, Any]:
    history = market_scoring.load_history(history_path)
    result = market_scoring.migrate_history_legacy_records(history, archive_duplicates=archive_duplicates)
    if result["changed"] and not dry_run:
        market_scoring.save_history(result["history"], history_path)
    return {
        "history_path": str(history_path),
        "dry_run": dry_run,
        "written": bool(result["changed"] and not dry_run),
        **{key: value for key, value in result.items() if key != "history"},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate MyInvestMarket score history legacy records.")
    parser.add_argument("--history", default=str(market_scoring.DEFAULT_HISTORY_PATH), help="History JSON path.")
    parser.add_argument("--dry-run", action="store_true", help="Report migration changes without writing the file.")
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="Mark legacy records but do not move duplicate legacy records into legacy_archive.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_migration(
        Path(args.history),
        dry_run=args.dry_run,
        archive_duplicates=not args.keep_duplicates,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
