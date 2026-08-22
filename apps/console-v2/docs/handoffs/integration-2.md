# Integration 2 handoff

## Source commits

- Core wiring: `194a0f6`, `c147085`, `7ae178c`, `109f7a7`, `5ecba5b`, `d313caa`, `db6e0c3`, `7b60af4`, `5e0b533`, `1e9ff8b`, `dcaf3e6`, `9a8c644`, `2c7addd`
- Shared VisionRuntime lifecycle fix: `4447175`
- Vision feature: `ea847da`, `26ef7ac`, `a081358`
- RPS feature: `3c02e6f`, `4151097`, `ef85db6`
- Settings: `2228eec`, `bc46445`
- Architecture/Windows boundary CI: `668d9ed` (with the generated-contract EOL conflict resolved without changing the contract)

## Application wiring delivered

- `App` creates one `VisionRuntime` and injects the same instance into Vision Mimic and RPS; unmount disposes it. Vite reaches the worker through the concrete runtime import.
- Vision proposals use the typed `DevicePort` path with `source=vision` and `finalCommand=false`; the Rust actor remains the 20 Hz latest-wins owner. Revoke cancels only the Vision source.
- RPS uses an app-local O6-only action controller, explicit per-round authorization, six-joint vectors sourced from the existing O6 presets (`握拳`, `张开`, `贰`), `source=rockPaperScissors`, and source-local cancellation.
- Added `motion_cancel_source` through the actor/Tauri adapter without changing frozen DTOs.
- Settings now has a V2-only app config file in the Tauri app config directory, safe fallback on missing/corrupt JSON, repeat-save support on Windows, camera permission/enumeration, sidecar runtime-status check, and offline asset check. It does not migrate old settings.
- Diagnostics receives device/config/capabilities/telemetry/log ports; device control's diagnostics action navigates to the diagnostics page.
- Global stop keeps the UI locked, cancels Vision/RPS/action/grasp paths, and reports unconfirmed stop results instead of claiming physical emergency-stop semantics. Unlock failure leaves the lock in place.
- Added a global render error boundary and theme provider support for light/dark/system through an app-owned theme port.

## Verification

- Rust: `cargo fmt --all`, Tauri check, `cargo test -p linkerhand-console` (6 tests), including actor Vision 20 Hz/source-cancel coverage and settings replace/corrupt fallback coverage.
- Frontend: `pnpm typecheck`, `pnpm lint`, targeted App/controller Vitest (4 tests), boundary, contract, and offline-asset checks.

## Remaining follow-up

- Production packaging still needs to select the bundled real Python SDK sidecar by install mode; current Tauri bootstrap intentionally uses the fake adapter for simulator/RC development.
- Final NSIS/portable packaging, offline fresh-install verification, full-browser performance profiling, and O6 PCAN hardware acceptance remain open. V2.0 formal release must not be claimed before those gates.
- Settings persistence is ready, but loading the persisted device config into the next actor bootstrap and wiring real sidecar health/adapter selection should be completed in the packaging/runtime integration task.
