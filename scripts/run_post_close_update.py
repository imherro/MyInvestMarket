from __future__ import annotations

import argparse
import atexit
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import build_market_dataset
import market_scoring


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("Asia/Shanghai")
PORT = 8011
LOCK_PATH = ROOT / "temp" / "runtime" / "post_close_update.lock"
LOCK_STALE_SECONDS = 6 * 60 * 60
ROLLING_SNAPSHOT_TARGET_COUNT = market_scoring.MIN_ROLLING_SAMPLE_COUNT + 1
VERIFY_ENDPOINTS = [
    "/api/service",
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


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read_lock_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def acquire_post_close_lock(path: Path = LOCK_PATH, stale_seconds: int = LOCK_STALE_SECONDS) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    payload = {
        "token": token,
        "pid": os.getpid(),
        "started_at": datetime.now(TZ).isoformat(timespec="seconds"),
    }

    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age_seconds = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            existing = read_lock_payload(path)
            if age_seconds > stale_seconds:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            return {
                "acquired": False,
                "reason": "post-close update already running",
                "lock_path": display_path(path),
                "existing_pid": existing.get("pid"),
                "existing_started_at": existing.get("started_at"),
                "age_seconds": round(age_seconds, 3),
            }
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return {
            "acquired": True,
            "path": path,
            "token": token,
            "lock_path": display_path(path),
            "started_at": payload["started_at"],
        }

    return acquire_post_close_lock(path=path, stale_seconds=stale_seconds)


def release_post_close_lock(lock: dict[str, Any]) -> None:
    if not lock.get("acquired"):
        return
    path = Path(lock["path"])
    token = lock.get("token")
    existing = read_lock_payload(path)
    if existing.get("token") != token:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


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


def recent_complete_trade_dates(as_of: date, count: int = ROLLING_SNAPSHOT_TARGET_COUNT) -> list[str]:
    pro = build_market_dataset.tushare_client()
    start = build_market_dataset.yyyymmdd(as_of - timedelta(days=45))
    end = build_market_dataset.yyyymmdd(as_of)
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    if cal.empty:
        raise RuntimeError(f"No open trading day found from {start} to {end}")

    complete_days: list[str] = []
    for trade_date in sorted(cal["cal_date"].astype(str).tolist(), reverse=True):
        daily = pro.daily(trade_date=trade_date)
        index_probe = pro.index_daily(ts_code="000001.SH", trade_date=trade_date)
        if daily.empty or index_probe.empty:
            continue
        complete_days.append(trade_date)
        if len(complete_days) >= count:
            break
    return list(reversed(complete_days))


def write_dated_snapshot(dataset: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"market_snapshot_{dataset['date']}.json"
    payload = json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def backfill_recent_market_snapshots(as_of: date, current_trade_date: str) -> list[Path]:
    backfilled: list[Path] = []
    current_iso = str(current_trade_date)
    for trade_date in recent_complete_trade_dates(as_of, ROLLING_SNAPSHOT_TARGET_COUNT):
        trade_iso = build_market_dataset.iso_date(trade_date)
        if trade_iso == current_iso:
            continue
        path = DATA_DIR / f"market_snapshot_{trade_iso}.json"
        if path.exists():
            continue
        dataset = build_market_dataset.build_dataset(datetime.strptime(trade_iso, "%Y-%m-%d").date())
        if dataset.get("date") != trade_iso:
            raise RuntimeError(f"Backfill expected {trade_iso}, got {dataset.get('date')}")
        backfilled.append(write_dated_snapshot(dataset))
    return backfilled


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
- 评分运行ID: {record.get('run_id')}
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


def require_api(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_api_payloads(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    service_payload = payloads.get("/api/service") or {}
    index = payloads.get("/api/index") or {}
    score_payload = payloads.get("/api/research/latest/market-score") or {}
    analysis_payload = payloads.get("/api/research/latest/market-analysis") or {}
    latest_record = score_payload.get("record") or {}
    index_summary = index.get("summary") or {}
    policy_map = index.get("position_policy_map") or {}
    binding = analysis_payload.get("binding") or {}
    local_model_version = market_scoring.MODEL_VERSION
    local_position_policy_version = market_scoring.POSITION_POLICY_VERSION

    require_api(bool(service_payload.get("available")), "/api/service is not available")
    require_api(
        service_payload.get("model_version") == local_model_version,
        "/api/service MODEL_VERSION does not match local MODEL_VERSION",
    )
    require_api(
        service_payload.get("position_policy_version") == local_position_policy_version,
        "/api/service POSITION_POLICY_VERSION does not match local POSITION_POLICY_VERSION",
    )
    require_api(bool(index.get("available")), "/api/index is not available")
    require_api(index.get("model_version") == local_model_version, "/api/index MODEL_VERSION does not match local MODEL_VERSION")
    require_api(
        index.get("position_policy_version") == local_position_policy_version,
        "/api/index POSITION_POLICY_VERSION does not match local POSITION_POLICY_VERSION",
    )
    require_api(bool(index_summary.get("run_id")), "/api/index.summary.run_id is missing")
    require_api(bool(index_summary.get("basis_trade_date")), "/api/index.summary.basis_trade_date is missing")
    require_api(bool(index_summary.get("recommended_equity_position_range")), "/api/index.summary.recommended_equity_position_range is missing")
    require_api(bool(policy_map.get("position_policy_version")), "/api/index.position_policy_map.position_policy_version is missing")
    require_api(
        policy_map.get("position_policy_version") == local_position_policy_version,
        "/api/index.position_policy_map.position_policy_version does not match local POSITION_POLICY_VERSION",
    )
    require_api(bool((policy_map.get("current") or {}).get("market_position_score") is not None), "/api/index.position_policy_map.current.market_position_score is missing")

    require_api(bool(score_payload.get("available")), "/api/research/latest/market-score is not available")
    require_api(bool(latest_record.get("run_id")), "latest market score run_id is missing")
    require_api(bool(latest_record.get("basis_trade_date")), "latest market score basis_trade_date is missing")
    require_api(latest_record.get("model_version") == local_model_version, "latest market score MODEL_VERSION does not match local MODEL_VERSION")
    require_api(
        latest_record.get("position_policy_version") == local_position_policy_version,
        "latest market score POSITION_POLICY_VERSION does not match local POSITION_POLICY_VERSION",
    )
    require_api(bool(latest_record.get("recommended_equity_position_range")), "latest market score recommended_equity_position_range is missing")
    require_api(index_summary.get("run_id") == latest_record.get("run_id"), "/api/index summary run_id does not match latest score")
    require_api(
        index_summary.get("basis_trade_date") == latest_record.get("basis_trade_date"),
        "/api/index summary basis_trade_date does not match latest score",
    )

    require_api(bool(analysis_payload.get("available")), "/api/research/latest/market-analysis is not available")
    require_api(bool(binding.get("consistent")), "latest analysis report binding is inconsistent")
    require_api(binding.get("run_id") == latest_record.get("run_id"), "latest analysis run_id does not match latest score")
    require_api(
        binding.get("basis_trade_date") == latest_record.get("basis_trade_date"),
        "latest analysis basis_trade_date does not match latest score",
    )

    return {
        "ok": True,
        "service_version": {
            "model_version": service_payload.get("model_version"),
            "position_policy_version": service_payload.get("position_policy_version"),
        },
        "run_id": latest_record.get("run_id"),
        "basis_trade_date": latest_record.get("basis_trade_date"),
        "checked_endpoints": sorted(payloads.keys()),
        "analysis_report": {
            "file": ((analysis_payload.get("metadata") or {}).get("file")),
            "binding": binding,
        },
    }


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
    payloads: dict[str, dict[str, Any]] = {}
    for path in VERIFY_ENDPOINTS:
        payload = endpoint_json(path)
        payloads[path] = payload
    validation = validate_api_payloads(payloads)
    result: dict[str, Any] = {"validation": validation}
    for path, payload in payloads.items():
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
    lock = acquire_post_close_lock()
    if not lock.get("acquired"):
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": lock.get("reason"),
                    "lock": lock,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    atexit.register(release_post_close_lock, lock)

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
    backfilled_paths = backfill_recent_market_snapshots(as_of, str(trade_date))

    history = market_scoring.load_history(market_scoring.DEFAULT_HISTORY_PATH)
    last = latest_record(history)
    same_trade_date = bool(last and last.get("basis_trade_date") == trade_date)
    unchanged = same_trade_date and old_fingerprint == new_fingerprint and not backfilled_paths

    result: dict[str, Any] = {
        "basis_trade_date": trade_date,
        "model_version": market_scoring.MODEL_VERSION,
        "same_trade_date_as_latest_score": same_trade_date,
        "stable_market_snapshot_unchanged": unchanged,
        "backfilled_snapshots": [str(path.relative_to(ROOT)) for path in backfilled_paths],
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
            *backfilled_paths,
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
            "schema_validation": score_result.get("schema_validation"),
            "audit_event": score_result.get("audit_event"),
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
