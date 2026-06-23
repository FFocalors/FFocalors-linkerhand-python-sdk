#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom11_server.py

轻量 HTTP Server，接收/返回 custom_11 关键点，增加延迟信息。

接口:
    GET  /health /status /schema /latest[?max_age_sec=N]
    POST /keypoints
    OPTIONS *
"""
import argparse
import json
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from custom11_stream_reader import Custom11StreamReader
from custom11_keypoints import keypoint_schema, describe_custom11_order


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


class _KeypointHandler(BaseHTTPRequestHandler):

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for k, v in CORS_HEADERS.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self, method, info=""):
        print(f"[server] {method} {self.path} {info}")

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items(): self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]; qs = self._qs()
        if path == "/health":
            self._json(200, {"ok": True, "service": "custom11_server", "mode": "dry-run"})
        elif path == "/status":
            st = self.server.reader.get_status()
            if hasattr(self.server.reader, "_receive_timestamps"):
                ts_list = list(self.server.reader._receive_timestamps)
                if len(ts_list) >= 2:
                    st["receive_fps_estimate"] = round(
                        (len(ts_list)-1) / max(ts_list[-1]-ts_list[0], 0.001), 1)
            st["latest_age_sec"] = st.get("age_sec")
            self._json(200, {"ok": True, "status": st})
        elif path == "/schema":
            self._json(200, {"ok": True, "schema": keypoint_schema(), "order": describe_custom11_order()})
        elif path == "/latest":
            max_age = float(qs.get("max_age_sec", self.server.reader._max_age_sec))
            frame = self.server.reader.get_latest_frame(max_age_sec=max_age)
            if frame is None:
                self._json(200, {"ok": True, "fresh": False, "message": "no fresh frame"})
            else:
                st = self.server.reader.get_status()
                age = st.get("age_sec", -1)
                srt = self.server.reader._latest_server_recv if hasattr(self.server.reader, "_latest_server_recv") else time.time()
                client_ts = frame.get("timestamp", time.time())
                latency = round(max(0, srt - client_ts), 4) if srt and client_ts else -1
                self._json(200, {
                    "ok": True, "fresh": True,
                    "age_sec": age,
                    "latency_sec": latency,
                    "server_receive_time": round(srt, 4),
                    "client_timestamp": client_ts,
                    "frame": frame,
                })
        else:
            self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/keypoints":
            self._json(404, {"ok": False, "message": "not found"}); return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try: payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._json(400, {"ok": False, "message": f"invalid JSON: {exc}"}); return

        self.server.reader._latest_server_recv = time.time()
        if not hasattr(self.server.reader, "_receive_timestamps"):
            self.server.reader._receive_timestamps = []
        self.server.reader._receive_timestamps.append(time.time())
        if len(self.server.reader._receive_timestamps) > 60:
            self.server.reader._receive_timestamps.pop(0)

        result = self.server.reader.update_frame(payload)
        code = 200 if result["ok"] else 400
        self._log("POST", f"ok={result['ok']}, kps={result.get('keypoints_count',0)}")
        if result["ok"]:
            print(f"[server] frame updated. kps={result['keypoints_count']}, "
                  f"hand={payload.get('hand','n/a')}")
        self._json(code, result)

    def _qs(self):
        d = {}
        if "?" in self.path:
            for pair in self.path.split("?", 1)[1].split("&"):
                if "=" in pair: k, v = pair.split("=", 1); d[k] = v
        return d

    def log_message(self, *a): pass


def main():
    parser = argparse.ArgumentParser(description="custom11 HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-age-sec", type=float, default=1.0)
    args = parser.parse_args()

    reader = Custom11StreamReader(max_age_sec=args.max_age_sec)
    reader._latest_server_recv = time.time()
    reader._receive_timestamps = [time.time()]
    server = HTTPServer((args.host, args.port), _KeypointHandler)
    server.reader = reader

    print(f"[server] listening on http://{args.host}:{args.port}")
    print("[server] endpoints: GET /health /status /schema /latest  POST /keypoints")
    print(f"[server] max_age_sec={args.max_age_sec} | CORS enabled | dry-run")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n[server] shutting down."); server.shutdown()


if __name__ == "__main__":
    main()
