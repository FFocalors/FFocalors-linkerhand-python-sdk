# ADR 0001: Python owns the LinkerHand SDK lifecycle

Status: accepted

The Python sidecar owns SDK construction, connection, and teardown. A single
worker thread serializes every hardware call. Rust speaks only the documented
NDJSON contract and does not import Python SDK modules. This isolates legacy SDK
prints and exceptions, provides deterministic fake mode, and leaves product
state/visualization outside the hardware boundary.
