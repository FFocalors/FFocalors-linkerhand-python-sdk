# Release/runtime integration handoff

## Delivery

- Branch: `codex/v2-m5-release-integration`
- Base: `codex/v2-rewrite` at `5ab7804`
- Integrated packaging commits: `ce79e27`, `6f3ef7f`
- Runtime commits: `ee62b21`, `cfbd923`
- UX commits: `bfe23b9`, `498d558` (resolved App shell conflict by retaining
  the singleton VisionRuntime, typed ports, stop-all lock semantics and only
  taking the UX aria/page-transition changes)
- Public DTO/contracts: unchanged

## Runtime decisions

- Release startup loads `console-v2-settings.json` from the Tauri app config
  directory. Missing, malformed, or legacy fake-channel settings fall back to
  a safe O6/left-hand `CAN PCAN_USBBUS1` configuration. The app does not
  connect hardware during startup.
- `LINKERHAND_CONSOLE_SIMULATOR=1` is the only simulator switch. It forces a
  fake transport and uses the checked-in Python bridge with `--fake`.
- Release mode uses only a discovered packaged executable; it never falls
  back to Python on PATH. `LINKERHAND_SIDECAR_PATH` is an explicit test/deploy
  override. Discovery covers an executable sibling, Tauri external-bin names,
  `binaries/`, and the portable `sidecar/linkerhand-sidecar.exe` layout.
- `sidecar_self_check` starts the selected process, sends a protocol `close`,
  validates the response, and always terminates the child. It performs no
  device `connect`, CAN, or RS485 operation. It distinguishes simulator mode,
  executable/protocol health, and the still-unverified hardware gate.
- `ProcessConfig::executable` makes the release intent explicit; `fake` and
  `python` remain test/development constructors.
- NSIS uses Tauri's `{ "type": "offlineInstaller" }` WebView2 mode. The build
  host must be able to obtain/cache the approximately 127 MB WebView2 offline
  installer; no local offline-installer binary was available in this run, so
  a fresh air-gapped Windows installation is not yet claimed as verified.
- Vite injects `package.json` version `2.0.0-rc.1` as `VITE_APP_VERSION`; the
  settings page has the same RC fallback for browser/offline simulation and
  contains no `0.1.0`/`v2-preview` display path.

## Verification

- `cargo fmt --manifest-path apps/console-v2/Cargo.toml --all`
- `cargo check --manifest-path apps/console-v2/src-tauri/Cargo.toml`
- `cargo test --manifest-path apps/console-v2/src-tauri/Cargo.toml --lib`: 10 passed
- `cargo test --manifest-path apps/console-v2/crates/sidecar-client/Cargo.toml`: 10 passed
- Runtime tests cover safe release defaults, explicit simulator transport,
  candidate precedence, missing executable deferred until connect, corrupted
  settings recovery, and protocol-valid/invalid self-checks.
- Packaging branch evidence remains in `docs/handoffs/packaging.md`:
  Python tests, fake NDJSON smoke, PyInstaller sidecar (22,725,009 bytes),
  NSIS installer (35,909,699 bytes), and portable ZIP (36,417,092 bytes).

## Remaining gates

- Re-run the complete Rust/Python/pnpm suite after final branch integration,
  then rebuild NSIS/portable with the offline WebView2 payload available.
- Browser QA must verify navigation/theme/slider behavior at 1366x768.
- O6 Windows PCAN hardware acceptance is mandatory before calling V2.0
  formal; this branch is an RC/simulator-ready delivery only.
