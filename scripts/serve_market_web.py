from __future__ import annotations

import hashlib
import json
import mimetypes
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from market_scoring import (
    DATA_DIR,
    DEFAULT_HISTORY_PATH,
    DEFAULT_SNAPSHOT_PATH,
    MODEL_VERSION,
    ROOT,
    append_score,
    load_history,
)


WEB_DIR = ROOT / "web"
PORT = 8011
TZ = ZoneInfo("Asia/Shanghai")

POSITION_CURVE_POINTS = [
    {"score": 0, "base_equity_midpoint_pct": 10},
    {"score": 20, "base_equity_midpoint_pct": 20},
    {"score": 35, "base_equity_midpoint_pct": 35},
    {"score": 50, "base_equity_midpoint_pct": 45},
    {"score": 65, "base_equity_midpoint_pct": 60},
    {"score": 80, "base_equity_midpoint_pct": 75},
    {"score": 100, "base_equity_midpoint_pct": 85},
]

MARKET_REGIME_BANDS = [
    {"from": 0, "to": 20, "label": "熊市防守"},
    {"from": 20, "to": 35, "label": "弱修复"},
    {"from": 35, "to": 50, "label": "震荡"},
    {"from": 50, "to": 65, "label": "结构牛"},
    {"from": 65, "to": 80, "label": "趋势牛"},
    {"from": 80, "to": 100, "label": "高热牛"},
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


def latest_market_score_result() -> dict[str, object]:
    history = load_history(DEFAULT_HISTORY_PATH)
    records = history.get("records", [])
    if not records:
        return {"available": False, "kind": "market_score", "error": "market_score_history.json has no records"}
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


def latest_market_analysis_result() -> dict[str, object]:
    path = latest_matching_file("chatgpt_market_analysis_*.md")
    if not path:
        return {"available": False, "kind": "market_analysis", "error": "chatgpt_market_analysis_*.md not found"}
    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), path.stem)
    return {
        "available": True,
        "kind": "market_analysis",
        "endpoint": "/api/research/latest/market-analysis",
        "metadata": file_meta(path),
        "title": title,
        "format": "text/markdown",
        "content": content,
    }


def latest_research_bundle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "model_version": MODEL_VERSION,
        "endpoints": {
            "index": "/api/index",
            "all_latest": "/api/research/latest",
            "market_snapshot": "/api/research/latest/market-snapshot",
            "market_score": "/api/research/latest/market-score",
            "market_analysis": "/api/research/latest/market-analysis",
            "score_history": "/api/history",
        },
        "results": {
            "market_snapshot": latest_market_snapshot_result(),
            "market_score": latest_market_score_result(),
            "market_analysis": latest_market_analysis_result(),
        },
    }


def score_records() -> list[dict[str, object]]:
    history = load_history(DEFAULT_HISTORY_PATH)
    records = history.get("records", [])
    if not isinstance(records, list):
        return []
    return sorted(records, key=lambda row: str(row.get("scored_at", "")))


def homepage_index_result() -> dict[str, object]:
    records = score_records()
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
        "schema_version": 1,
        "generated_at": now_iso(),
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
            "vol_adjusted_equity_position_range": latest.get("vol_adjusted_equity_position_range"),
            "vol_adjusted_market_position_score": latest.get("vol_adjusted_market_position_score"),
            "volatility_targeting": latest.get("volatility_targeting", {}),
            "cards": [
                {
                    "id": "position_score",
                    "label": "仓位参考分",
                    "value": latest.get("market_position_score"),
                    "max": 100,
                    "detail": latest.get("equity_position_range"),
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
                    "id": "vol_adjusted_position",
                    "label": "波动调整分",
                    "value": latest.get("vol_adjusted_market_position_score"),
                    "max": 100,
                    "detail": latest.get("vol_adjusted_equity_position_range"),
                },
                {
                    "id": "market_regime",
                    "label": "市场状态",
                    "value": latest.get("market_regime"),
                    "detail": latest.get("confidence"),
                },
            ],
        },
        "api_status": {
            "label": "最新研究结果 API",
            "available_count": sum(1 for available in api_available.values() if available),
            "total_count": len(api_available),
            "items": api_available,
            "endpoints": latest_research.get("endpoints", {}),
        },
        "position_map": {
            "title": "市场分与仓位对应",
            "x_axis": "市场分",
            "y_axis": "基准权益仓位",
            "curve_points": POSITION_CURVE_POINTS,
            "regime_bands": MARKET_REGIME_BANDS,
            "current": {
                "market_position_score": latest.get("market_position_score"),
                "base_equity_position_range": latest.get("base_equity_position_range") or latest.get("equity_position_range"),
                "vol_adjusted_equity_position_range": latest.get("vol_adjusted_equity_position_range"),
                "market_regime": latest.get("market_regime"),
            },
        },
        "overview_chart": {
            "title": "总分与上证指数",
            "record_count": len(records),
            "series": {
                "market_position_score": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("market_position_score")}
                    for row in records
                ],
                "vol_adjusted_market_position_score": [
                    {"basis_trade_date": row.get("basis_trade_date"), "scored_at": row.get("scored_at"), "value": row.get("vol_adjusted_market_position_score")}
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
            "rows": [
                {
                    "scored_at": row.get("scored_at"),
                    "basis_trade_date": row.get("basis_trade_date"),
                    "market_opportunity_score": row.get("market_opportunity_score"),
                    "crowding_penalty": row.get("crowding_penalty"),
                    "market_position_score": row.get("market_position_score"),
                    "vol_adjusted_market_position_score": row.get("vol_adjusted_market_position_score"),
                    "shanghai_composite": row.get("shanghai_composite"),
                    "equity_position_range": row.get("equity_position_range"),
                    "vol_adjusted_equity_position_range": row.get("vol_adjusted_equity_position_range"),
                    "market_regime": row.get("market_regime"),
                }
                for row in reversed(records)
            ],
        },
        "source_endpoints": {
            "page": "/",
            "index": "/api/index",
            "history": "/api/history",
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
            path = unquote(urlparse(self.path).path)
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
                self.send_json(
                    {
                        "model_version": MODEL_VERSION,
                        "history": load_history(DEFAULT_HISTORY_PATH),
                        "snapshot_exists": DEFAULT_SNAPSHOT_PATH.exists(),
                    }
                )
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
                    "record": result["record"],
                    "history": result["history"],
                },
                status=201,
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
