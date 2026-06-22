from __future__ import annotations

import hashlib
import json
import mimetypes
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from market_scoring import (
    DATA_DIR,
    DEFAULT_HISTORY_PATH,
    DEFAULT_SNAPSHOT_PATH,
    HISTORY_DEDUPE_KEY_FIELDS,
    HISTORY_SCHEMA_VERSION,
    MODEL_VERSION,
    POSITION_POLICY_VERSION,
    ROOT,
    append_score,
    load_history,
)


WEB_DIR = ROOT / "web"
PORT = 8011
TZ = ZoneInfo("Asia/Shanghai")
SERVICE_NAME = "MyInvestMarketWeb"
SERVICE_API_VERSION = 1

POSITION_SCORE_BANDS = [
    {
        "score_min": 0,
        "score_max": 20,
        "position_range": "0%-20%",
        "label": "极弱 / 防守",
        "description": "市场位置偏弱，股票账户以防守为主。",
    },
    {
        "score_min": 20,
        "score_max": 35,
        "position_range": "20%-40%",
        "label": "弱修复 / 谨慎",
        "description": "市场有修复迹象，但仍不适合高仓位。",
    },
    {
        "score_min": 35,
        "score_max": 50,
        "position_range": "40%-60%",
        "label": "中性震荡",
        "description": "市场处于中性区，仓位以均衡为主。",
    },
    {
        "score_min": 50,
        "score_max": 65,
        "position_range": "55%-75%",
        "label": "结构性偏强",
        "description": "市场有较明确结构性机会，可维持中高仓位。",
    },
    {
        "score_min": 65,
        "score_max": 80,
        "position_range": "75%-90%",
        "label": "趋势偏强",
        "description": "趋势和风险收益较好，可较高仓位参与。",
    },
    {
        "score_min": 80,
        "score_max": 100,
        "position_range": "90%-100%",
        "label": "低拥挤强趋势",
        "description": "市场健康且风险约束未触发时，股票账户可接近满仓。",
    },
]


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_meta(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "file": relative_path(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, TZ).isoformat(timespec="seconds"),
        "sha256": sha256_file(path),
    }


def latest_matching_file(pattern: str) -> Path | None:
    matches = [path for path in DATA_DIR.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name))


def latest_market_snapshot_result() -> dict[str, object]:
    path = DEFAULT_SNAPSHOT_PATH
    if not path.exists():
        return {"available": False, "kind": "market_snapshot", "error": "latest_market_snapshot.json not found"}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        "available": True,
        "kind": "market_snapshot",
        "endpoint": "/api/research/latest/market-snapshot",
        "metadata": file_meta(path),
        "basis_trade_date": payload.get("date") or (payload.get("market", {}) or {}).get("as_of_trade_date"),
        "payload": payload,
    }


def service_version_result() -> dict[str, object]:
    return {
        "available": True,
        "kind": "service_version",
        "endpoint": "/api/service",
        "service": SERVICE_NAME,
        "api_version": SERVICE_API_VERSION,
        "generated_at": now_iso(),
        "model_version": MODEL_VERSION,
        "position_policy_version": POSITION_POLICY_VERSION,
        "history_schema_version": HISTORY_SCHEMA_VERSION,
    }


def latest_market_score_result() -> dict[str, object]:
    records = score_records(include_legacy=False)
    if not records:
        return {"available": False, "kind": "market_score", "error": "market_score_history.json has no current-version records"}
    record = sorted(records, key=lambda row: str(row.get("scored_at", "")))[-1]
    result: dict[str, object] = {
        "available": True,
        "kind": "market_score",
        "endpoint": "/api/research/latest/market-score",
        "history_endpoint": "/api/history",
        "record": record,
    }
    if DEFAULT_HISTORY_PATH.exists():
        result["metadata"] = file_meta(DEFAULT_HISTORY_PATH)
    return result


def markdown_field(content: str, labels: list[str]) -> str | None:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        for label in labels:
            prefix = f"- {label}:"
            if line.startswith(prefix):
                return line[len(prefix) :].strip().strip("`")
    return None


