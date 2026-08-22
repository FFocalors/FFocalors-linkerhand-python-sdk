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
- NSIS uses Tauri's `{ "type": "offlineInstaller" }` WebView2 mode. The
  `pnpm build:windows` run downloaded the WebView2 payload and produced the
  installer; a fresh air-gapped install still needs a separate machine test.
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
- Rebuilt on this branch with the runtime/UX integration:
  - NSIS `LinkerHand Console_2.0.0-rc.1_x64-setup.exe`: 251,852,946 bytes,
    SHA-256 `6A1B6EEE377B943CDF9BEA8E8CDD242572AF5C169404E700E0B9D183D2C0FA17`.
  - Portable ZIP `LinkerHand-Console-v2.0.0-rc.1-win-x64-portable.zip`:
    36,735,343 bytes, SHA-256
    `8B294E500A8BD5DA3BE13A6A55BC5AEE55DF7833B969BB422003993906B4DACB`.
  - Sidecar: 22,725,876 bytes, SHA-256
    `BB7F43FADB498E1E3D67871541E87FD373FCACA4692ED043421201935E72A77F`.
  - Packaged sidecar fake NDJSON smoke passed with three envelopes.

## Final RC packaging refresh

- Packaging branch: `codex/v2-m5-final-packaging`
- Source integration commit: `94348d19fd0475cefdc9f24484c044c1e0fe1e2f`
- `pnpm build:windows` completed with the configured Tauri NSIS
  `webviewInstallMode.type = offlineInstaller`; the build downloaded and
  embedded the offline WebView2 payload.
- Bundle inventory contains the release frontend, classic
  `vision-worker-*.js` chunk, `vision/vision_bundle.js`, hand-landmarker model,
  both WASM variants, and the target-triple sidecar executable. The portable
  ZIP contains the release executable, sidecar, and inventory.
- Final artifacts (Windows x64):
  - `E:\OneDrive\Desktop\必备安装\linkerhand-v2-final-packaging\apps\console-v2\target\x86_64-pc-windows-msvc\release\bundle\nsis\LinkerHand Console_2.0.0-rc.1_x64-setup.exe` — 251,854,576 bytes,
    SHA-256 `46C1B12A153147D64BBAB2A96F0CE176900B85DB2F9EEBC891895ACEE65650A2`.
  - `E:\OneDrive\Desktop\必备安装\linkerhand-v2-final-packaging\apps\console-v2\artifacts\LinkerHand-Console-v2.0.0-rc.1-win-x64-portable.zip` — 36,736,155 bytes,
    SHA-256 `13AEAE7C2EA5514DF19A6A9DF09609374D39EFA7E47B9EDEA181CC41653ABB37`.
  - `E:\OneDrive\Desktop\必备安装\linkerhand-v2-final-packaging\apps\console-v2\src-tauri\binaries\linkerhand-sidecar-x86_64-pc-windows-msvc.exe` — 22,725,412 bytes,
    SHA-256 `0296BF57EC128DAA052A57FC50CAB60C119E3360225D75584CEE4402814A96B2`.
- The source and packaged sidecar both passed the three-envelope fake NDJSON
  smoke. No hardware connect is performed by this smoke.

## Remaining gates

- The complete Rust/Python/pnpm suite, offline asset checks, sidecar smoke,
  NSIS build, and portable rebuild have passed on this branch.
- A fresh air-gapped Windows machine installation has not yet been executed;
  the offline WebView2 payload was downloaded and embedded during the build,
  but installation still needs an independent clean-machine verification.
- Browser QA for navigation/theme/slider and the classic vision worker was
  completed on the integration branch before this packaging refresh; this
  packaging task did not repeat interactive browser QA.
- O6 Windows PCAN hardware acceptance is mandatory before calling V2.0
  formal; this branch is an RC/simulator-ready delivery only.
