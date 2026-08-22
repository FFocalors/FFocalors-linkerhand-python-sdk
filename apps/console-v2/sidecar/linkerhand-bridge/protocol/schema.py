"""Strict validation for the sidecar wire contract.

Requests intentionally accept only a small, explicit set of fields.  This makes
contract drift visible to the Rust client instead of silently ignoring typoed
configuration or capability names.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
OPERATIONS = frozenset({
    "connect", "disconnect", "capabilities", "getTelemetry", "getPosition",
    "getCurrent", "getSpeed", "getTouch", "setPosition", "setSpeed",
    "setCurrent", "setTorque", "stop", "close",
})
# The metadata fields are optional on input for convenient pipes, but accepted
# and validated when the Rust client sends a full envelope.
REQUEST_FIELDS = frozenset({"schemaVersion", "messageType", "requestId", "sequence", "monotonicTimeMs", "operation", "payload"})


@dataclass
class ProtocolError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def as_payload(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details:
            result["details"] = self.details
        return result


def _expect_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_REQUEST", f"{name} must be an object")
    return value


def validate_request(request: Any) -> dict[str, Any]:
    obj = _expect_object(request, "request")
    unknown = sorted(set(obj) - REQUEST_FIELDS)
    if unknown:
        raise ProtocolError("UNKNOWN_FIELD", "unknown request field(s)", details={"fields": unknown})
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        raise ProtocolError("SCHEMA_UNSUPPORTED", "schemaVersion must be 1", details={"schemaVersion": obj.get("schemaVersion")})
    request_id = obj.get("requestId")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise ProtocolError("INVALID_REQUEST", "requestId must be a non-empty string of at most 128 characters")
    operation = obj.get("operation")
    if operation not in OPERATIONS:
        raise ProtocolError("UNKNOWN_OPERATION", f"unsupported operation: {operation}")
    payload = obj.get("payload", {})
    _expect_object(payload, "payload")
    if "messageType" in obj and obj["messageType"] not in ("command", "request"):
        raise ProtocolError("INVALID_REQUEST", "messageType must be command or request")
    if "sequence" in obj and (isinstance(obj["sequence"], bool) or not isinstance(obj["sequence"], int) or obj["sequence"] < 0):
        raise ProtocolError("INVALID_REQUEST", "sequence must be a non-negative integer")
    if "monotonicTimeMs" in obj and (isinstance(obj["monotonicTimeMs"], bool) or not isinstance(obj["monotonicTimeMs"], (int, float))):
        raise ProtocolError("INVALID_REQUEST", "monotonicTimeMs must be numeric")
    return {"schemaVersion": SCHEMA_VERSION, "requestId": request_id, "operation": operation, "payload": payload}


def validate_vector(value: Any, expected: int, name: str, minimum: float = 0, maximum: float = 255) -> list[int | float]:
    if not isinstance(value, list) or len(value) != expected:
        raise ProtocolError("INVALID_ARGUMENT", f"{name} must contain exactly {expected} values", details={"expectedLength": expected})
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < minimum or item > maximum for item in value):
        raise ProtocolError("INVALID_ARGUMENT", f"{name} values must be between {minimum:g} and {maximum:g}")
    return value
