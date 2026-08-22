"""Run the fake bridge through its real NDJSON subprocess boundary.

This deliberately checks stdout as a protocol stream, rather than calling
Python functions in-process. It catches SDK logging accidentally leaking into
stdout and validates that the bundled entrypoint can be replaced by an exe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, help="packaged sidecar executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    script = root / "sidecar" / "linkerhand-bridge" / "main.py"
    command = [str(args.executable), "--fake"] if args.executable else [sys.executable, str(script), "--fake"]
    requests = [
        {"schemaVersion": 1, "messageType": "command", "requestId": "smoke-1", "sequence": 1, "monotonicTimeMs": 1, "operation": "connect", "payload": {"deviceId": "smoke", "model": "L10", "hand": "left", "transport": {"type": "can", "channel": "fake"}, "mode": "fake"}},
        {"schemaVersion": 1, "messageType": "command", "requestId": "smoke-2", "sequence": 2, "monotonicTimeMs": 2, "operation": "getTelemetry", "payload": {}},
        {"schemaVersion": 1, "messageType": "command", "requestId": "smoke-3", "sequence": 3, "monotonicTimeMs": 3, "operation": "close", "payload": {}},
    ]
    process = subprocess.run(
        command,
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if process.returncode != 0:
        raise SystemExit(f"sidecar exited {process.returncode}: {process.stderr}")
    lines = process.stdout.splitlines()
    if len(lines) != len(requests):
        raise SystemExit(f"expected {len(requests)} stdout envelopes, got {len(lines)}: {process.stdout!r}")
    responses = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"stdout contamination or invalid JSON: {line!r}") from exc
        if value.get("messageType") not in {"response", "error"}:
            raise SystemExit(f"unexpected sidecar message: {value!r}")
        responses.append(value)
    if any(value.get("messageType") == "error" for value in responses):
        raise SystemExit(f"fake smoke returned an error: {responses!r}")
    if [value.get("requestId") for value in responses] != [request["requestId"] for request in requests]:
        raise SystemExit(f"request IDs were not echoed: {responses!r}")
    print(f"sidecar NDJSON fake smoke passed ({len(responses)} envelopes; stdout is pure JSON)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