def analysis_report_binding(content: str, latest_record: dict[str, object] | None = None) -> dict[str, object]:
    run_id = markdown_field(content, ["评分运行ID", "run_id"])
    basis_trade_date = markdown_field(content, ["数据基准日", "basis_trade_date"])
    expected_run_id = latest_record.get("run_id") if latest_record else None
    expected_basis_trade_date = latest_record.get("basis_trade_date") if latest_record else None
    consistent = bool(
        run_id
        and basis_trade_date
        and expected_run_id
        and expected_basis_trade_date
        and run_id == expected_run_id
        and basis_trade_date == expected_basis_trade_date
    )
    return {
        "run_id": run_id,
        "basis_trade_date": basis_trade_date,
        "expected_run_id": expected_run_id,
        "expected_basis_trade_date": expected_basis_trade_date,
        "consistent": consistent,
    }


def latest_market_analysis_result() -> dict[str, object]:
    path = latest_matching_file("chatgpt_market_analysis_*.md")
    if not path:
        return {"available": False, "kind": "market_analysis", "error": "chatgpt_market_analysis_*.md not found"}
    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), path.stem)
    score_result = latest_market_score_result()
    latest_record = score_result.get("record") if score_result.get("available") else None
    binding = analysis_report_binding(content, latest_record if isinstance(latest_record, dict) else None)
    result = {
        "available": bool(binding.get("consistent")),
        "kind": "market_analysis",
        "endpoint": "/api/research/latest/market-analysis",
        "metadata": file_meta(path),
        "title": title,
        "format": "text/markdown",
        "binding": binding,
        "content": content,
    }
    if not binding.get("consistent"):
        result["error"] = "latest analysis report does not match latest market score run_id/basis_trade_date"
    return result


def latest_research_bundle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "model_version": MODEL_VERSION,
        "endpoints": {
            "service": "/api/service",
            "index": "/api/index",
            "all_latest": "/api/research/latest",
            "market_snapshot": "/api/research/latest/market-snapshot",
            "market_score": "/api/research/latest/market-score",
            "market_analysis": "/api/research/latest/market-analysis",
            "score_history": "/api/history",
            "score_history_with_legacy": "/api/history?include_legacy=true",
        },
        "results": {
            "service": service_version_result(),
            "market_snapshot": latest_market_snapshot_result(),
            "market_score": latest_market_score_result(),
            "market_analysis": latest_market_analysis_result(),
        },
    }


def current_version_filter() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "position_policy_version": POSITION_POLICY_VERSION,
    }


def record_matches_current_version(record: dict[str, object]) -> bool:
    return (
        record.get("model_version") == MODEL_VERSION
        and record.get("position_policy_version") == POSITION_POLICY_VERSION
    )


def filtered_history(history: dict[str, object], include_legacy: bool = False) -> dict[str, object]:
    records = history.get("records", [])
    if not isinstance(records, list):
        records = []
    current_records = [
        record for record in records if isinstance(record, dict) and record_matches_current_version(record)
    ]
    selected_records = records if include_legacy else current_records
    result = dict(history)
    result["records"] = selected_records
    result["record_count"] = len(selected_records)
    result["total_record_count"] = len(records)
    result["legacy_record_count"] = len(records) - len(current_records)
    result["version_filter"] = {
        **current_version_filter(),
        "include_legacy": include_legacy,
    }
    return result


def score_records(include_legacy: bool = False) -> list[dict[str, object]]:
    history = load_history(DEFAULT_HISTORY_PATH)
    records = filtered_history(history, include_legacy=include_legacy).get("records", [])
    if not isinstance(records, list):
        return []
    return sorted(records, key=lambda row: str(row.get("scored_at", "")))


def recommended_equity_position_range(record: dict[str, object]) -> object:
    return (
        record.get("recommended_equity_position_range")
        or record.get("base_equity_position_range")
        or record.get("equity_position_range")
    )


def normalized_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in [None, ""]]
    if value:
        return [str(value)]
    return []


