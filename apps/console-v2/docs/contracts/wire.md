# Wire contract

All cross-process messages are one JSON object per NDJSON line, using stable camelCase names and `schemaVersion: 1`. The envelope fields are `messageType`, `requestId`, `sequence`, `monotonicTimeMs`, optional `operation`, and `payload`. Unknown schema versions are rejected at the sidecar boundary.
