from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from market_scoring import (
    ALLOCATION_POLICY_VERSION,
    ALLOCATION_SLEEVE_ORDER,
    DATA_DIR,
    DEFAULT_HISTORY_PATH,
    DEFAULT_SNAPSHOT_PATH,
    HISTORY_DEDUPE_KEY_FIELDS,
    HISTORY_SCHEMA_VERSION,
    MODEL_VERSION,
    POSITION_POLICY_VERSION,
    ROOT,
    STABLE_RISK_CAP_REASONS,
    append_score,
    load_history,
    score_record_is_current_schema,
)
from market_state_stability import validate_state_stability


WEB_DIR = ROOT / "web"
PORT = 8011
TZ = ZoneInfo("Asia/Shanghai")
SERVICE_NAME = "MyInvestMarketWeb"
SERVICE_API_VERSION = 1
DEFAULT_BASE_URL = f"http://127.0.0.1:{PORT}"


def stable_release_result() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "status": "stable",
        "core_rules_frozen": True,
        "risk_cap_reasons": list(STABLE_RISK_CAP_REASONS),
        "risk_cap_extension_policy": f"{MODEL_VERSION} freezes risk_cap types; parameter tuning is allowed, new logical branches require a new model version.",
        "position_policy_version": POSITION_POLICY_VERSION,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
    }

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


MARKET_CYCLE_REFERENCE = [
    {
        "wave": "1",
        "phase": "impulse",
        "label": "熊末反弹",
        "price_level": 42,
        "opportunity_score_range": "45-60",
        "position_score_range": "40-70",
        "equity_position_range": "40%-75%",
        "note": "估值开始有吸引力，但趋势和资金通常还需要确认。",
    },
    {
        "wave": "2",
        "phase": "impulse",
        "label": "回踩确认",
        "price_level": 32,
        "opportunity_score_range": "35-50",
        "position_score_range": "35-60",
        "equity_position_range": "20%-60%",
        "note": "便宜度仍在，但回踩会压低趋势、宽度和风险偏好。",
    },
    {
        "wave": "3",
        "phase": "impulse",
        "label": "主升共振",
        "price_level": 82,
        "opportunity_score_range": "75-90",
        "position_score_range": "80-100",
        "equity_position_range": "90%-100%",
        "note": "趋势、宽度、资金和主线共振，是模型最愿意重仓的位置。",
    },
    {
        "wave": "4",
        "phase": "impulse",
        "label": "中继调整",
        "price_level": 64,
        "opportunity_score_range": "60-75",
        "position_score_range": "60-80",
        "equity_position_range": "55%-90%",
        "note": "牛市中继回撤，仓位不追高，但也不按熊市处理。",
    },
    {
        "wave": "5",
        "phase": "impulse",
        "label": "牛末冲顶",
        "price_level": 90,
        "opportunity_score_range": "60-80",
        "position_score_range": "20-45",
        "equity_position_range": "20%-60%",
        "note": "人气和趋势仍强，但估值、拥挤、波动和风险上限开始压仓位。",
    },
    {
        "wave": "a",
        "phase": "corrective",
        "label": "顶部杀跌",
        "price_level": 55,
        "opportunity_score_range": "40-55",
        "position_score_range": "20-40",
        "equity_position_range": "20%-60%",
        "note": "顶部后的第一波下跌，风险释放不充分，先控制仓位。",
    },
    {
        "wave": "b",
        "phase": "corrective",
        "label": "反抽诱多",
        "price_level": 68,
        "opportunity_score_range": "50-65",
        "position_score_range": "20-45",
        "equity_position_range": "20%-60%",
        "note": "反抽会抬高短期机会分，但若估值和资金没有修复，仓位仍受约束。",
    },
    {
        "wave": "c",
        "phase": "corrective",
        "label": "悲观出清",
        "price_level": 22,
        "opportunity_score_range": "25-45",
        "position_score_range": "10-40",
        "equity_position_range": "0%-40%",
        "note": "最悲观时估值便宜，但趋势、资金和宽度常未确认，不会盲目满仓。",
    },
]


RISK_CAP_LABELS = {
    "high_crowding_extreme": "拥挤极高",
    "high_crowding": "拥挤偏高",
    "volume_blowoff_top": "爆量顶部",
    "sector_concentration_top": "主线拥挤顶部",
    "capital_outflow_combo": "资金同步退潮",
    "extreme_expensive_valuation": "估值极贵",
    "expensive_valuation": "估值偏贵",
    "bubble_top_combo": "泡沫顶部组合",
    "extreme_high_volatility": "波动率极高",
    "high_volatility": "波动率偏高",
    "missing_valuation_data_hot_market": "高机会行情缺估值数据",
    "missing_volatility_data_hot_market": "高机会行情缺波动率数据",
    "missing_core_risk_data_hot_market": "高机会行情缺核心风控数据",
    "strong_index_weak_breadth": "指数强但宽度弱",
}


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
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "stable_release": stable_release_result(),
    }


