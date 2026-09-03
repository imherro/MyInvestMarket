from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hithink_data


def test_index_history_converts_remote_rows(monkeypatch) -> None:
    payload = {
        "ok": True,
        "data": {
            "item": [
                {
                    "date_ms": 1788364800000,
                    "open_price": 3952.79,
                    "high_price": 3968.11,
                    "low_price": 3930.45,
                    "close_price": 3942.09,
                    "volume": 49699019000,
                    "turnover": 819882350000,
                }
            ]
        },
    }
    monkeypatch.setattr(hithink_data, "_cli", lambda: "hithink-finance")
    completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with patch.object(hithink_data.subprocess, "run", return_value=completed) as run:
        frame = hithink_data.index_history("000001.SH", date(2026, 9, 1), date(2026, 9, 3))

    assert list(frame["trade_date"]) == ["20260903"]
    assert frame.iloc[0]["close"] == 3942.09
    assert run.call_args.kwargs["timeout"] == 45
    assert "--end-ms" in run.call_args.args[0]


def test_special_pool_total_reads_pagination(monkeypatch) -> None:
    payload = {"ok": True, "data": {"pagination": {"total": 16}}}
    monkeypatch.setattr(hithink_data, "_cli", lambda: "hithink-finance")
    completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with patch.object(hithink_data.subprocess, "run", return_value=completed):
        assert hithink_data.special_pool_total("limit-down-pool", date(2026, 9, 3)) == 16


def test_run_rejects_failed_business_envelope(monkeypatch) -> None:
    monkeypatch.setattr(hithink_data, "_cli", lambda: "hithink-finance")
    completed = subprocess.CompletedProcess([], 0, json.dumps({"ok": False, "error": {"code": "AUTH"}}), "")
    with patch.object(hithink_data.subprocess, "run", return_value=completed):
        try:
            hithink_data.index_history("000001.SH", date(2026, 9, 1), date(2026, 9, 3))
        except RuntimeError as exc:
            assert "AUTH" in str(exc)
        else:
            raise AssertionError("expected failed business envelope to raise")