def risk_overview_result(latest: dict[str, object]) -> dict[str, object]:
    data_quality = latest.get("data_quality", {}) if isinstance(latest.get("data_quality"), dict) else {}
    warnings = normalized_text_list(data_quality.get("warnings"))
    missing_fields = normalized_text_list(data_quality.get("missing_fields"))
    sources_used = normalized_text_list(data_quality.get("sources_used"))
    raw_risk_caps = latest.get("risk_caps", [])
    risk_caps = raw_risk_caps if isinstance(raw_risk_caps, list) else []
    confidence_value = str(latest.get("confidence") or "unknown")
    has_warning = bool(warnings)
    has_risk_cap = bool(risk_caps)
    status = "risk" if has_warning or has_risk_cap or confidence_value == "low" else "normal"

    return {
        "available": bool(latest),
        "status": status,
        "status_label": "需关注" if status == "risk" else "正常",
        "confidence": {
            "value": latest.get("confidence"),
            "label": {"high": "高", "medium": "中", "low": "低"}.get(confidence_value, confidence_value),
            "message": "置信度由核心字段缺失、数据 warning 和滚动样本质量共同决定。",
        },
        "data_quality": {
            "status": "warning" if has_warning else "normal",
            "warning_count": len(warnings),
            "warnings": warnings,
            "missing_field_count": len(missing_fields),
            "missing_fields": missing_fields,
            "source_count": len(sources_used),
            "message": f"存在 {len(warnings)} 条数据质量 warning。" if has_warning else "暂无数据质量 warning。",
        },
        "risk_caps": {
            "status": "active" if has_risk_cap else "normal",
            "count": len(risk_caps),
            "items": risk_caps,
            "message": f"已触发 {len(risk_caps)} 项风险上限。" if has_risk_cap else "未触发风险上限。",
        },
    }


def position_policy_map_result(latest: dict[str, object]) -> dict[str, object]:
    return {
        "title": "股票账户净分-推荐权益仓位映射",
        "account_scope": "stock_account",
        "position_policy_version": latest.get("position_policy_version", POSITION_POLICY_VERSION),
        "x_axis": "市场仓位分 / market_position_score",
        "y_axis": "股票账户推荐权益仓位",
        "score_min": 0,
        "score_max": 100,
        "position_min": 0,
        "position_max": 100,
        "bands": POSITION_SCORE_BANDS,
        "current": {
            "market_position_score": latest.get("market_position_score"),
            "pre_cap_market_position_score": latest.get("pre_cap_market_position_score"),
            "recommended_equity_position_range": recommended_equity_position_range(latest),
            "risk_caps": latest.get("risk_caps", []),
            "market_regime": latest.get("market_regime"),
        },
    }


def history_api_result(include_legacy: bool = False) -> dict[str, object]:
    history = filtered_history(load_history(DEFAULT_HISTORY_PATH), include_legacy=include_legacy)
    return {
        "api_version": 2,
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "position_policy_version": POSITION_POLICY_VERSION,
        "dedupe_key_fields": list(HISTORY_DEDUPE_KEY_FIELDS),
        "version_filter": history.get("version_filter"),
        "record_count": history.get("record_count"),
        "total_record_count": history.get("total_record_count"),
        "legacy_record_count": history.get("legacy_record_count"),
        "history": history,
        "snapshot_exists": DEFAULT_SNAPSHOT_PATH.exists(),
    }


