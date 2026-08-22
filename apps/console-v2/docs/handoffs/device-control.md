# Device Control Feature Handoff

## Scope

Branch `codex/v2-m3-device-control` implements the operator-facing device control page in `frontend/features/device-control`. No shared contract, Tauri, Rust, sidecar, generated file, or App assembly was changed.

## Runtime seam

`DeviceControlController` is exported from the feature entrypoint and is intentionally feature-local. The future runtime adapter should inject it through the `controller` prop. It owns connect/disconnect/reconnect, connection subscription, complete normalized joint target submission, speed/torque commands, quick actions, loops, and optional operation subscription. `DevicePort.stopAll()` and `DevicePort.unlock()` remain the required shared safety calls.

The controller must publish real `ConnectionSnapshot` and `OperationSnapshot` values. The browser does not poll or generate a hardware loop. A missing controller disables all device-changing controls with an explicit explanation.

## Interaction guarantees

- Sliders are generated from `capabilities.jointCount`, grouped in sets of five so L25 remains reachable at 1366x768.
- All manual commands are complete normalized vectors. A single global `requestAnimationFrame` coalesces input; pointer release/cancel, blur, Enter, and Space cancel the pending frame and send `finalCommand: true`.
- Telemetry never writes over any joint currently being dragged. After the drag ends, subsequent telemetry is accepted.
- Stop-all locks immediately and cancels manual/quick-action/loop UI state. It is software locking, not physical emergency power-off. Unlock only clears the local lock after `unlock()` resolves and the latest real connection state is connected.
- Speed and torque controls are enabled only when capability availability and command length permit them.

## Verification

`index.test.tsx` covers complete-vector final submission, RAF coalescing, telemetry isolation, L25 rendering, controller-less disablement, connection actions, stop/unlock, and speed/torque capability gating.

In this checkout, `pnpm typecheck`, `pnpm lint`, `pnpm test`, and `pnpm build` could not start because `apps/console-v2/node_modules` is absent (`tsc` was not recognized). Install the package dependencies in the integration environment, then run all four commands from `apps/console-v2`.
