"""Pure stdout NDJSON writer.

The stream is captured before any SDK call so ``redirect_stdout`` in the worker
cannot contaminate protocol output.
"""
from __future__ import annotations

import json
import sys
import time
from threading import Lock
from typing import Any, TextIO


class EnvelopeWriter:
    def __init__(self, stream: TextIO | None = None, error_stream: TextIO | None = None):
        self.stream = stream if stream is not None else sys.stdout
        self.error_stream = error_stream if error_stream is not None else sys.stderr
        self._sequence = 0
        self._lock = Lock()

    @property
    def sequence(self) -> int:
        return self._sequence

    def emit(self, *, request_id: str, message_type: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            envelope = {
                "schemaVersion": 1,
                "messageType": message_type,
                "requestId": request_id,
                "sequence": self._sequence,
                "monotonicTimeMs": int(time.monotonic() * 1000),
                "operation": operation,
                "payload": payload,
            }
            self.stream.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.stream.flush()
            return envelope

    def sdk_output(self, text: str) -> None:
        if text:
            self.error_stream.write(text)
            self.error_stream.flush()
