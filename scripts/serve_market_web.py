from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from market_scoring import (
    DEFAULT_HISTORY_PATH,
    DEFAULT_SNAPSHOT_PATH,
    MODEL_VERSION,
    ROOT,
    append_score,
    load_history,
)


WEB_DIR = ROOT / "web"
PORT = 8011


class MarketWebHandler(BaseHTTPRequestHandler):
    server_version = "MyInvestMarketWeb/1.0"

    def do_GET(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
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