def api_endpoint(
    method: str,
    path: str,
    purpose: str,
    response: str,
    *,
    read_only: bool = True,
    parameters: list[dict[str, object]] | None = None,
    safety_note: str | None = None,
    alias_of: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "method": method,
        "path": path,
        "purpose": purpose,
        "parameters": parameters or [],
        "response": response,
        "read_only": read_only,
    }
    if safety_note:
        item["safety_note"] = safety_note
    if alias_of:
        item["alias_of"] = alias_of
    return item


def api_groups_result() -> list[dict[str, object]]:
    return [
        {
            "key": "documentation",
            "label": "文档入口",
            "description": "面向浏览器和机器读取的接口说明入口。",
            "endpoints": [
                api_endpoint(
                    "GET",
                    "/",
                    "Web 首页，展示最新市场评分、历史曲线、仓位映射和接口说明。",
                    "HTML 页面。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api",
                    "统一接口目录，列出当前系统所有公开接口及安全边界。",
                    "接口目录 JSON；不触发重计算、写入、交易或同步。",
                    read_only=True,
                    safety_note="只返回静态说明与目录元数据。",
                ),
                api_endpoint(
                    "GET",
                    "/docs",
                    "浏览器版接口目录。",
                    "HTML 文档页，由 /api 目录生成。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/redoc",
                    "浏览器版精简接口目录，保留给 Redoc 风格入口。",
                    "HTML 文档页，由 /api 目录生成。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/openapi.json",
                    "OpenAPI 风格的机器可读接口摘要。",
                    "OpenAPI JSON，字段从 /api 目录生成。",
                    read_only=True,
                ),
            ],
        },
        {
            "key": "system_status",
            "label": "系统状态",
            "description": "查看服务、模型和策略版本。",
            "endpoints": [
                api_endpoint(
                    "GET",
                    "/api/service",
                    "服务版本、模型版本、仓位策略版本、配置策略版本和稳定发布锁。",
                    "service、api_version、model_version、position_policy_version、allocation_policy_version、stable_release。",
                    read_only=True,
                ),
            ],
        },
        {
            "key": "current_data",
            "label": "当前数据",
            "description": "读取首页当前态、最新研究束和原始快照。",
            "endpoints": [
                api_endpoint(
                    "GET",
                    "/api/index",
                    "主页核心内容，供 Web 首页一次性渲染。",
                    "评分摘要、风险概览、四仓配置、仓位映射、周期示意、历史曲线、接口目录摘要。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest",
                    "最新市场研究结果聚合入口。",
                    "service、market_snapshot、market_score、market_analysis、model_validation、model_health、strategy_robustness。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/latest",
                    "兼容旧调用方的最新研究结果聚合入口。",
                    "与 /api/research/latest 相同。",
                    read_only=True,
                    alias_of="/api/research/latest",
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest/market-snapshot",
                    "最新市场数据快照。",
                    "快照文件元数据、basis_trade_date 和完整 payload。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/snapshot",
                    "最新市场快照的原始 JSON。",
                    "latest_market_snapshot.json 的原始内容。",
                    read_only=True,
                ),
            ],
        },
        {
            "key": "analysis_results",
            "label": "分析结果",
            "description": "读取评分、报告、模型健康和稳健性分析。",
            "endpoints": [
                api_endpoint(
                    "GET",
                    "/api/research/latest/market-score",
                    "最新市场评分记录。",
                    "最新 current-version 评分 record、历史入口和文件元数据。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest/market-analysis",
                    "最新 Markdown 市场研究报告。",
                    "报告标题、Markdown 内容、文件元数据和 run_id/basis_trade_date 绑定校验。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest/model-validation",
                    "最新模型验证报告。",
                    "验证 JSON payload、Markdown 内容和文件元数据。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest/model-health",
                    "模型漂移、滚动表现、健康分和校准触发建议。",
                    "calibration trigger payload。",
                    read_only=True,
                ),
                api_endpoint(
                    "GET",
                    "/api/research/latest/strategy-robustness",
                    "策略稳健性分析。",
                    "因果代理、样本外验证、压力测试和 robustness payload。",
                    read_only=True,
                ),
            ],
        },
        {
            "key": "history_data",
            "label": "历史数据",
            "description": "读取评分历史和版本过滤结果。",
            "endpoints": [
                api_endpoint(
                    "GET",
                    "/api/history",
                    "当前模型版本评分历史；可选包含旧版本。",
                    "history、record_count、total_record_count、legacy_record_count、version_filter。",
                    read_only=True,
                    parameters=[
                        {
                            "name": "include_legacy",
                            "in": "query",
                            "required": False,
                            "type": "boolean",
                            "default": False,
                            "description": "true 时返回包含旧模型版本的完整历史。",
                        }
                    ],
                ),
            ],
        },
        {
            "key": "write_actions",
            "label": "写入动作",
            "description": "会改变本地评分历史的接口；不执行交易。",
            "endpoints": [
                api_endpoint(
                    "POST",
                    "/api/score",
                    "根据本地 latest_market_snapshot.json 记录一次当前评分。",
                    "appended、duplicate、dedupe_key、record、history。",
                    read_only=False,
                    safety_note="会写入本地评分历史；不下单、不同步 GitHub、不触发交易。",
                ),
            ],
        },
    ]


