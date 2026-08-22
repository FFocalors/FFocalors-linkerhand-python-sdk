"""NDJSON protocol primitives for the LinkerHand sidecar."""

from .schema import SCHEMA_VERSION, OPERATIONS, ProtocolError, validate_request
from .writer import EnvelopeWriter

__all__ = ["SCHEMA_VERSION", "OPERATIONS", "ProtocolError", "validate_request", "EnvelopeWriter"]
