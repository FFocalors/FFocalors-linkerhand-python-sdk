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
- Every start/switch/frame async path carries a monotonic generation. Stop/dispose invalidates it first, cancels pending model initialization immediately, and stops late camera/replacement streams instead of attaching them. Cancellation settles the old start normally and never emits `error` or `running`.
- All inference timestamps are monotonic frame timestamps; result `hands[*].landmarks` contains 21 points.

## Resources and verification

Use `pnpm check:vision-assets` to validate the manifest hashes and required `.gitattributes` binary rules. Use `pnpm vision:download` only when refreshing the pinned local resources; it fails on a model hash change. `pnpm build` performs the check first, so a missing asset is an explicit build failure rather than a network fallback. The model, WASM and loader JS are all `-text` so Windows `core.autocrlf` cannot rewrite bytes.

## Verification performed

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test` (15 tests, including same-owner video binding, model/worker/frame errors, track-ended loss, hidden cleanup, async capture-stop race, ack/backpressure, deferred worker init, late camera arrival and deferred camera replacement)
- `pnpm build` (offline asset check + Vite build)

The baseline App does not yet import `VisionRuntime`; therefore this build validates TypeScript, local resources and the runtime source but does not prove that Vite emitted a worker chunk. The current `dist/assets` output contains only the baseline app CSS/JS. After Feature integration, run `pnpm build` and inspect `dist/assets` for the worker chunk (and verify its URL is local) before claiming browser packaging coverage.

Fresh-checkout reproducibility was verified from detached commit `6dfb66c692fed10ba78cdd82830f8c3242df032a` in a newly-created temporary worktree with Windows `core.autocrlf=true`. `git check-attr` reported `text: unset` for the model, WASM and loader JS; `pnpm install --frozen-lockfile`, `pnpm check:vision-assets` and `pnpm build` all passed. The temporary worktree and its untracked dependency directory were removed afterward.

## Follow-up entry points

Vision should translate `VisionLandmarkResult` into neutral pose proposals only after confidence/handedness policy is defined. RPS should consume the same result stream and must not instantiate another camera, worker, or model. Hardware mapping and action execution remain outside this runtime.
