# LinkerHand SDK sidecar

This process is the hardware boundary for Console V2. It owns one SDK object
and executes every SDK call on one worker thread. stdin and stdout are NDJSON;
stdout is reserved for protocol envelopes and SDK/library prints are copied to
stderr.

Run without hardware:

```powershell
@'
{"schemaVersion":1,"messageType":"command","requestId":"1","sequence":1,"monotonicTimeMs":1,"operation":"connect","payload":{"deviceId":"demo","model":"L10","hand":"left","transport":{"type":"can","channel":"fake"},"mode":"fake"}}
{"schemaVersion":1,"messageType":"command","requestId":"2","sequence":2,"monotonicTimeMs":1,"operation":"getTelemetry","payload":{}}
{"schemaVersion":1,"messageType":"command","requestId":"3","sequence":3,"monotonicTimeMs":1,"operation":"close","payload":{}}
'@ | python main.py --fake
```

`connect` payload uses `model` (`O6`, `L6`, `L7`, `L10`, `L20`, `G20`, `L21`,
or `L25`), `hand` (`left`/`right`) and a strict transport object. CAN is
`{"type":"can","channel":"PCAN_USBBUS1"}`; RS485 is
`{"type":"rs485","port":"COM3","baudrate":115200}`. RS485 is available
only for O6/L6/L7/L10.

`stop` is a queue barrier and enables a software write lock. Every `set*`
operation is rejected until `unlock`; neither operation claims physical power
removal. Raw capability lengths are snapshotted in
`../../docs/contracts/raw-capabilities.json`.

The Rust client should launch the packaged `linkerhand-sidecar` executable in a
release bundle. Development may launch `main.py` with `--sdk-root` pointing to
the directory containing `LinkerHand/`. `--fake` is intentionally explicit and
is only for tests/simulation; real SDK mode is the release default.

## Windows x64 build

From `apps/console-v2`, install the pinned runtime requirements into the build
Python and run:

```powershell
python -m pip install -r sidecar/linkerhand-bridge/requirements-windows-x64.txt
$env:LINKERHAND_SDK_ROOT = (Resolve-Path ../..).Path
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1
python scripts/smoke-sidecar.py --executable src-tauri/binaries/linkerhand-sidecar-x86_64-pc-windows-msvc.exe
```

The script resolves every path before invoking PyInstaller, so a checkout with
Chinese characters or spaces is supported. The stable output name is
`linkerhand-sidecar-x86_64-pc-windows-msvc.exe`; generated `build/`, `dist/`,
and `src-tauri/binaries/` content is ignored by Git. The spec includes only the
bridge, the LinkerHand package/YAML settings, and the SDK's CAN/RS485 runtime
dependencies. SDK/library output is redirected to stderr; stdout remains pure
NDJSON.
