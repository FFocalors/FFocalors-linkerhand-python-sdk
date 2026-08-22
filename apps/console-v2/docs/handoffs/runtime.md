# Runtime handoff

- Branch: `codex/v2-m1-runtime`
- Commit: `735e188c05edb41333356ee3f96f2d53febf83b8`
- Scope: Rust-only `console-contracts`, `device-adapter-api`, `device-simulator`, `motion-engine`, `telemetry`, `device-runtime`, `action-engine`, `adaptive-grasp`, `structured-logging`, `sidecar-client`, `app-runtime`, plus a minimal Tauri 2 Channel assembly shell.
- Public interfaces: added versioned camelCase DTOs and `WireEnvelope`; adapter, motion, telemetry, sidecar, and typed application ports are new. The follow-up adds `RockPaperScissors`, explicit motion source begin/end/finish lifecycle, and `DevicePort`/`MotionPort`/`TelemetryPort`/`ActionPort`/`GraspPort`/`LogPort` interfaces. No existing public interface was changed because this was an empty baseline.
- Verification: `cargo fmt --all`; `cargo test --workspace` (all unit/doc tests pass, including app-runtime stop-all integration and 100,000 bounded log writes); `cargo clippy --workspace --all-targets -- -D warnings` passes on the current Windows MSVC target.
- Known limits: `src-tauri` is intentionally an assembly skeleton and has no frontend or Python process. `MotionEngine::stop_all` cancels software operations and locks command submission; it explicitly does not claim physical power removal. The copied `src-tauri/icons/icon.png` is only a build-time placeholder.
- Next entry points: use `app-runtime::AppRuntime` as the orchestration seam, implement a concrete `DeviceAdapter`, and connect frontend commands/channels in `src-tauri` without moving business logic into the shell.
