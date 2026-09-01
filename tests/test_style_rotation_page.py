from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_style_rotation_page_assets_and_data_contract() -> None:
    html = (ROOT / "web" / "style-rotation-backtest.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "style-rotation-backtest.js").read_text(encoding="utf-8")
    payload = json.loads((ROOT / "web" / "data" / "style-rotation-history.json").read_text(encoding="utf-8"))

    assert "style-rotation-backtest.css" in html
    assert "style-rotation-backtest.js" in html
    assert "月末判断 / 次日执行" in html
    assert "pendingWeight" in script
    assert 'cashflow: { label: "100% 自由现金流"' in script
    assert 'technology: { label: "100% 科技成长"' in script
    assert payload["sample"]["sessions"] >= 100
    assert payload["observations"] == sorted(payload["observations"], key=lambda row: row["date"])
    assert all({"date", "cashflow", "technology", "a500", "csi300"} <= row.keys() for row in payload["observations"])
