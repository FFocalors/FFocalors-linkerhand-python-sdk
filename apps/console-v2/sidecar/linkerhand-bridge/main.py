"""CLI entrypoint: ``python .../linkerhand-bridge/main.py [--fake]``."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from protocol import EnvelopeWriter, ProtocolError, validate_request
from services.service import SidecarService


def _request_id(value: Any) -> str:
    return value if isinstance(value, str) else ""


def run(stdin=None, stdout=None, stderr=None, *, fake: bool = False, sdk_root: str | None = None) -> int:
    # Capture these streams before SDK calls; writer never consults mutable sys.stdout.
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    writer = EnvelopeWriter(stdout, stderr)
    service = SidecarService(output=writer.sdk_output)
    try:
        for line in stdin:
            if not line.strip():
                continue
            request_id = ""
            operation = "error"
            try:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProtocolError("INVALID_JSON", f"invalid JSON: {exc.msg}") from exc
                request_id = _request_id(raw.get("requestId")) if isinstance(raw, dict) else ""
                request = validate_request(raw)
                request_id, operation, payload = request["requestId"], request["operation"], request["payload"]
                if operation == "connect":
                    payload = dict(payload)
                    if fake: payload.setdefault("mode", "fake")
                    if sdk_root: payload.setdefault("sdkRoot", sdk_root)
                result = service.submit(operation, payload)
                writer.emit(request_id=request_id, message_type="response", operation=operation, payload=result)
            except ProtocolError as exc:
                writer.emit(request_id=request_id, message_type="error", operation=operation, payload={"error": exc.as_payload()})
            except Exception as exc:
                writer.emit(request_id=request_id, message_type="error", operation=operation, payload={"error": {"code": "INTERNAL_ERROR", "message": str(exc), "retryable": True}})
            if service.closing:
                break
    finally:
        service.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LinkerHand Console V2 SDK sidecar")
    parser.add_argument("--fake", action="store_true", help="use deterministic fake SDK")
    parser.add_argument("--sdk-root", help="directory containing the LinkerHand SDK")
    args = parser.parse_args(argv)
    return run(fake=args.fake, sdk_root=args.sdk_root)


if __name__ == "__main__":
    raise SystemExit(main())
