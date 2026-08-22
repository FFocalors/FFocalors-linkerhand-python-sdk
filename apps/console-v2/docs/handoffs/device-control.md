# Device Control Feature Handoff

## Scope

Branch `codex/v2-m3-device-control` implements the operator-facing device control page in `frontend/features/device-control`. No shared contract, Tauri, Rust, sidecar, generated file, or App assembly was changed.

## Runtime seam

`DeviceControlController` is exported from the feature entrypoint and is intentionally feature-local. The future runtime adapter should inject it through the `controller` prop. It owns connect/disconnect/reconnect, connection subscription, complete normalized joint target submission, speed/torque commands, quick actions, loops, and optional operation subscription. `DevicePort.stopAll()` and `DevicePort.unlock()` remain the required shared safety calls.

The controller must publish real `ConnectionSnapshot` and `OperationSnapshot` values. The browser does not poll or generate a hardware loop. A missing controller disables all device-changing controls with an explicit explanation.

## Interaction guarantees

- Sliders are generated from `capabilities.jointCount`, grouped in sets of five so L25 remains reachable at 1366x768.
- All manual commands are complete normalized vectors. Each `JointSlider` keeps pointer feedback in native/local DOM state; the parent receives no React state update per input. A single global `requestAnimationFrame` updates the visual vector and coalesces the hardware command; pointer release/cancel, blur, Enter, and Space cancel the pending frame and send `finalCommand: true`.
- Telemetry merges per joint: it never writes over a joint currently being dragged, while untouched joints continue to follow telemetry. After release, that joint also accepts subsequent telemetry.
- Stop-all locks immediately and cancels manual/quick-action/loop UI state. It is software locking, not physical emergency power-off. Unlock only clears the local lock after `unlock()` resolves and the latest real connection state is connected.
- Quick-action and loop labels/mutual exclusion are derived from subscribed operation state (`running`/`stopping`/`paused`); a short submitting state is cleared when the controller promise settles, and completed/error/cancelled operations restore the controls.
- Speed and torque controls are enabled only when capability availability and command length permit them.

## Verification

`index.test.tsx` covers complete-vector final submission, exact latest-vector RAF coalescing, final-vs-stale cancellation, parent/local render behavior, per-joint telemetry isolation, L25 rendering, controller-less disablement, connection actions, stop/unlock including pending-RAF races, operation-driven quick-action/loop recovery, and speed/torque capability gating.

Verified from `apps/console-v2` after installing the lockfile dependencies:

- `pnpm typecheck` passed.
- `pnpm lint` passed.
- `pnpm test` passed (3 test files, 13 tests).
- `pnpm build` passed (Vite production bundle generated).
