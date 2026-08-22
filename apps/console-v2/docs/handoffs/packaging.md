# Console V2 packaging handoff

- Branch: `codex/v2-m5-packaging`
- Version: `2.0.0-rc.1` (Python metadata uses the normalized `2.0.0rc1` form)
- Scope: Tauri Windows x64 configuration, PyInstaller real sidecar build,
  offline vision resource inventory, NSIS/portable scripts, and release gates
- Tauri: `frontendDist` is `../dist`, bundle is active, NSIS is the Windows
  target, and the minimum window is 1366x768.
- Sidecar: `scripts/build-sidecar.ps1` accepts `LINKERHAND_SDK_ROOT` and emits
  `src-tauri/binaries/linkerhand-sidecar-x86_64-pc-windows-msvc.exe`. The
  checked-in SDK is included through `pathex` and YAML data; no placeholder
  path is used.
- Offline assets: `pnpm build` runs `check:vision-assets`; the checked-in model
  and WASM hashes are therefore prerequisites rather than build downloads.
- Verification: `python scripts/smoke-sidecar.py` checks the real subprocess
  NDJSON boundary, including stdout purity. Run `node scripts/create-bundle-inventory.mjs`
  after frontend/sidecar builds and `pnpm build:portable` after Tauri.

## Local proof (Windows x64, 2026-08-23)

- `pnpm install --frozen-lockfile` passed.
- `pnpm lint` passed after adding global ESLint ignores for all generated
  frontend/Tauri/sidecar output; `pnpm test:lint-boundary` asserts those roots
  are not returned by ESLint's file matcher.
- `pnpm build` passed and verified 5 offline assets; the Vite output was
  271.4 kB before compression.
- `python -m pytest -q sidecar/linkerhand-bridge/tests`: all tests passed.
- PyInstaller 6.15.0 built the real sidecar at 22,725,009 bytes; the packaged
  executable passed the 3-envelope fake NDJSON smoke.
- `cargo check --workspace` passed (only the existing ts-rs serde-attribute
  warning).
- `pnpm tauri build --target x86_64-pc-windows-msvc` passed and produced the
  NSIS installer `LinkerHand Console_2.0.0-rc.1_x64-setup.exe` (35,909,699
  bytes).
- The portable ZIP was produced at 36,417,092 bytes and contains the release
  exe, sidecar, and bundle inventory.

## Known limits

This branch deliberately does not change `src-tauri/src/lib.rs`; runtime sidecar
path selection and O6 hardware acceptance belong to integration. NSIS/Tauri
bundling requires a Windows host with the Rust target, WebView2, and Tauri
prerequisites. No generated executable is committed.
