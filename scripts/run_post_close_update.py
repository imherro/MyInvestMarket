from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import build_market_dataset
import market_scoring


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
PORT = 8011
VERIFY_ENDPOINTS = [
    "/api/index",
    "/api/research/latest/market-score",
    "/api/research/latest/market-analysis",
]


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def git_output(args: list[str]) -> str:
    return run_command(["git", *args]).stdout.strip()


def git_status() -> str:
    return git_output(["status", "--porcelain"])


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stable_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    # Post-close automation should not append a new score just because intraday
    # macro supplements or generated_at changed after the same A-share session.
    core_keys = [
        "date",
        "market",
        "breadth",
        "capital_flow",
        "sector_rotation",
        "valuation",
        "volatility",
    ]
    return {key: copy.deepcopy(snapshot.get(key)) for key in core_keys}


def stable_fingerprint(snapshot: dict[str, Any] | None) -> str | None:
    stable = stable_snapshot(snapshot)
    if stable is None:
        return None
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_snapshot(snapshot: dict[str, Any]) -> tuple[Path, Path, bytes]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = DATA_DIR / f"market_snapshot_{snapshot['date']}.json"
    latest_path = DATA_DIR / "latest_market_snapshot.json"
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    payload_bytes = payload.encode("utf-8")
    dated_path.write_bytes(payload_bytes)
    latest_path.write_bytes(payload_bytes)
    return dated_path, latest_path, payload_bytes


def latest_record(history: dict[str, Any] | None) -> dict[str, Any] | None:
    records = (history or {}).get("records", [])
    if not isinstance(records, list) or not records:
        return None
    return sorted(records, key=lambda row: str(row.get("scored_at", "")))[-1]


def append_score(snapshot: dict[str, Any], snapshot_path: Path, snapshot_bytes: bytes) -> dict[str, Any]:
    record = market_scoring.score_snapshot(snapshot, snapshot_path=snapshot_path, snapshot_bytes=snapshot_bytes)
    return market_scoring.append_score_record(record, market_scoring.DEFAULT_HISTORY_PATH)


def fmt(value: Any, default: str = "--") -> str:
    if value is None:
        return default
    return str(value)


def module_rows(record: dict[str, Any]) -> str:
    rows = ["| 模块 | 得分 |", "|---|---:|"]
    modules = record.get("modules", {}) or {}
    for module in modules.values():
        if not isinstance(module, dict):
            continue
        rows.append(f"| {module.get('label')} | {fmt(module.get('score'))} / {fmt(module.get('weight'))} |")
    return "\n".join(rows)


def crowding_rows(record: dict[str, Any]) -> str:
    items = ((record.get("crowding", {}) or {}).get("items", []) or [])
    if not items:
        return "- 暂无显著拥挤惩罚。"
    lines = []
    for item in items:
        lines.append(f"- {item.get('label')}，扣 {fmt(item.get('penalty'))}：{item.get('basis')}")
    return "\n".join(lines)


def top_industry_lines(snapshot: dict[str, Any], key: str) -> str:
    rows = ((snapshot.get("sector_rotation", {}) or {}).get(key, []) or [])[:5]
    if not rows:
        return "- 暂无可用行业数据。"
    lines = []
    for idx, row in enumerate(rows, start=1):
        if key.endswith("return"):
            detail = f"{fmt(row.get('pct_change'))}%"
        else:
            detail = f"{fmt(row.get('net_amount_100m_cny'))} 亿元"
        lines.append(f"{idx}. {row.get('industry')} {detail}")
    return "\n".join(lines)


def write_report(snapshot: dict[str, Any], record: dict[str, Any]) -> Path:
    now = datetime.now(TZ)
    report_path = DATA_DIR / f"chatgpt_market_analysis_{now.strftime('%Y%m%d_%H%M%S')}.md"
    valuation_score = (((snapshot.get("valuation", {}) or {}).get("market", {}) or {}).get("valuation_score"))
    realized_vol = (((snapshot.get("volatility", {}) or {}).get("market", {}) or {}).get("realized_vol_30d"))
    breadth = snapshot.get("breadth", {}) or {}
    content = f"""# A股市场研究结果

- 生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}
- 数据基准日: {record.get('basis_trade_date')}
- 输入数据: `data/latest_market_snapshot.json`
- 评分模型: `{record.get('model_version')}`

---

## 结论

当前市场状态为“{record.get('market_regime')}”。模型按股票账户口径输出官方推荐权益仓位；波动率只用于风险扣分、风险上限和提示，不再按8%年化目标波动率缩放股票账户仓位。

## 评分摘要

| 项目 | 数值 |
|---|---:|
| 市场机会分 | {fmt(record.get('market_opportunity_score'))} |
| 拥挤惩罚 | {fmt(record.get('crowding_penalty'))} |
| 扣上限前仓位分 | {fmt(record.get('pre_cap_market_position_score'))} |
| 股票账户仓位分 | {fmt(record.get('market_position_score'))} |
| 官方推荐权益区间 | {fmt(record.get('recommended_equity_position_range') or record.get('base_equity_position_range') or record.get('equity_position_range'))} |
| 风险上限数量 | {len(record.get('risk_caps', []) or [])} |
| 仓位策略版本 | {record.get('position_policy_version')} |
| 市场状态 | {record.get('market_regime')} |
| 置信度 | {record.get('confidence')} |

{module_rows(record)}

## 本次关键证据

- 上涨家数 `{fmt(breadth.get('advancers'))}`，下跌家数 `{fmt(breadth.get('decliners'))}`，个股中位数涨跌 `{fmt(breadth.get('median_pct_change'))}%`。
- 估值便宜度 `{fmt(valuation_score)}%`，30日年化波动率 `{fmt(round(realized_vol * 100, 2) if isinstance(realized_vol, (int, float)) else None)}%`。
- 北向净流入 `{fmt((snapshot.get('capital_flow', {}) or {}).get('northbound_net_inflow_100m_cny'))}` 亿元，主力净流入 `{fmt((snapshot.get('capital_flow', {}) or {}).get('main_net_inflow_100m_cny'))}` 亿元。

## 主线方向

涨幅靠前行业：

{top_industry_lines(snapshot, 'top5_industries_by_return')}

资金流入靠前行业：

{top_industry_lines(snapshot, 'top5_industries_by_capital_inflow')}

## 拥挤与风险

{crowding_rows(record)}

## 执行观察

后续重点观察宽度是否修复、主力资金是否收敛、估值分位是否回到中性区间，以及波动率是否下降。宽度和资金未修复前，只承认结构性机会，不把指数强势直接视为全面扩仓信号。
"""
    report_path.write_text(content, encoding="utf-8")
    return report_path


