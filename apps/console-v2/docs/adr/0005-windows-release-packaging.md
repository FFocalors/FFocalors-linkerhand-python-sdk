# ADR 0005: Windows x64 RC packaging

Status: accepted for `2.0.0-rc.1`

## Decision

Console V2 ships a Windows x64 release candidate as a Tauri NSIS installer and
an explicitly labelled portable ZIP. Tauri owns the frontend at `../dist`,
enables bundling, and starts at a 1366x768 minimum window. The bundle carries
the local MediaPipe model/WASM output and a hash inventory; production builds
never download a CDN asset.

The real Python SDK bridge is built with the checked-in PyInstaller spec and
the pinned `requirements-windows-x64.txt`. `LINKERHAND_SDK_ROOT` is an input,
not a path baked into source. The resulting sidecar has a stable target-triple
name and is provided to Tauri as an external binary. `--fake` is only a test or
development switch; release mode is real by default. The bridge's stdout is
reserved for schema-1 NDJSON and all SDK output goes to stderr.

## Release gate

`pnpm check:vision-assets`, `pnpm build`, `cargo check --workspace`, the Python
sidecar tests, and the subprocess fake smoke must pass. `pnpm build:windows`
may produce the NSIS installer only on a Windows host with WebView2/Tauri
prerequisites and the pinned Python wheels. `pnpm build:portable` packages the
built executable, sidecar, and inventory without claiming that the hardware
path has been validated.

This is an RC only. Without an O6 device test, do not call it a formal or
hardware-certified release; the O6 acceptance gate remains with integration.
