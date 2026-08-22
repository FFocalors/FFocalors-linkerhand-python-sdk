# Actions / adaptive grasp handoff

## Scope

本分支只改 action-engine、adaptive-grasp 及两个对应前端 feature。状态机不读写文件、不创建线程，也不直接调用硬件；后续由 app-runtime 通过现有 `ActionPort` / `GraspPort` 接线。

## Runtime handoff

- Action engine: configure model, register built-in/custom `Preset`, record with `record_at(monotonic_ms, command)`, play with `play_at`, then feed `tick(now_ms)` to `MotionPort`. `final_command` releases Playback/Loop source. Call `stop_all` for cancellation.
- Adaptive grasp: create `GraspMachine::try_new(Profile)` for UI availability checks, then calibrate and call `tick(now_ms, &GraspTelemetry)`. Map `GraspOutput.command` to the existing motion port. Surface `FailureReason::operator_message()` verbatim to operators.
- The current public UI contracts expose list/run/delete/pause only; recording, speed, loop, calibration and abort controls are intentionally local presentation state until the app-runtime facade grows those methods.

## Verification

`cargo test --manifest-path apps/console-v2/Cargo.toml -p action-engine -p adaptive-grasp -p app-runtime` passes. Frontend `typecheck/lint/test` could not run in this worktree because `apps/console-v2/node_modules` is absent.