def api_catalog_result(base_url: str = DEFAULT_BASE_URL) -> dict[str, object]:
    groups = api_groups_result()
    total_endpoints = sum(len(group.get("endpoints", [])) for group in groups)
    description = "MyInvest A股市场研究与股票账户仓位评分系统。"
    return {
        "system_name": SERVICE_NAME,
        "version": SERVICE_API_VERSION,
        "description": description,
        "system": {
            "name": SERVICE_NAME,
            "version": SERVICE_API_VERSION,
            "model_version": MODEL_VERSION,
            "position_policy_version": POSITION_POLICY_VERSION,
            "allocation_policy_version": ALLOCATION_POLICY_VERSION,
            "description": description,
        },
        "base_url": base_url,
        "generated_at": now_iso(),
        "docs": {
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
            "catalog": "/api",
        },
        "recommended_entrypoints": [
            {
                "method": "GET",
                "path": "/api/index",
                "purpose": "Web 首页和外部系统读取主页主要内容的首选入口。",
            },
            {
                "method": "GET",
                "path": "/api/research/latest",
                "purpose": "一次性读取最新研究结果聚合包。",
            },
            {
                "method": "GET",
                "path": "/api/research/latest/market-score",
                "purpose": "只需要最新市场分、仓位分和评分依据时使用。",
            },
            {
                "method": "GET",
                "path": "/api/history?include_legacy=true",
                "purpose": "需要复盘完整历史和旧模型记录时使用。",
            },
            {
                "method": "GET",
                "path": "/api/research/latest/model-health",
                "purpose": "检查模型漂移、校准触发和健康状态。",
            },
        ],
        "safety": {
            "catalog_read_only": True,
            "boundaries": [
                "/api 只做接口说明，不触发重计算、写入、交易或同步。",
                "GET 接口仅读取本地已生成研究文件或当前服务版本信息。",
                "POST /api/score 会写入本地评分历史，但不下单、不同步 GitHub、不连接 QMT 交易。",
                "所有输出是研究和仓位框架参考，不是自动交易指令。",
                "接口不返回 .env、token、账户金额、下单数量等敏感执行信息。",
            ],
        },
        "groups": groups,
        "total_endpoints": total_endpoints,
    }


def api_catalog_summary_result() -> dict[str, object]:
    catalog = api_catalog_result()
    return {
        "endpoint": "/api",
        "total_endpoints": catalog["total_endpoints"],
        "docs": catalog["docs"],
        "recommended_entrypoints": catalog["recommended_entrypoints"],
        "safety": catalog["safety"],
        "groups": [
            {
                "key": group.get("key"),
                "label": group.get("label"),
                "description": group.get("description"),
                "endpoint_count": len(group.get("endpoints", [])),
            }
            for group in catalog["groups"]
        ],
    }


def openapi_result() -> dict[str, object]:
    catalog = api_catalog_result()
    paths: dict[str, object] = {}
    for group in catalog["groups"]:
        tag = group.get("label") or group.get("key")
        for endpoint in group.get("endpoints", []):
            if not isinstance(endpoint, dict):
                continue
            method = str(endpoint.get("method", "GET")).lower()
            path = str(endpoint.get("path", ""))
            operation = {
                "tags": [tag],
                "summary": endpoint.get("purpose"),
                "description": endpoint.get("response"),
                "parameters": [
                    {
                        "name": parameter.get("name"),
                        "in": parameter.get("in", "query"),
                        "required": bool(parameter.get("required")),
                        "description": parameter.get("description", ""),
                        "schema": {
                            "type": parameter.get("type", "string"),
                            **({"default": parameter.get("default")} if "default" in parameter else {}),
                        },
                    }
                    for parameter in endpoint.get("parameters", [])
                    if isinstance(parameter, dict)
                ],
                "responses": {
                    "200": {
                        "description": endpoint.get("response") or "OK",
                    }
                },
                "x-read-only": endpoint.get("read_only"),
            }
            if method == "post":
                operation["responses"]["201"] = {"description": "Created when a new record is appended."}
            paths.setdefault(path, {})[method] = operation
    return {
        "openapi": "3.1.0",
        "info": {
            "title": catalog["system"]["description"],
            "version": str(catalog["system"]["version"]),
        },
        "servers": [{"url": catalog["base_url"]}],
        "paths": paths,
    }


