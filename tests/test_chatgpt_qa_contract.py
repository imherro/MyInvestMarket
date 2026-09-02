from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serve_market_web  # noqa: E402


def test_chatgpt_qa_history_has_structured_latest_record() -> None:
    payload = serve_market_web.chatgpt_qa_history_result()
    assert payload["available"] is True
    assert payload["record_count"] >= 1
    latest = payload["latest"]
    for key in ("basis_trade_date", "period_stage", "confidence", "position_pct", "action", "directions", "avoid_directions", "answer_markdown"):
        assert key in latest
    assert payload["storage"]["notion_sync"] is False
    assert payload["storage"]["append_only_by_record_id"] is True
    if payload["latest"].get("source_type") == "chatgpt_web":
        assert payload["latest"].get("source_url", "").startswith("https://chatgpt.com/")
    else:
        assert payload["latest"].get("source_type") == "local_post_close"
    assert len(payload["latest"]["answer_markdown"]) > 1000


def test_chatgpt_qa_endpoints_are_read_only_and_catalogued() -> None:
    endpoints = {
        endpoint["path"]: endpoint
        for group in serve_market_web.api_catalog_result()["groups"]
        for endpoint in group["endpoints"]
    }
    for path in ("/api/chatgpt-qa/latest", "/api/chatgpt-qa/history"):
        assert endpoints[path]["method"] == "GET"
        assert endpoints[path]["read_only"] is True


def test_chatgpt_qa_page_and_homepage_entrypoint_exist() -> None:
    page = (ROOT / "web/chatgpt-qa.html").read_text(encoding="utf-8")
    home = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert 'data-page="chatgpt-qa"' in page
    assert "/api/chatgpt-qa/history" in page
    assert 'href="/chatgpt-qa.html"' in home


def test_chatgpt_qa_json_is_valid() -> None:
    payload = json.loads((ROOT / "data/chatgpt_qa_history.json").read_text(encoding="utf-8"))
    assert payload["question_id"] == "a_share_daily_research_v1"
    assert payload["records"]
