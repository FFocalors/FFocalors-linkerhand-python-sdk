#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom11_server.py

轻量 HTTP Server，接收 custom_11 关键点并缓存最新一帧。

使用 Python 标准库 http.server，不新增依赖。
不做硬件控制。

接口：
    GET  /health      - 健康检查
    POST /keypoints   - 接收 custom_11 关键点
    GET  /latest      - 返回最新一帧
"""
import argparse
import json
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from custom11_stream_reader import Custom11StreamReader


class _KeypointHandler(BaseHTTPRequestHandler):
    """共享 reader 实例通过 server.reader 注入。"""

    def _json_response(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log_request(self, method, info=""):
        print(f"[custom11_server] {method} {self.path} from {self.client_address[0]} {info}")

    def do_GET(self):
        if self.path == "/health":
            self._log_request("GET")
            self._json_response(200, {"ok": True, "service": "custom11_server", "mode": "dry-run"})
        elif self.path == "/latest":
            self._log_request("GET")
            frame = self.server.reader.get_latest_frame()
            if frame is None:
                self._json_response(200, {"ok": True, "fresh": False, "message": "no fresh frame"})
            else:
                status = self.server.reader.get_status()
                self._json_response(200, {
                    "ok": True, "fresh": True,
                    "age_sec": status.get("age_sec", -1),
                    "frame": frame,
                })
        else:
            self._json_response(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        if self.path != "/keypoints":
            self._json_response(404, {"ok": False, "message": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._json_response(400, {"ok": False, "message": f"invalid JSON: {exc}"})
            return

        result = self.server.reader.update_frame(payload)
        code = 200 if result["ok"] else 400
        kp_count = result.get("keypoints_count", 0)
        info = f"ok={result['ok']}, kps={kp_count}, msg={result['message']}"
        self._log_request("POST", info)
        if result["ok"]:
            print(f"[custom11_server] frame updated. keypoints={kp_count}, "
                  f"hand={payload.get('hand','n/a')}, source={payload.get('source','n/a')}")
        self._json_response(code, result)


def main():
    parser = argparse.ArgumentParser(description="custom11 HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    parser.add_argument("--max-age-sec", type=float, default=1.0, help="frame max age in seconds")
    args = parser.parse_args()

    reader = Custom11StreamReader(max_age_sec=args.max_age_sec)
    server = HTTPServer((args.host, args.port), _KeypointHandler)
    server.reader = reader  # 注入

    print(f"[custom11_server] listening on http://{args.host}:{args.port}")
    print(f"[custom11_server] endpoints: GET /health  POST /keypoints  GET /latest")
    print(f"[custom11_server] max_age_sec={args.max_age_sec}")
    print("[custom11_server] dry-run mode. No hardware control.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[custom11_server] shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
