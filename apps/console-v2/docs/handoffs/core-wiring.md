# Core wiring handoff (M5 / Luna)

Branch: `codex/v2-m5-core-wiring`  
Base: `e421e7a3d27a8ee31a1fa739603dbc3a7da50ba7`

## Public interface status

The frozen `console-contracts` DTOs, generated TypeScript projection, vision,
RPS, and Feature UI directories were not changed. The runtime adapter adds
Tauri commands and local payloads for speed/torque vectors, operation and
connection subscriptions, action control, adaptive grasp control, and bounded
log listing. `DeviceAdapter` and `DeviceRuntime` gained optional speed/torque
operations; existing adapters remain source-compatible through default
unsupported implementations. `ActionEngine` exposes read-only current ID and
progress for event projection.

## Composition

`frontend/app/composition.ts` creates one stable composition per App mount and
injects the feature-local `DeviceControlController`, `ActionController`, and
`GraspController`. Tauri controllers are backed by actor commands/channels;
browser mode uses deterministic local controllers and the App composition
identifies the mode as a browser simulator. No browser timer sends hardware
commands.

The Tauri actor remains the sole owner of `AppRuntime` and all blocking sidecar
I/O. Subscriber lists are capped at eight and remove channels on send failure
or explicit cleanup. Stop-all cancels actions, loops, playback, grasp, pending
motion and sidecar work before taking the software lock; unlock is explicit and
does not resume old work.

## Verification

- `cargo fmt --all -- --check`
- `cargo test --workspace`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `pnpm typecheck`
- `pnpm lint`
- `pnpm test -- --run` (8 files, 36 tests)

## Limits

The fake Python sidecar remains the default Tauri configuration; real CAN/RS485
SDK deployment is still hardware/package dependent. Infinite action loops are
translated to the action engine's bounded 1,000-loop safety cap. Software
stop is a write lock and cancellation barrier, not a physical emergency stop.
Adaptive grasp telemetry is sampled while a grasp subscriber exists and all
touch fallback is explicit in the feature controller.
