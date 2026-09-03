from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serve_market_web  # noqa: E402


def test_dashboard_result_is_compact_and_has_decision_layers() -> None:
    payload = serve_market_web.dashboard_result()

    assert payload["available"] is True
    assert payload["summary"]["basis_trade_date"]
    assert payload["summary"]["recommended_equity_position_range"]
    assert payload["cycle"]["latest"]["latest_state"]
    assert payload["allocation"]["sleeves"]
    assert len(payload["recent_chart"]["records"]) <= 90
    assert len(payload["cycle"].keys()) == 3
    assert len(payload["quick_links"]) == 6


def test_dashboard_is_catalogued_as_read_only() -> None:
    catalog = serve_market_web.api_catalog_result()
    endpoints = [endpoint for group in catalog["groups"] for endpoint in group["endpoints"]]
    dashboard = next(endpoint for endpoint in endpoints if endpoint["path"] == "/api/dashboard")

    assert dashboard["method"] == "GET"
    assert dashboard["read_only"] is True


def test_cycle_evidence_explains_candidate_hold_and_position_mapping() -> None:
    payload = serve_market_web.cycle_engine_evidence_result()

    assert payload["available"] is True
    assert payload["basis_month"] == "2026-08"
    assert payload["latest"]["candidate"]["candidate_state"] == "ambiguous"
    assert payload["latest"]["state_machine"]["stable_state"] == "late_bull"
    assert payload["latest"]["state_machine"]["transition_status"] == "held_ambiguous"
    assert payload["latest"]["policy"]["equity_min_pct"] == 60
    assert payload["latest"]["policy"]["equity_max_pct"] == 80
    assert payload["algorithm"]["candidate_rules"]
    assert payload["algorithm"]["state_machine_rules"]
    assert payload["latest"]["selected_features"]
    assert all(item["pit_date"] <= payload["basis_trade_date"] for item in payload["latest"]["selected_features"] if item["pit_date"])


def test_cycle_evidence_endpoint_is_catalogued_read_only() -> None:
    endpoints = [endpoint for group in serve_market_web.api_catalog_result()["groups"] for endpoint in group["endpoints"]]
    evidence = next(endpoint for endpoint in endpoints if endpoint["path"] == "/api/cycle-engine/evidence")

    assert evidence["method"] == "GET"
    assert evidence["read_only"] is True


def test_homepage_is_decision_first_and_links_to_detail_workbenches() -> None:
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    assert 'src="/dashboard.js"' in html
    assert 'src="/app.js"' not in html
    for path in ("research.html", "risk.html", "cycle.html", "allocation.html", "cycle-engine-backtest.html", "methodology.html"):
        assert f'href="/{path}"' in html
    assert "fear-band" in html
    assert 'id="fearChart"' in html
    assert "不是买入分" in html


def test_detail_pages_share_portal_shell() -> None:
    for page in ("research", "risk", "cycle", "allocation", "methodology"):
        html = (ROOT / f"web/{page}.html").read_text(encoding="utf-8")
        assert 'rel="stylesheet" href="/portal.css"' in html
        assert 'src="/portal.js"' in html
        assert 'href="/"' in html


def test_cycle_page_contains_evidence_sections_and_endpoint() -> None:
    html = (ROOT / "web/cycle.html").read_text(encoding="utf-8")

    for marker in ("当前状态使用的四个输入域", "实际输入与标准化结果", "候选状态判定顺序", "稳定状态确认逻辑", "最近状态轨迹"):
        assert marker in html
    assert "/api/cycle-engine/evidence" in html
    assert 'src="/portal.js"' in html
    assert 'id="cyclePositionPolicyChart"' in html
    assert "七种稳定状态的权益仓位路径" in html
