# M2 transport handoff

Branch: `codex/v2-m2-transport`

Commits: `e93bab7`, `62d65bf`, `77968fd`, `6c06b34`, `5531df8`, and
`e836671`, followed by the actor/Channel fixes in the current handoff commit.

The frozen public DTOs are unchanged. `sidecar-client` now owns a bounded,
thread-backed process manager with separate stdin/stdout/stderr handling,
request-id and operation routing, monotonic response sequence validation,
timeouts, contamination/crash state, restart, and bounded shutdown. The
`SidecarDeviceAdapter` maps `DeviceConfig` to the Python bridge, parses its
capabilities, converts normalized positions to raw bytes, and constructs
complete telemetry snapshots. The integration test starts the real Python
fake sidecar and covers connect/set/get/stop/unlock/disconnect/close.

The Tauri shell exposes typed config/capabilities/connection/connect/disconnect,
set target, stop, unlock, operation, telemetry read, subscribe, and unsubscribe
commands. A bounded actor is the sole AppRuntime owner. It ticks motion at
20Hz, flushes final commands immediately, samples telemetry only while a
bounded subscriber exists, and removes failed/explicitly unsubscribed
Channels. Browser mode keeps the existing mock runtime; Tauri mode selects the
official `@tauri-apps/api` command/Channel adapter.

Validation performed: `cargo test --workspace`, `cargo clippy --workspace
--all-targets -- -D warnings`, `cargo check -p linkerhand-console`,
`pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`, and Python sidecar
tests (`32 passed`). The Tauri actor test covers continuous frames, final
motion, stop lock/unlock, and bounded shutdown; the sidecar test rejects
request/command stdout frames.

Limitations: the initial Tauri runtime constructs `SidecarDeviceAdapter` with
the checked-in Python bridge in `--fake` mode, so the shell is hardware-free;
production packaging should select real mode and bundle the SDK. Feature ports
that do not yet have a Rust facade return an explicit `UNSUPPORTED` AppError.

Next entry: wire the production sidecar launcher into the Tauri runtime and
replace the simulator factory, then add Channel subscription plumbing once
`@tauri-apps/api` is included in the frontend package.
