# Vision feature handoff

## 分支与范围

- Branch: `codex/v2-m4-vision-feature`
- Base: `9886056` (`codex/v2-m4-vision-runtime`)
- Scope: `frontend/features/vision/**` and this handoff only.
- Shared contracts, `shared/vision-runtime`, device-control, App, Rust and sidecar are unchanged.

## Integration contract

The app shell should pass its one shared `VisionRuntime` as `runtime` and a feature-local `VisionProposalController` as `proposalController` to `VisionMimic`. The controller is intentionally a sink/controller boundary: it receives only complete `VisionPoseProposal` values and exposes `revoke(reason)`. The feature never calls a device facade, Tauri, or `VisionPort.sync`.

Runtime ownership is checked before `stop()` during `stop` and unmount. A feature cannot stop an RPS-owned runtime. Once stopped, locked, unauthorized, non-O6, uncalibrated, low-confidence, or non-running, proposals are revoked and no further result can submit.

## Verification

From `apps/console-v2`:

```text
pnpm typecheck
pnpm lint
pnpm test -- --run
pnpm build
```

The feature tests cover all proposal gates, complete O6 vectors and bounded mapping, lock revocation, shared-runtime owner cleanup, fixture recognition, and the session calibration sequence.

## Follow-up integration

Wire `proposalController.submit` to the app-runtime Vision facade/motion arbitration in the composition layer. Keep authorization and lock state owned by that composition layer, pass the same runtime to Rock-Paper-Scissors, and retain the runtime's owner exclusion. Browser validation should verify the camera preview, `snapshot().inflight <= 1`, real FPS/dropped frames and recovery from permission/device errors.