def api_docs_html(title: str) -> str:
    catalog = api_catalog_result()
    rows: list[str] = []
    for group in catalog["groups"]:
        rows.append(f"<h2>{html.escape(str(group.get('label', '')))}</h2>")
        rows.append(f"<p>{html.escape(str(group.get('description', '')))}</p>")
        rows.append("<table><thead><tr><th>方法</th><th>路径</th><th>用途</th><th>只读</th></tr></thead><tbody>")
        for endpoint in group.get("endpoints", []):
            if not isinstance(endpoint, dict):
                continue
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(str(endpoint.get('method', '')))}</code></td>"
                f"<td><code>{html.escape(str(endpoint.get('path', '')))}</code></td>"
                f"<td>{html.escape(str(endpoint.get('purpose', '')))}</td>"
                f"<td>{'是' if endpoint.get('read_only') else '否'}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
    safety_items = "".join(f"<li>{html.escape(text)}</li>" for text in catalog["safety"]["boundaries"])
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      body {{ margin: 0; padding: 24px; background: #f5f7f6; color: #17211f; font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif; }}
      main {{ max-width: 1120px; margin: 0 auto; }}
      h1 {{ font-size: 1.6rem; }}
      h2 {{ margin-top: 28px; font-size: 1.1rem; }}
      a, code {{ color: #047d73; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #fff; }}
      th, td {{ padding: 10px; border: 1px solid #d9e1dd; text-align: left; vertical-align: top; }}
      th {{ background: #eef4f1; }}
      li {{ margin: 6px 0; }}
    </style>
  </head>
  <body>
    <main>
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(str(catalog["system"]["description"]))} base_url: <code>{html.escape(str(catalog["base_url"]))}</code></p>
      <p><a href="/api">/api</a> · <a href="/openapi.json">/openapi.json</a> · <a href="/">Web 首页</a></p>
      <h2>安全边界</h2>
      <ul>{safety_items}</ul>
      {''.join(rows)}
    </main>
  </body>
</html>"""


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
    path = latest_matching_file("market_analysis_*.md")
    if not path:
        return {"available": False, "kind": "market_analysis", "error": "market_analysis_*.md not found"}
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


def latest_model_validation_result() -> dict[str, object]:
    json_path = DATA_DIR / "model_validation_latest.json"
    markdown_path = DATA_DIR / "model_validation_latest.md"
    if not json_path.exists() or not markdown_path.exists():
        return {
            "available": False,
            "kind": "model_validation",
            "error": "model validation report has not been generated",
        }
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    markdown = markdown_path.read_text(encoding="utf-8-sig")
    return {
        "available": bool(payload.get("available")),
        "kind": "model_validation",
        "endpoint": "/api/research/latest/model-validation",
        "metadata": {
            "json": file_meta(json_path),
            "markdown": file_meta(markdown_path),
        },
        "payload": payload,
        "format": "text/markdown",
        "content": markdown,
    }


def latest_model_health_result() -> dict[str, object]:
    try:
        import calibration_trigger

        records = score_records(include_legacy=True)
        payload = calibration_trigger.evaluate_calibration_trigger(records)
        return {
            "available": bool(payload.get("available")),
            "kind": "model_health",
            "endpoint": "/api/research/latest/model-health",
            "payload": payload,
        }
    except Exception as exc:
        return {
            "available": False,
            "kind": "model_health",
            "endpoint": "/api/research/latest/model-health",
            "error": str(exc),
            "type": exc.__class__.__name__,
        }


def latest_strategy_robustness_result() -> dict[str, object]:
    try:
        import robustness_score

        records = score_records(include_legacy=True)
        payload = robustness_score.compute_robustness(records)
        return {
            "available": bool(payload.get("available")),
            "kind": "strategy_robustness",
            "endpoint": "/api/research/latest/strategy-robustness",
            "payload": payload,
        }
    except Exception as exc:
        return {
            "available": False,
            "kind": "strategy_robustness",
            "endpoint": "/api/research/latest/strategy-robustness",
            "error": str(exc),
            "type": exc.__class__.__name__,
        }


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
            "model_validation": "/api/research/latest/model-validation",
            "model_health": "/api/research/latest/model-health",
            "strategy_robustness": "/api/research/latest/strategy-robustness",
            "score_history": "/api/history",
            "score_history_with_legacy": "/api/history?include_legacy=true",
        },
        "results": {
            "service": service_version_result(),
            "market_snapshot": latest_market_snapshot_result(),
            "market_score": latest_market_score_result(),
            "market_analysis": latest_market_analysis_result(),
            "model_validation": latest_model_validation_result(),
            "model_health": latest_model_health_result(),
            "strategy_robustness": latest_strategy_robustness_result(),
        },
    }


def current_version_filter() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "position_policy_version": POSITION_POLICY_VERSION,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
    }


def record_matches_current_version(record: dict[str, object]) -> bool:
    return score_record_is_current_schema(record)


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


LEGACY_ALLOCATION_MAPPING = {
    "beta_core": ["core_wide_etf"],
    "alpha_active": ["mainline_etf", "leader_alpha"],
    "defensive_factor": ["defensive_quality"],
    "liquidity": ["cash_like"],
}


def parse_range_bounds(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str) or "-" not in value:
        return None
    try:
        left, right = value.replace("%", "").split("-", 1)
        return float(left), float(right)
    except ValueError:
        return None


def format_range_bounds(low: float, high: float) -> str:
    if low > high:
        low, high = high, low
    return f"{round(max(0, min(100, low)))}%-{round(max(0, min(100, high)))}%"


def convert_legacy_sleeves_for_display(policy: dict[str, object]) -> list[dict[str, object]]:
    sleeves = policy.get("sleeves") if isinstance(policy, dict) else []
    if not isinstance(sleeves, list):
        return []
    sleeve_by_key = {str(item.get("key")): item for item in sleeves if isinstance(item, dict) and item.get("key")}
    if all(key in sleeve_by_key for key in ALLOCATION_SLEEVE_ORDER):
        return [sleeve_by_key[key] for key in ALLOCATION_SLEEVE_ORDER]

    meta = {
        "beta_core": ("β核心仓（宽基ETF）", "宽基ETF", "市场β底盘"),
        "alpha_active": ("α主动仓（行业ETF + 龙头个股）", "主线行业ETF/龙头个股", "主动超额收益"),
        "defensive_factor": ("防御因子仓（红利/低波/自由现金流）", "红利低波/自由现金流/质量因子", "权益防御与质量暴露"),
        "liquidity": ("流动性仓（货币/短债）", "货币/短债/现金管理", "等待权与回撤缓冲"),
    }
    converted: list[dict[str, object]] = []
    for key in ALLOCATION_SLEEVE_ORDER:
        source_keys = LEGACY_ALLOCATION_MAPPING[key]
        source_items = [sleeve_by_key[source_key] for source_key in source_keys if source_key in sleeve_by_key]
        bounds = [parse_range_bounds(item.get("target_range")) for item in source_items]
        clean_bounds = [item for item in bounds if item is not None]
        midpoint = sum(number_or_none(item.get("midpoint")) or 0 for item in source_items) if source_items else None
        if clean_bounds:
            target_range = format_range_bounds(sum(item[0] for item in clean_bounds), sum(item[1] for item in clean_bounds))
        else:
            target_range = source_items[0].get("target_range") if source_items else None
        label, asset, role = meta[key]
        converted.append(
            {
                "key": key,
                "label": label,
                "name": label,
                "asset": asset,
                "role": role,
                "driver": "由旧 allocation_policy_v1 映射到四仓展示。",
                "examples": [],
                "target_range": target_range,
                "midpoint": round(midpoint, 2) if midpoint is not None else None,
                "legacy_source_keys": source_keys,
            }
        )
    return converted


def allocation_policy_for_display(policy: dict[str, object]) -> dict[str, object]:
    if not isinstance(policy, dict) or not policy:
        return {}
    displayed = dict(policy)
    displayed["display_version"] = ALLOCATION_POLICY_VERSION
    displayed["display_mapping"] = "allocation_policy_v2" if policy.get("version") == ALLOCATION_POLICY_VERSION else "legacy_v1_to_v2"
    displayed["sleeves"] = convert_legacy_sleeves_for_display(policy)
    if not displayed.get("risk_asset_formula"):
        displayed["risk_asset_formula"] = "beta_core + alpha_active + defensive_factor"
    if not displayed.get("liquidity_formula"):
        displayed["liquidity_formula"] = "100% - total_risk_asset_range"
    return displayed


def allocation_policy_result(latest: dict[str, object], records: list[dict[str, object]] | None = None) -> dict[str, object]:
    raw_policy = latest.get("allocation_policy") if isinstance(latest.get("allocation_policy"), dict) else {}
    policy = allocation_policy_for_display(raw_policy)
    sleeves = policy.get("sleeves") if isinstance(policy, dict) else []
    if not isinstance(sleeves, list):
        sleeves = []

    history = []
    for record in records or []:
        raw_allocation = record.get("allocation_policy") if isinstance(record.get("allocation_policy"), dict) else {}
        allocation = allocation_policy_for_display(raw_allocation)
        record_sleeves = allocation.get("sleeves") if isinstance(allocation, dict) else []
        if not isinstance(record_sleeves, list):
            record_sleeves = []
        sleeve_values = {
            str(item.get("key")): {
                "target_range": item.get("target_range"),
                "midpoint": item.get("midpoint"),
            }
            for item in record_sleeves
            if isinstance(item, dict) and item.get("key")
        }
        history.append(
            {
                "basis_trade_date": record.get("basis_trade_date"),
                "scored_at": record.get("scored_at"),
                "state": allocation.get("state"),
                "market_position_score": record.get("market_position_score"),
                "sleeves": sleeve_values,
            }
        )

    return {
        "available": bool(policy),
        "title": "股票账户四仓配置",
        "version": policy.get("version") or ALLOCATION_POLICY_VERSION,
        "display_version": policy.get("display_version") or ALLOCATION_POLICY_VERSION,
        "display_mapping": policy.get("display_mapping"),
        "account_scope": policy.get("account_scope") or "stock_account",
        "state": policy.get("state"),
        "total_risk_asset_range": policy.get("total_risk_asset_range") or recommended_equity_position_range(latest),
        "risk_asset_formula": policy.get("risk_asset_formula"),
        "liquidity_formula": policy.get("liquidity_formula"),
        "alpha_active_components": policy.get("alpha_active_components") if isinstance(policy.get("alpha_active_components"), dict) else {},
        "principles": policy.get("principles", []) if isinstance(policy.get("principles"), list) else [],
        "score_inputs": policy.get("score_inputs", {}) if isinstance(policy.get("score_inputs"), dict) else {},
        "sleeves": sleeves,
        "triggers": policy.get("triggers", []) if isinstance(policy.get("triggers"), list) else [],
        "notes": policy.get("notes", []) if isinstance(policy.get("notes"), list) else [],
        "history": history,
    }


def allocation_sleeve_midpoint(record: dict[str, object], key: str) -> object:
    allocation = record.get("allocation_policy") if isinstance(record.get("allocation_policy"), dict) else {}
    displayed = allocation_policy_for_display(allocation)
    sleeves = displayed.get("sleeves") if isinstance(displayed, dict) else []
    if not isinstance(sleeves, list):
        return None
    for sleeve in sleeves:
        if isinstance(sleeve, dict) and sleeve.get("key") == key:
            return sleeve.get("midpoint")
    return None


def number_or_none(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def format_score_value(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def market_cycle_profile_result(record: dict[str, object] | None) -> dict[str, object]:
    if not record:
        return {
            "available": False,
            "label": "暂无评分特征",
            "is_wave_prediction": False,
            "message": "没有最新评分记录，暂不能生成周期特征参照。",
            "reference_waves": [],
            "observations": [],
        }

    opportunity = number_or_none(record.get("market_opportunity_score"))
    position = number_or_none(record.get("market_position_score"))
    pre_cap = number_or_none(record.get("pre_cap_market_position_score"))
    crowding = number_or_none(record.get("crowding_penalty")) or 0
    gap = opportunity - position if opportunity is not None and position is not None else None
    risk_caps = record.get("risk_caps", [])
    risk_cap_items = risk_caps if isinstance(risk_caps, list) else []
    risk_cap_reasons = {str(item.get("reason")) for item in risk_cap_items if isinstance(item, dict) and item.get("reason")}
    top_risk_reasons = {
        "bubble_top_combo",
        "extreme_expensive_valuation",
        "expensive_valuation",
        "volume_blowoff_top",
        "sector_concentration_top",
        "high_crowding_extreme",
        "high_crowding",
    }
    high_volatility_reasons = {"extreme_high_volatility", "high_volatility"}

    if opportunity is not None and position is not None and position >= 80 and opportunity >= 70 and crowding < 10 and not (risk_cap_reasons & top_risk_reasons):
        label = "健康主升特征"
        reference_waves = ["3"]
        stance = "股票账户可保持高仓位，但仍要跟踪宽度和资金是否同步。"
        message = "机会分和仓位分同时处于高位，说明趋势、宽度、资金或主线质量较好，且风险上限没有明显压制。"
    elif opportunity is not None and position is not None and opportunity >= 60 and position <= 45 and ((risk_cap_reasons & top_risk_reasons) or (gap is not None and gap >= 20) or crowding >= 12):
        label = "高位过热风控特征"
        reference_waves = ["5", "b"]
        stance = "不追高扩仓，优先检查估值、波动、拥挤和资金退潮风险。"
        message = "机会分仍不低，但最终仓位分被明显压低，说明模型认为行情可看见，但风险收益不适合重仓。"
    elif opportunity is not None and position is not None and opportunity <= 45 and position <= 40:
        label = "悲观出清观察特征"
        reference_waves = ["c"]
        stance = "底部区间只做观察和分批确认，不因便宜直接满仓。"
        message = "机会分和仓位分都低，通常对应趋势、资金、宽度尚未确认的悲观阶段。"
    elif opportunity is not None and position is not None and 35 <= opportunity <= 60 and 35 <= position <= 70 and (gap is None or gap <= 15):
        label = "底部修复或回踩确认特征"
        reference_waves = ["1", "2"]
        stance = "可以关注修复是否持续，仓位随宽度和资金确认逐步提升。"
        message = "市场已经脱离极弱区，但趋势和资金质量还没有进入强共振。"
    elif opportunity is not None and position is not None and opportunity >= 55 and 50 <= position <= 80:
        label = "中继调整或结构趋势特征"
        reference_waves = ["4"]
        stance = "维持中高仓位，重点检查调整是否破坏宽度和主线。"
        message = "机会分和仓位分处在中高区，行情有延续基础，但还不是低拥挤强趋势满仓状态。"
    elif opportunity is not None and position is not None and opportunity >= 45 and position <= 45:
        label = "反抽但风控压制特征"
        reference_waves = ["a", "b"]
        stance = "把反弹当作验证窗口，不把短期修复直接等同为新主升。"
        message = "机会分有修复，但仓位分仍低，说明反弹质量或风险约束不足。"
    else:
        label = "中性震荡特征"
        reference_waves = ["2", "4"]
        stance = "按结构性机会处理，等待趋势、宽度、资金或估值给出更清晰确认。"
        message = "当前分数组合没有落入极端底部、健康主升或泡沫顶部的典型区间。"

    observations = [
        f"机会分 {format_score_value(opportunity)}，最终仓位分 {format_score_value(position)}。",
    ]
    if pre_cap is not None and position is not None and pre_cap > position:
        if risk_cap_items:
            observations.append(f"扣上限前仓位分 {format_score_value(pre_cap)}，风险上限后降至 {format_score_value(position)}。")
        else:
            observations.append(f"扣上限前仓位分 {format_score_value(pre_cap)}，最终执行仓位分为 {format_score_value(position)}。")
    if gap is not None:
        observations.append(f"机会分与仓位分差值 {format_score_value(gap)}，差值越大越说明风险约束在主导仓位。")
    if risk_cap_items:
        risk_cap_labels = [RISK_CAP_LABELS.get(reason, reason) for reason in sorted(risk_cap_reasons)]
        observations.append(f"已触发 {len(risk_cap_items)} 项风险上限：{'、'.join(risk_cap_labels)}。")
    elif risk_cap_reasons & high_volatility_reasons:
        observations.append("波动率风险上限正在压制仓位。")
    else:
        observations.append("未触发风险上限，仓位主要由机会分和拥挤惩罚决定。")

    return {
        "available": True,
        "label": label,
        "is_wave_prediction": False,
        "reference_waves": reference_waves,
        "score_line": f"机会 {format_score_value(opportunity)} / 仓位 {format_score_value(position)}",
        "opportunity_score": opportunity,
        "market_position_score": position,
        "pre_cap_market_position_score": pre_cap,
        "crowding_penalty": crowding,
        "opportunity_position_gap": gap,
        "risk_cap_reasons": sorted(risk_cap_reasons),
        "message": message,
        "stance": stance,
        "observations": observations,
        "note": "这是当前评分特征参照，不判定当前处于某个具体浪位。",
    }


def market_cycle_reference_result(latest: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "title": "市场八浪周期与评分区间",
        "kind": "cycle_reference",
        "is_prediction": False,
        "basis": "示意图只解释模型在不同周期位置的典型评分反应，不用于预测当前浪位。",
        "score_fields": {
            "market_opportunity_score": "市场机会分，衡量行情机会质量。",
            "market_position_score": "最终仓位分，扣除拥挤惩罚并经过风险上限后的股票账户仓位分。",
        },
        "waves": MARKET_CYCLE_REFERENCE,
        "current_profile": market_cycle_profile_result(latest),
    }


def history_api_result(include_legacy: bool = False) -> dict[str, object]:
    history = filtered_history(load_history(DEFAULT_HISTORY_PATH), include_legacy=include_legacy)
    return {
        "api_version": 2,
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "position_policy_version": POSITION_POLICY_VERSION,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
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
    allocation_map = allocation_policy_result(latest, records)

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
        "allocation_policy_version": latest.get("allocation_policy_version", ALLOCATION_POLICY_VERSION) if latest else ALLOCATION_POLICY_VERSION,
        "stable_release": stable_release_result(),
        "page": {
            "path": "/",
            "title": "A股市场评分",
            "model_line": f"{latest.get('model_version', MODEL_VERSION)} · {latest.get('scored_at', '--')}" if latest else MODEL_VERSION,
            "primary_action": {"label": "记录当前评分", "method": "POST", "endpoint": "/api/score"},
        },
        "summary": {
            "basis_trade_date": latest.get("basis_trade_date"),
            "run_id": latest.get("run_id"),
            "market_position_score": latest.get("market_position_score"),
            "market_opportunity_score": latest.get("market_opportunity_score"),
            "crowding_penalty": latest.get("crowding_penalty"),
            "risk_penalty_score": latest.get("risk_penalty_score"),
            "risk_discount": latest.get("risk_discount"),
            "risk_adjusted_market_position_score": latest.get("risk_adjusted_market_position_score"),
            "risk_engine": latest.get("risk_engine", {}),
            "position_model": latest.get("position_model", {}),
            "decision_explain": latest.get("decision_explain", {}),
            "shanghai_composite": latest.get("shanghai_composite"),
            "market_regime": latest.get("market_regime"),
            "market_regime_code": latest.get("market_regime_code"),
            "market_regime_label": latest.get("market_regime_label"),
            "market_regime_layer": latest.get("market_regime_layer", {}),
            "trend_state": latest.get("trend_state"),
            "trend_state_label": latest.get("trend_state_label"),
            "trend_strength": latest.get("trend_strength"),
            "trend_duration": latest.get("trend_duration"),
            "market_trend_layer": latest.get("market_trend_layer", {}),
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
            "allocation_policy_version": latest.get("allocation_policy_version", ALLOCATION_POLICY_VERSION),
            "allocation_state": latest.get("allocation_state") or allocation_map.get("state"),
            "allocation_policy": latest.get("allocation_policy", {}),
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
                    "id": "risk_penalty_score",
                    "label": "连续风险分",
                    "value": latest.get("risk_penalty_score"),
                    "max": 100,
                    "detail": latest.get("risk_engine", {}).get("risk_level") if isinstance(latest.get("risk_engine"), dict) else None,
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
                    "detail": latest.get("market_regime_label") or latest.get("confidence"),
                },
                {
                    "id": "trend_state",
                    "label": "趋势结构",
                    "value": latest.get("trend_state_label"),
                    "max": 100,
                    "detail": f"{latest.get('trend_strength')} / {latest.get('trend_duration')}日",
                },
            ],
        },
        "risk_overview": risk_overview_result(latest),
        "state_stability": validate_state_stability(records),
        "api_status": {
            "label": "最新研究结果 API",
            "available_count": sum(1 for available in api_available.values() if available),
            "total_count": len(api_available),
            "items": api_available,
            "endpoints": latest_research.get("endpoints", {}),
        },
        "api_catalog": api_catalog_summary_result(),
        "position_policy_map": policy_map,
        "position_map": {**policy_map, "legacy_alias_of": "position_policy_map"},
        "allocation_policy": allocation_map,
        "market_cycle_reference": market_cycle_reference_result(latest),
        "allocation_chart": {
            "title": "四仓配置历史",
            "record_count": len(records),
            "series": {
                key: [
                    {
                        "basis_trade_date": row.get("basis_trade_date"),
                        "scored_at": row.get("scored_at"),
                        "value": allocation_sleeve_midpoint(row, key),
                    }
                    for row in records
                ]
                for key in ALLOCATION_SLEEVE_ORDER
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
                    "risk_penalty_score": row.get("risk_penalty_score"),
                    "risk_discount": row.get("risk_discount"),
                    "risk_adjusted_market_position_score": row.get("risk_adjusted_market_position_score"),
                    "position_model_version": (row.get("position_model") or {}).get("version") if isinstance(row.get("position_model"), dict) else None,
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
                    "market_regime_code": row.get("market_regime_code"),
                    "market_regime_label": row.get("market_regime_label"),
                    "trend_state": row.get("trend_state"),
                    "trend_state_label": row.get("trend_state_label"),
                    "trend_strength": row.get("trend_strength"),
                    "trend_duration": row.get("trend_duration"),
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
            "latest_model_validation": "/api/research/latest/model-validation",
            "latest_model_health": "/api/research/latest/model-health",
            "latest_strategy_robustness": "/api/research/latest/strategy-robustness",
        },
    }


class MarketWebHandler(BaseHTTPRequestHandler):
    server_version = "MyInvestMarketWeb/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == "/api":
                self.send_json(api_catalog_result())
                return
            if path == "/openapi.json":
                self.send_json(openapi_result())
                return
            if path == "/docs":
                self.send_html(api_docs_html("MyInvestMarket API 文档"))
                return
            if path == "/redoc":
                self.send_html(api_docs_html("MyInvestMarket API Redoc"))
                return
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
            if path == "/api/research/latest/model-validation":
                self.send_json(latest_model_validation_result())
                return
            if path == "/api/research/latest/model-health":
                self.send_json(latest_model_health_result())
                return
            if path == "/api/research/latest/strategy-robustness":
                self.send_json(latest_strategy_robustness_result())
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

    def send_html(self, content: str, status: int = 200) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
