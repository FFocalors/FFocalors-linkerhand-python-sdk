# Sidecar handoff

- Branch: `codex/v2-m1-sidecar`
- Commit: `a3aee4134649b73ff930488545017fff1db7cb68`
- Scope: `apps/console-v2/sidecar/linkerhand-bridge/`, protocol contract, ADR, and this handoff
- Public interface: new sidecar NDJSON interface only; legacy `LinkerHand` SDK unchanged
- Tests: `uv run --with pytest --python 3.12 python -m pytest apps/console-v2/sidecar/linkerhand-bridge/tests` (26 passed); default Python 3.9 had no pytest
- Unresolved: real hardware dependencies (CAN/pyserial) remain deployment inputs; run fake mode in CI
- Next entry: Rust sidecar-client launches `main.py` (or bundled executable), sends schemaVersion 1 envelopes, and consumes stderr separately
