# Vision Runtime Handoff

## Delivered

- Added `frontend/shared/vision-runtime` as the one shared camera/worker/model runtime.
- Replaced the placeholder worker with MediaPipe Tasks Vision `HandLandmarker` using `runningMode: 'VIDEO'`.
- Added one-slot frame backpressure, `requestVideoFrameCallback` with RAF fallback, transfer of `ImageBitmap`, worker acknowledgement, frame drops and latest bounded result state.
- Added lifecycle handling: start/stop/suspend/resume, camera switching, permissions, track-ended/device loss, worker/model failure, visibility stop and disposal.
- Added checked local model/WASM resources under `public/vision`; no runtime CDN URL is used.
- Added deterministic gate and protocol fixture tests.

## Public entry point

```ts
import { VisionRuntime } from '../shared/vision-runtime';
const runtime = new VisionRuntime();
await runtime.start(videoElement, 'vision'); // or 'rps'
const unsubscribe = runtime.onResult(result => { /* feature mapping */ });
await runtime.stop();
unsubscribe();
```

The app shell should create one `VisionRuntime` and inject the same instance into Vision and RPS. Features must consume neutral landmarks and perform their own `VisionPoseProposal`/gesture mapping. This runtime never issues motion or robot commands.

## State invariants

- One source owns one runtime; another source receives `VISION_BUSY` without opening another camera.
- `inflight` is always `0` or `1`; `SingleFrameGate` proves no queue is created and counts dropped frames.
- `stop`/`dispose` close tracks and terminate the worker. Document hidden state invokes stop; callers may explicitly use suspend when retaining a stream is intentional.
- All inference timestamps are monotonic frame timestamps; result `hands[*].landmarks` contains 21 points.

## Resources and verification

Use `pnpm check:vision-assets` to validate the manifest hashes. Use `pnpm vision:download` only when refreshing the pinned local resources; it fails on a model hash change. `pnpm build` performs the check first, so a missing asset is an explicit build failure rather than a network fallback.

## Verification performed

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test` (8 tests)
- `pnpm build` (offline asset check + Vite build)

## Follow-up entry points

Vision should translate `VisionLandmarkResult` into neutral pose proposals only after confidence/handedness policy is defined. RPS should consume the same result stream and must not instantiate another camera, worker, or model. Hardware mapping and action execution remain outside this runtime.
