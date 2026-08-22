# LinkerHand Console V2 sidecar protocol (schema 1)

Transport is one JSON object per line on stdin/stdout. The sidecar never writes
anything except envelopes to stdout. Every output envelope has these fields:

```json
{"schemaVersion":1,"messageType":"response","requestId":"abc","sequence":1,"monotonicTimeMs":1234,"operation":"getTelemetry","payload":{}}
```

`sequence` starts at one and is strictly increasing per process. `requestId` is
echoed. Errors use `messageType: "error"` and
`payload.error: {code,message,retryable,details?}`. Stable codes include
`INVALID_JSON`, `INVALID_REQUEST`, `UNKNOWN_FIELD`, `SCHEMA_UNSUPPORTED`,
`UNKNOWN_OPERATION`, `INVALID_ARGUMENT`, `UNSUPPORTED_TRANSPORT`,
`UNSUPPORTED_CAPABILITY`, `NOT_CONNECTED`, `SDK_UNAVAILABLE`, `SDK_ERROR`, and
`TIMEOUT`.

Requests contain `schemaVersion`, `requestId`, `operation`, and `payload`; a
full-envelope sender may additionally include `messageType` (`command` or
`request`), non-negative `sequence`, and numeric `monotonicTimeMs`. All these
metadata fields are validated when present.
Supported operations are `connect`, `disconnect`, `capabilities`,
`getTelemetry`, `getPosition`, `getCurrent`, `getSpeed`, `getTouch`,
`setPosition`, `setSpeed`, `setCurrent`, `setTorque`, `stop`, and `close`.
Unknown fields are rejected.

`connect` payload:

```json
{"model":"L10","hand":"left","transport":{"type":"can","channel":"PCAN_USBBUS1"},"mode":"real","sdkRoot":"D:/sdk"}
```

CAN accepts only `type` and `channel`; RS485 accepts only `type`, `port`, and
positive integer `baudrate` (default 115200). RS485 is supported by O6, L6, L7,
and L10. Position lengths are O6/L6=6, L7=7, L10=10, L20/G20=20, and
L21/L25=25. Position, speed, current, and torque values are numeric 0..255;
each vector must have the model's exact length. Write payload names are
`positions`, `speeds`, `currents`, and `torques` respectively.

`getTelemetry` returns all four keys (`position`, `current`, `speed`, `touch`).
`stop` is a queue-level stop acknowledgement; it does not claim a hardware
emergency-stop primitive that the legacy SDK does not expose. `disconnect` is
recoverable; `close` shuts down the process after its response.
