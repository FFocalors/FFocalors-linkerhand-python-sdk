"""Drive the packaged sidecar over NDJSON against the real O6 (read-only).

Tests connect, getPosition, getCurrent, getSpeed, getTouch and getTelemetry
one by one and prints each raw envelope. No motion command is ever sent.

Requires PCAN to be free: close the Console V2 app first (a second process
cannot open the PCAN channel while the first still holds it).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "target" / "debug" / "linkerhand-sidecar.exe",
    )
    parser.add_argument("--channel", default="PCAN_USBBUS1")
    parser.add_argument("--model", default="O6")
    parser.add_argument("--hand", default="left")
    parser.add_argument("--source", action="store_true", help="run the bridge from source instead of the packaged exe")
    args = parser.parse_args()
    if args.source:
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root / "sidecar" / "linkerhand-bridge" / "main.py")]
    else:
        command = [str(args.executable)]
        if not args.executable.is_file():
            raise SystemExit(f"sidecar executable not found: {args.executable}")

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def drain_stderr() -> None:
        for line in process.stderr:  # type: ignore[union-attr]
            print(f"[sidecar-stderr] {line.rstrip()}", file=sys.stderr)

    threading.Thread(target=drain_stderr, daemon=True).start()

    sequence = 0

    def request(operation: str, payload: dict) -> dict:
        nonlocal sequence
        sequence += 1
        envelope = {
            "schemaVersion": 1,
            "messageType": "command",
            "requestId": f"probe-{sequence}",
            "sequence": sequence,
            "monotonicTimeMs": int(time.time() * 1000),
            "operation": operation,
            "payload": payload,
        }
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(envelope) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise SystemExit("sidecar closed stdout without a response")
        return json.loads(line)

    try:
        started = time.time()
        response = request("connect", {
            "deviceId": "probe-real-o6",
            "model": args.model,
            "hand": args.hand,
            "transport": {"type": "can", "channel": args.channel},
            "mode": "real",
        })
        print(f"connect ({time.time() - started:.1f}s): {json.dumps(response, ensure_ascii=False)[:600]}")
        if response.get("messageType") == "error":
            raise SystemExit(f"connect failed: {response['payload']}")

        for operation in ("getPosition", "getCurrent", "getSpeed", "getTouch", "getTelemetry"):
            started = time.time()
            response = request(operation, {})
            elapsed = time.time() - started
            kind = response.get("messageType")
            if kind == "error":
                payload = response.get("payload", {}).get("error", {})
                print(f"{operation} ({elapsed * 1000:.0f}ms): ERROR code={payload.get('code')} message={payload.get('message')!r}")
            else:
                print(f"{operation} ({elapsed * 1000:.0f}ms): {json.dumps(response.get('payload'), ensure_ascii=False)[:600]}")
    finally:
        try:
            request("close", {})
        except Exception:
            pass
        process.stdin.close()  # type: ignore[union-attr]
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