def endpoint_json(path: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:{PORT}{path}"
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def ensure_server() -> None:
    try:
        endpoint_json("/api/index")
        return
    except Exception:
        pass

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_market_web.py")],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.time() + 20
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            endpoint_json("/api/index")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"8011 service did not become ready: {last_error}")


def verify_api() -> dict[str, Any]:
    ensure_server()
    result: dict[str, Any] = {}
    for path in VERIFY_ENDPOINTS:
        payload = endpoint_json(path)
        result[path] = {
            "ok": True,
            "available": payload.get("available") if isinstance(payload, dict) else None,
        }
    return result


def commit_and_push(paths: list[Path], trade_date: str, no_git: bool) -> dict[str, Any]:
    if no_git:
        return {"skipped": True, "reason": "--no-git"}

    rel_paths = [str(path.relative_to(ROOT)) for path in paths]
    run_command(["git", "add", "--", *rel_paths])
    staged = run_command(["git", "diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return {"skipped": True, "reason": "no staged changes"}

    message = f"Update market score for {trade_date}"
    run_command(["git", "commit", "-m", message])
    run_command(["git", "push", "origin", "main"])
    head = git_output(["rev-parse", "HEAD"])
    origin = git_output(["rev-parse", "origin/main"])
    remote = git_output(["ls-remote", "origin", "refs/heads/main"]).split()[0]
    return {
        "skipped": False,
        "commit": head,
        "verified": head == origin == remote,
        "origin_main": origin,
        "remote_main": remote,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the idempotent post-close MyInvestMarket update.")
    parser.add_argument("--as-of", default=datetime.now(TZ).strftime("%Y-%m-%d"), help="Calendar date, YYYY-MM-DD.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow running when the Git worktree is dirty.")
    parser.add_argument("--force-score", action="store_true", help="Append a new score even when the stable snapshot fingerprint is unchanged.")
    parser.add_argument("--no-git", action="store_true", help="Do not commit or push generated changes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    initial_status = git_status()
    if initial_status and not args.allow_dirty:
        raise RuntimeError("Git worktree is dirty before update; rerun after committing/stashing or pass --allow-dirty for manual testing.")

    build_market_dataset.load_dotenv(ROOT / ".env")
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    old_snapshot = load_json(DATA_DIR / "latest_market_snapshot.json")
    old_fingerprint = stable_fingerprint(old_snapshot)
    snapshot = build_market_dataset.build_dataset(as_of)
    new_fingerprint = stable_fingerprint(snapshot)
    trade_date = snapshot.get("date")

    history = market_scoring.load_history(market_scoring.DEFAULT_HISTORY_PATH)
    last = latest_record(history)
    same_trade_date = bool(last and last.get("basis_trade_date") == trade_date)
    unchanged = same_trade_date and old_fingerprint == new_fingerprint

    result: dict[str, Any] = {
        "basis_trade_date": trade_date,
        "model_version": market_scoring.MODEL_VERSION,
        "same_trade_date_as_latest_score": same_trade_date,
        "stable_market_snapshot_unchanged": unchanged,
    }

    if unchanged and not args.force_score:
        result["status"] = "skipped"
        result["reason"] = "latest complete trading day and stable snapshot are unchanged"
        result["api"] = verify_api()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    dated_path, latest_path, snapshot_bytes = write_snapshot(snapshot)
    score_result = append_score(snapshot, latest_path, snapshot_bytes)
    record = score_result["record"]
    report_path = write_report(snapshot, record)
    api = verify_api()
    git_result = commit_and_push(
        [
            latest_path,
            dated_path,
            market_scoring.DEFAULT_HISTORY_PATH,
            report_path,
        ],
        str(trade_date),
        args.no_git,
    )

    result.update(
        {
            "status": "updated",
            "run_id": record.get("run_id"),
            "score_appended": score_result.get("appended"),
            "score_duplicate": score_result.get("duplicate"),
            "duplicate_of_run_id": score_result.get("duplicate_of_run_id"),
            "history_dedupe_key": score_result.get("dedupe_key"),
            "market_opportunity_score": record.get("market_opportunity_score"),
            "crowding_penalty": record.get("crowding_penalty"),
            "pre_cap_market_position_score": record.get("pre_cap_market_position_score"),
            "market_position_score": record.get("market_position_score"),
            "recommended_equity_position_range": record.get("recommended_equity_position_range")
            or record.get("base_equity_position_range")
            or record.get("equity_position_range"),
            "risk_cap_count": len(record.get("risk_caps", []) or []),
            "market_regime": record.get("market_regime"),
            "report": str(report_path.relative_to(ROOT)),
            "api": api,
            "git": git_result,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
