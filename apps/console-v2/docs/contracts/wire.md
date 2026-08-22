# Wire contract

All cross-process messages are one JSON object per NDJSON line, using stable camelCase names and `schemaVersion: 1`. The required envelope fields are `schemaVersion`, `messageType`, `requestId`, `sequence`, `monotonicTimeMs`, `operation`, and `payload`. `messageType` is `request`, `command`, `response`, `event`, or `error`; `operation` is the generated `SidecarOperation` enum. Unknown fields and schema versions are rejected at the sidecar boundary.

`CommandSource` includes `Manual`, `Preset`, `Playback`, `Loop`, `Vision`, `RockPaperScissors`, `Grasp`, and `Safety`. Software stop-all cancellation explicitly includes Vision, RockPaperScissors, Playback, Loop, and Grasp.
