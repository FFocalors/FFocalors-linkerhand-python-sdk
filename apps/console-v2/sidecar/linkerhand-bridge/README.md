# LinkerHand SDK sidecar

This process is the hardware boundary for Console V2. It owns one SDK object
and executes every SDK call on one worker thread. stdin and stdout are NDJSON;
stdout is reserved for protocol envelopes and SDK/library prints are copied to
stderr.

Run without hardware:

```powershell
@'
{"schemaVersion":1,"messageType":"command","requestId":"1","sequence":1,"monotonicTimeMs":1,"operation":"connect","payload":{"model":"L10","hand":"left","transport":{"type":"can","channel":"fake"},"mode":"fake"}}
{"schemaVersion":1,"messageType":"command","requestId":"2","sequence":2,"monotonicTimeMs":1,"operation":"getTelemetry","payload":{}}
{"schemaVersion":1,"messageType":"command","requestId":"3","sequence":3,"monotonicTimeMs":1,"operation":"close","payload":{}}
'@ | python main.py --fake
```

`connect` payload uses `model` (`O6`, `L6`, `L7`, `L10`, `L20`, `G20`, `L21`,
or `L25`), `hand` (`left`/`right`) and a strict transport object. CAN is
`{"type":"can","channel":"PCAN_USBBUS1"}`; RS485 is
`{"type":"rs485","port":"COM3","baudrate":115200}`. RS485 is available
only for O6/L6/L7/L10.

The Rust client should launch `main.py` with an explicit `--sdk-root` pointing
to the directory containing `LinkerHand/` for real hardware. A bundled
PyInstaller build should preserve `LinkerHand`, `resource`, and the YAML files;
`linkerhand_bridge.spec` is a boundary skeleton, not a release artifact.
