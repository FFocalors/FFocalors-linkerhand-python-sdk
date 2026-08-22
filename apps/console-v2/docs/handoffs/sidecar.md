# Sidecar handoff

- Branch: `codex/v2-m1-sidecar`
- Code commit: `c60caca54397ee372fbe02dd2c80a08b562748da` (handoff metadata follows in the next docs commit)
- Scope: `apps/console-v2/sidecar/linkerhand-bridge/`, protocol contract, ADR, and this handoff
- Public interface: new sidecar NDJSON interface only; legacy `LinkerHand` SDK unchanged
- Tests: `uv run --with pytest --python 3.12 python -m pytest apps/console-v2/sidecar/linkerhand-bridge/tests` (26 passed); default Python 3.9 had no pytest
- Audit: RealSdkAdapter now passes legacy `can`/`modbus` constructor keywords, uses `get_joint_speed` for public speed projection, and enforces per-model command lengths (including L20 current-only and five-value G20/L21/L25 torque boundaries). Pseudo-SDK tests verify constructor signatures, method calls, and stdout capture; subprocess tests verify bad JSON continuation and close exit.
- Unresolved: real hardware dependencies (CAN/pyserial) remain deployment inputs; run fake mode in CI
- Next entry: Rust sidecar-client launches `main.py` (or bundled executable), sends schemaVersion 1 envelopes, and consumes stderr separately