def homepage_index_result() -> dict[str, object]:
    records = score_records(include_legacy=False)
    latest = records[-1] if records else {}
    modules = latest.get("modules", {}) if isinstance(latest.get("modules"), dict) else {}
    selected_module_key = next(iter(modules.keys()), None)
    selected_module = modules.get(selected_module_key, {}) if selected_module_key else {}
    latest_research = latest_research_bundle()
    api_results = latest_research.get("results", {})
    api_available = {
        key: bool(value.get("available")) if isinstance(value, dict) else False
        for key, value in api_results.items()
    }
    policy_map = position_policy_map_result(latest)

    module_cards = []
    for key, module in modules.items():
        if not isinstance(module, dict):
            continue
        module_cards.append(
            {
                "key": key,
                "label": module.get("label"),
                "score": module.get("score"),
                "weight": module.get("weight"),
                "score_pct": module.get("score_pct"),
                "summary": module.get("summary"),
                "history": [
                    {
                        "basis_trade_date": record.get("basis_trade_date"),
                        "scored_at": record.get("scored_at"),
                        "score": ((record.get("modules", {}) or {}).get(key, {}) or {}).get("score"),
                        "score_pct": ((record.get("modules", {}) or {}).get(key, {}) or {}).get("score_pct"),
                    }
                    for record in records
                ],
            }
        )

    return {
        "available": bool(latest),
        "schema_version": 1,
        "generated_at": now_iso(),
        "model_version": latest.get("model_version", MODEL_VERSION) if latest else MODEL_VERSION,
        "account_scope": latest.get("account_scope", "stock_account") if latest else "stock_account",
        "position_policy_version": latest.get("position_policy_version", POSITION_POLICY_VERSION) if latest else POSITION_POLICY_VERSION,
        "page": {
            "path": "/",
            "title": "A股市场评分",
            "model_line": f"{latest.get('model_version', MODEL_VERSION)} · {latest.get('scored_at', '--')}" if latest else MODEL_VERSION,
            "primary_action": {"label": "记录当前评分", "method": "POST", "endpoint": "/api/score"},
        },
        "summary": {
            "basis_trade_date": latest.get("basis_trade_date"),
            "run_id": latest.get("run_id"),
            "market_regime": latest.get("market_regime"),
            "confidence": latest.get("confidence"),
            "equity_position_range": latest.get("equity_position_range"),
            "base_equity_position_range": latest.get("base_equity_position_range"),
            "recommended_equity_position_range": latest.get("recommended_equity_position_range")
            or latest.get("base_equity_position_range")
            or latest.get("equity_position_range"),
            "pre_cap_market_position_score": latest.get("pre_cap_market_position_score"),
            "risk_caps": latest.get("risk_caps", []),
            "account_scope": latest.get("account_scope", "stock_account"),
            "position_policy_version": latest.get("position_policy_version", POSITION_POLICY_VERSION),
            "volatility_policy": latest.get("volatility_policy", {}),
            "legacy_vol_adjusted_equity_position_range": latest.get("legacy_vol_adjusted_equity_position_range"),
            "legacy_vol_adjusted_market_position_score": latest.get("legacy_vol_adjusted_market_position_score"),
            "legacy_vol_adjusted_deprecated": latest.get("legacy_vol_adjusted_deprecated"),
            "data_quality": latest.get("data_quality", {}),
            "cards": [
                {
                    "id": "position_score",
                    "label": "股票账户仓位分",
                    "value": latest.get("market_position_score"),
                    "max": 100,
                    "detail": latest.get("recommended_equity_position_range")
                    or latest.get("base_equity_position_range")
                    or latest.get("equity_position_range"),
                },
                {
                    "id": "opportunity_score",
                    "label": "市场机会分",
                    "value": latest.get("market_opportunity_score"),
                    "max": 100,
                    "detail": "100分制",
                },
                {
                    "id": "crowding_penalty",
                    "label": "拥挤惩罚",
                    "value": latest.get("crowding_penalty"),
                    "max": 30,
                    "detail": "30分上限",
                },
                {
                    "id": "pre_cap_position",
                    "label": "扣上限前分",
                    "value": latest.get("pre_cap_market_position_score"),
                    "max": 100,
                    "detail": f"{len(latest.get('risk_caps', []) or [])} 项风险上限",
                },
                {
                    "id": "market_regime",
                    "label": "市场状态",
                    "value": latest.get("market_regime"),
                    "detail": latest.get("confidence"),
                },
            ],
        },
        "risk_overview": risk_overview_result(latest),
        "api_status": {
            "label": "最新研究结果 API",
            "available_count": sum(1 for available in api_available.values() if available),
            "total_count": len(api_available),
            "items": api_available,
            "endpoints": latest_research.get("endpoints", {}),
        },
        "position_policy_map": policy_map,
        "position_map": {**policy_map, "legacy_alias_of": "position_policy_map"},
        "overview_chart": {
            "title": "总分与上证指数",
            "record_count": len(records),
            "series": {
                "market_position_score": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("market_position_score")}
                    for row in records
                ],
                "pre_cap_market_position_score": [
                    {
                        "basis_trade_date": row.get("basis_trade_date"),
                        "scored_at": row.get("scored_at"),
                        "value": row.get("pre_cap_market_position_score")
                        or row.get("base_market_position_score")
                        or row.get("market_position_score"),
                    }
                    for row in records
                ],
                "market_opportunity_score": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("market_opportunity_score")}
                    for row in records
                ],
                "crowding_penalty": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("crowding_penalty")}
                    for row in records
                ],
                "shanghai_composite": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("shanghai_composite")}
                    for row in records
                ],
            },
        },
        "modules": {
            "title": "子项分历史",
            "selected_key": selected_module_key,
            "cards": module_cards,
        },
        "selected_module_detail": {
            "key": selected_module_key,
            "label": selected_module.get("label") if isinstance(selected_module, dict) else None,
            "metrics": selected_module.get("metrics", {}) if isinstance(selected_module, dict) else {},
            "evidence": selected_module.get("evidence", []) if isinstance(selected_module, dict) else [],
        },
        "history_table": {
            "title": "评分历史",
            "updated_at": load_history(DEFAULT_HISTORY_PATH).get("updated_at"),
            "version_filter": current_version_filter(),
            "rows": [
                {
                    "scored_at": row.get("scored_at"),
                    "basis_trade_date": row.get("basis_trade_date"),
                    "market_opportunity_score": row.get("market_opportunity_score"),
                    "crowding_penalty": row.get("crowding_penalty"),
                    "pre_cap_market_position_score": row.get("pre_cap_market_position_score")
                    or row.get("base_market_position_score")
                    or row.get("market_position_score"),
                    "market_position_score": row.get("market_position_score"),
                    "shanghai_composite": row.get("shanghai_composite"),
                    "equity_position_range": row.get("equity_position_range"),
                    "recommended_equity_position_range": row.get("recommended_equity_position_range")
                    or row.get("base_equity_position_range")
                    or row.get("equity_position_range"),
                    "risk_cap_count": len(row.get("risk_caps", []) or []),
                    "position_policy_version": row.get("position_policy_version"),
                    "market_regime": row.get("market_regime"),
                }
                for row in reversed(records)
            ],
        },
        "source_endpoints": {
            "page": "/",
            "service": "/api/service",
            "index": "/api/index",
            "history": "/api/history",
            "history_with_legacy": "/api/history?include_legacy=true",
            "latest_research": "/api/research/latest",
            "latest_score": "/api/research/latest/market-score",
            "latest_snapshot": "/api/research/latest/market-snapshot",
            "latest_analysis": "/api/research/latest/market-analysis",
        },
    }


