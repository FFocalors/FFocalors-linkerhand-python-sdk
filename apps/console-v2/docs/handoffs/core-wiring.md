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
- `cargo check -p linkerhand-console`
- `cargo test --workspace`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `pnpm typecheck`
- `pnpm lint`
- `pnpm test -- --run` (9 files, 37 tests)
- `pnpm check:contracts`
- `pnpm check:vision-assets`
- `pnpm build`
- `python -m pytest -q sidecar/linkerhand-bridge` (run separately from workspace root)

The contract check normalizes LF/CRLF before comparison. The integration
baseline was generated with LF, while a Windows fresh checkout can materialize
the checked-in projection as CRLF; the previous byte-for-byte check therefore
reported a false stale projection. The Rust contract contents remain unchanged.
Offline capabilities are sourced from the raw-capabilities model matrix and are
available without opening the sidecar; an operator's explicit connect replaces
that declaration with adapter-reported capabilities. App startup failures now
show a recoverable retry surface instead of an unbounded spinner.

## Limits

The fake Python sidecar remains the default Tauri configuration; real CAN/RS485
SDK deployment is still hardware/package dependent. Nullable local loop input
is passed to the action engine as a true run-until-cancel loop; its diagnostic
counter saturates and is not a safety stop. Software stop is a write lock and
cancellation barrier, not a physical emergency stop.
Adaptive grasp telemetry is sampled while a grasp subscriber exists and all
touch fallback is explicit in the feature controller.
