# Console V2 Rust modules

`console-contracts` owns all public camelCase DTOs and the `WireEnvelope` (`schemaVersion`, `messageType`, `requestId`, `sequence`, `monotonicTimeMs`, `operation`, `payload`). `device-adapter-api` is the only hardware boundary; `device-simulator` implements it deterministically.

`console-contracts` is the sole public DTO source; its generator projects checked-in TypeScript and `check:contracts` detects drift. `device-runtime` owns adapter lifecycle and connection snapshots. `motion-engine` arbitrates normalized complete vectors at 20 Hz. `stop_all` clears pending commands, covers Vision/RockPaperScissors/Playback/Loop/Grasp, and locks software submission; `unlock` is explicit. `telemetry` keeps bounded normal-status and high-rate frame buffers separate. `action-engine` and `adaptive-grasp` are pure state machines. `structured-logging` is bounded and pageable. `sidecar-client` validates strict NDJSON envelopes and stop/unlock state. `app-runtime` exposes separate UI-facing facade ports for Device, Motion, Telemetry, Action, Grasp, Vision, and Log, plus an internal SidecarPort; it owns no global event bus.

Only `src-tauri` depends on Tauri. Its command/channel layer is an assembly shell and must not acquire business logic. Frontend and Python sidecar implementations are intentionally outside this workspace.

## Enforced dependency boundaries

`scripts/check-boundaries.mjs` is the executable module map for the three
runtime surfaces. A feature may import itself, `frontend/shared`, or public
contracts; feature-to-feature imports (including deep and Windows-style
relative paths) are rejected. Shared code cannot depend on `features`, `app`,
or workers. Workers are limited to their own module and the allowlisted shared
contract/runtime areas; `app` is the assembly point. The same policy is
reflected in the ESLint restricted-import rules for fast editor feedback.

The checker also runs `cargo metadata` to reject direct Tauri dependencies in
business crates, reverse edges from `device-adapter-api`, and Rust workspace
cycles. A lightweight Python scan prevents the sidecar from importing UI or
feature product state. `pnpm check:boundaries` runs all three checks and
`pnpm test:boundaries` exercises legal and illegal fixtures.