class MarketWebHandler(BaseHTTPRequestHandler):
    server_version = "MyInvestMarketWeb/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == "/api/service":
                self.send_json(service_version_result())
                return
            if path == "/api/index":
                self.send_json(homepage_index_result())
                return
            if path in ["/api/latest", "/api/research/latest"]:
                self.send_json(latest_research_bundle())
                return
            if path == "/api/research/latest/market-snapshot":
                self.send_json(latest_market_snapshot_result())
                return
            if path == "/api/research/latest/market-score":
                self.send_json(latest_market_score_result())
                return
            if path == "/api/research/latest/market-analysis":
                self.send_json(latest_market_analysis_result())
                return
            if path == "/api/history":
                include_legacy = (query.get("include_legacy", ["false"])[0] or "").lower() == "true"
                self.send_json(history_api_result(include_legacy=include_legacy))
                return
            if path == "/api/snapshot":
                if not DEFAULT_SNAPSHOT_PATH.exists():
                    self.send_json({"error": "latest_market_snapshot.json not found"}, status=404)
                    return
                self.send_json(json.loads(DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8-sig")))
                return
            self.send_static(path)
        except Exception as exc:
            self.send_json(
                {
                    "error": str(exc),
                    "type": exc.__class__.__name__,
                    "trace": traceback.format_exc(limit=3),
                },
                status=500,
            )

    def do_POST(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
            if path != "/api/score":
                self.send_json({"error": "not found"}, status=404)
                return
            result = append_score(DEFAULT_SNAPSHOT_PATH, DEFAULT_HISTORY_PATH)
            self.send_json(
                {
                    "model_version": MODEL_VERSION,
                    "position_policy_version": POSITION_POLICY_VERSION,
                    "appended": result.get("appended"),
                    "duplicate": result.get("duplicate"),
                    "dedupe_key": result.get("dedupe_key"),
                    "duplicate_of_run_id": result.get("duplicate_of_run_id"),
                    "record": result["record"],
                    "history": result["history"],
                },
                status=201 if result.get("appended") else 200,
            )
        except Exception as exc:
            self.send_json(
                {
                    "error": str(exc),
                    "type": exc.__class__.__name__,
                    "trace": traceback.format_exc(limit=3),
                },
                status=500,
            )

    def send_static(self, request_path: str) -> None:
        root = WEB_DIR.resolve()
        relative = "index.html" if request_path in ["", "/"] else request_path.lstrip("/")
        target = (root / relative).resolve()
        if target == root:
            target = target / "index.html"
        if target != root and root not in target.parents:
            self.send_response(403)
            self.end_headers()
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), MarketWebHandler)
    print(f"MyInvestMarket Web is running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
