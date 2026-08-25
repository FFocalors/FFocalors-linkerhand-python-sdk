# Shared Vision Runtime

`VisionRuntime` is the single browser camera and MediaPipe Tasks Vision owner for the Vision Mimic and Rock-Paper-Scissors features.

## Responsibilities

- Own `getUserMedia`, one `HandLandmarker` worker, model loading, frame scheduling and camera tracks.
- Run MediaPipe HandLandmarker in `VIDEO` mode in `frontend/workers/vision-worker`.
- Publish neutral `VisionLandmarkResult` values: handedness, 21 landmarks, confidence, monotonic time, frame sequence, FPS estimate, dropped-frame count and in-flight count.
- Provide `start`, `stop`, `suspend`, `resume`, `switchCamera`, `dispose`, `subscribe` and `onResult`.

The runtime does not map landmarks to robot positions, `VisionPoseProposal`, RPS moves or device commands. Feature code owns those translations and must share one runtime instance.

## Invariants

1. `owner` is one of `vision`, `rps`, or `null`; a different owner receives `VISION_BUSY` and never opens a second camera.
2. The worker has at most one frame in flight. `SingleFrameGate` drops a new frame while occupied; it never queues frames.
3. `stop` and `dispose` cancel callbacks, stop all tracks, detach the video element, terminate the worker and release ownership. Hidden documents call `stop` (explicit `suspend` is available when a caller wants to retain the stream).
4. Worker landmark results are published unchanged; feature code owns any presentation-level processing.
5. Model and WASM URLs are packaged `/vision` assets. There is no CDN fallback.
6. The camera requests 640x480 at 30 FPS and inference frames are capped at that size. This matches the legacy one-hand pipeline and prevents a 1080p camera from adding avoidable bitmap-transfer and model latency.

## State and errors

States are `idle`, `loading`, `running`, `suspended`, `stopping`, `error`, `permission-denied`, and `device-lost`. Stable error codes include `VISION_BUSY`, `CAMERA_PERMISSION_DENIED`, `CAMERA_UNAVAILABLE`, `CAMERA_DEVICE_LOST`, `MODEL_LOAD_FAILED`, `WORKER_ERROR`, and `WORKER_INFERENCE_FAILED`.

## Offline resources

`public/vision/assets-manifest.json` records MediaPipe Tasks Vision `1.0.1`, source, Apache-2.0 license and SHA-256 hashes. `pnpm check:vision-assets` fails on missing or modified resources. `pnpm vision:download` downloads the pinned model and copies WASM from the installed package, then checks the model hash. Production `pnpm build` checks assets before Vite and never downloads them.

## Tests

`runtime.test.ts` covers one-slot backpressure, owner exclusion, permission errors and release of tracks/worker. `protocol.test.ts` uses a fixed 21-landmark fixture and snapshots the worker message shape without requiring a real camera. Browser validation should additionally observe `snapshot().inflight <= 1`, `droppedFrames`, and a bounded latest result stream.
