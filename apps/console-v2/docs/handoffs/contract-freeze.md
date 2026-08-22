# Contract freeze handoff

- Branch: `codex/v2-m1-contract-freeze`
- Base: `1fea3fe` (`docs(console-v2): record M1 integration verification`)
- Final commit: `b2986c6` (`feat(console-v2): add raw vector adapter seam`)
- Contract commits, in order: `9e8334e` (canonical contract and generator), `6a768e6` (runtime/sidecar/UI seams), `22c9137` (normalized raw clamp), `b2986c6` (raw vector mapper).
- Worktree is clean at handoff.

## Responsibility

This branch freezes the Console V2 contract boundary and supplies the seams needed for later real integration:

- `crates/console-contracts` is the single Rust source for public DTOs, enums, envelope fields, model identity, transport tags, normalized positions, raw telemetry fields, and error DTOs.
- `frontend/shared/contracts/generated.ts` is generated from the Rust contract binary. `frontend/shared/contracts/index.ts` contains only UI Port composition and adapter-facing interfaces.
- `sidecar-client` validates strict NDJSON and provides `RawVectorMapper` for normalized position ↔ raw byte conversion.
- The Python sidecar validates raw model/transport/vector facts and implements the software stop barrier and explicit unlock.
- `app-runtime::ui` defines UI-facing facade Ports; `SidecarPort` remains an internal dependency.
- `docs/contracts/raw-capabilities.json` is the cross-language raw capability fixture for all eight supported models.

This branch does not claim to provide a real Tauri command/channel wiring, real camera/vision implementation, persistent action storage, hardware emergency-stop behavior, or a production SDK deployment bundle. The UI continues to use a deterministic mock runtime.

## Public interface changes

- Supported models are exactly `O6`, `L6`, `L7`, `L10`, `L20`, `G20`, `L21`, and `L25`; UI `L12` was removed.
- `DeviceConfig` now requires `deviceId`, `model`, `hand`, tagged `transport` (`can`/`rs485`), and `autoReconnect`.
- Public joint positions are complete normalized vectors in `0.0..=1.0`. UI renders percentages; raw SDK bytes are only exposed as explicitly named `rawPosition`, `rawCurrent`, `rawSpeed`, and `rawTouch` fields.
- `TelemetrySnapshot` no longer invents `temperatureC` or aggregate `currentMa`; unavailable capabilities must remain unavailable.
- `AppError` is `{code,message,retryable,details?}` across Rust/Python/UI boundaries.
- `SidecarOperation` contains the existing operations plus `unlock`; `WireEnvelope` requires `schemaVersion`, `messageType`, `requestId`, `sequence`, `monotonicTimeMs`, `operation`, and `payload`.
- Rust UI facade Ports cover Device, Motion, Telemetry, Action, Grasp, Vision, and Log. Sidecar cancellation is internal.

## State-machine invariants

- A `JointTargetCommand` always carries a complete normalized vector, a `CommandSource`, and `finalCommand`; adapters validate model-specific vector length before sending.
- `normalized_to_raw` clamps finite normalized values to `[0,1]`, rounds to `[0,255]`, and rejects wrong lengths/non-finite values. `RawVectorMapper` rejects raw vectors whose length differs from capabilities.
- Runtime `stop_all` clears pending motion, cancels Action/Grasp/Vision work, locks MotionEngine submission, stops the sidecar path, and cancels pending sidecar requests.
- Sidecar `stop` is a queue barrier and software write lock. Every `set*` operation is rejected with `STOPPED` until explicit `unlock`; this is not physical power removal or a hardware emergency stop.
- Runtime `unlock` explicitly unlocks MotionEngine and the sidecar. `disconnect` is recoverable; `close` transitions the sidecar process to stopped.
- Sidecar envelope sequence numbers increase strictly for responses consumed by `SidecarSession`; request IDs are non-empty and echoed by Python output envelopes.

## Dependency direction

```text
console-contracts (Rust source)
  ├─ generate-contracts -> frontend/shared/contracts/generated.ts
  ├─ device-adapter-api / device-runtime / motion-engine / telemetry
  ├─ sidecar-client -> strict NDJSON + raw vector mapper
  └─ app-runtime -> UI facade Ports + internal SidecarPort

Python sidecar raw schema + adapter
  └─ validates the same raw model/vector fixture and serves the NDJSON boundary

Frontend UI
  └─ consumes generated DTOs and UI Ports; it does not consume sidecar envelopes directly
```

No global event bus or UI dependency is introduced into the Rust domain crates.

## Error codes, fixture, and generation

Stable sidecar error codes include `INVALID_JSON`, `INVALID_REQUEST`,
`UNKNOWN_FIELD`, `SCHEMA_UNSUPPORTED`, `UNKNOWN_OPERATION`,
`INVALID_ARGUMENT`, `UNSUPPORTED_TRANSPORT`, `UNSUPPORTED_CAPABILITY`,
`NOT_CONNECTED`, `SDK_UNAVAILABLE`, `SDK_ERROR`, `TIMEOUT`, and `STOPPED`.

The raw model/length source snapshot is [raw-capabilities.json](../contracts/raw-capabilities.json). Generate and verify the UI projection from `apps/console-v2`:

```powershell
pnpm generate:contracts
pnpm check:contracts
```

The freshness check compares generator output to the checked-in file and exits non-zero on drift.

## Verification

- `cargo fmt --all -- --check` passed.
- `cargo test --workspace` passed, including contract conversion, strict sidecar session, all eight simulator models, app-runtime stop/unlock, telemetry buffers, and doc tests.
- `cargo clippy --workspace --all-targets -- -D warnings` passed.
- `python -m pytest -q` in `sidecar/linkerhand-bridge` passed: 32 tests.
- `pnpm install --frozen-lockfile` passed.
- `pnpm typecheck` passed.
- `pnpm lint` passed.
- `pnpm test` passed: 3 files / 4 tests.
- `pnpm build` passed.
- `node scripts/check-contracts.mjs` passed.

## Current limitations

- `src-tauri` remains an assembly skeleton and does not yet launch/connect the Python sidecar or expose the UI facade through real commands/channels.
- Python `RealSdkAdapter` still depends on the legacy LinkerHand SDK and real CAN/RS485 deployment inputs.
- Action persistence, grasp preset registry, vision proposal generation, and log export remain seam-level behavior; the facade returns explicit unsupported/empty results where the underlying subsystem is not installed.
- Software stop is intentionally not advertised as physical power removal.
- Generated TypeScript is a projection, not a runtime schema validator; production IPC should validate envelopes at the Rust/Python boundary.

## Next agent entry points

1. Implement the concrete Rust sidecar process/session adapter using `sidecar-client::NdjsonFramer`, `RawVectorMapper`, and the generated `SidecarOperation` values.
2. Wire `app-runtime::ui` Ports through `src-tauri` commands/channels without moving business logic into the shell.
3. Replace the UI mock runtime with a facade-backed implementation while preserving normalized vectors and raw capability handling.
4. Add real SDK integration tests using fake subprocess I/O first, then hardware-gated CAN/RS485 tests.
5. Keep `raw-capabilities.json`, Rust serialization, Python schema, and generated TypeScript freshness checks in CI.
