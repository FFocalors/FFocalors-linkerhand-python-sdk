# M2 transport handoff

Branch: `codex/v2-m2-transport`

Commit: `e93bab7` (sidecar process/client and adapter) plus the working-tree
Tauri/frontend assembly changes in the following commit.

The frozen public DTOs are unchanged. `sidecar-client` now owns a bounded,
thread-backed process manager with separate stdin/stdout/stderr handling,
request-id and operation routing, monotonic response sequence validation,
timeouts, contamination/crash state, restart, and bounded shutdown. The
`SidecarDeviceAdapter` maps `DeviceConfig` to the Python bridge, parses its
capabilities, converts normalized positions to raw bytes, and constructs
complete telemetry snapshots. The integration test starts the real Python
fake sidecar and covers connect/set/get/stop/unlock/disconnect/close.

The Tauri shell exposes typed config/capabilities/connection/connect/disconnect,
set target, stop, unlock, and telemetry Channel commands. Browser mode keeps
the existing mock runtime; Tauri mode selects the command-backed port adapter.

Validation performed: `cargo test -p sidecar-client`, `cargo check -p
linkerhand-console`, and the Python sidecar test suite. Frontend package
dependencies were not installed in this checkout, so `pnpm typecheck` could
not run until `pnpm install` is available.

Limitations: the initial Tauri runtime installs the deterministic simulator so
the shell is hardware-free; production packaging should construct
`SidecarDeviceAdapter` with the bundled Python bridge. Feature ports that do
not yet have a Rust facade return an explicit `UNSUPPORTED` AppError.

Next entry: wire the production sidecar launcher into the Tauri runtime and
replace the simulator factory, then add Channel subscription plumbing once
`@tauri-apps/api` is included in the frontend package.
