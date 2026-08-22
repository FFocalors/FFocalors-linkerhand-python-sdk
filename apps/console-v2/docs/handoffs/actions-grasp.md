# Actions / adaptive grasp handoff

## Scope

本分支只改 action-engine、adaptive-grasp 及两个对应前端 feature。状态机不读写文件、不创建线程，也不直接调用硬件；后续由 app-runtime 实现两个 feature-local controller Port。

## Runtime handoff

- Action engine: configure model, register built-in/custom `Preset`, record with `record_at(monotonic_ms, command)`, play with `play_at`, then feed `tick(now_ms)` to `MotionPort`. `final_command` releases Playback/Loop source. Call `stop_all` for cancellation.
- `frontend/features/actions/index.tsx` exports `ActionController`: recording lifecycle, play(speed/loop), pause/resume/stop, `getState`, and `subscribe`. Without it, recording/playback controls are disabled; list/delete still use the frozen `ActionPort`.
- Adaptive grasp: create `GraspMachine::try_new(Profile)` for UI availability checks, then calibrate and call `tick(now_ms, &GraspTelemetry)`. Map `GraspOutput.command` to the existing motion port. Surface `FailureReason::operator_message()` verbatim to operators.
- `frontend/features/smart-grasp/index.tsx` exports `GraspController`: calibration, approach, grasp, release, abort, `getState`, and `subscribe`. Phase changes and touch display come only from this controller. Without it, controls are disabled and absent `rawTouch` is shown as “暂无数据”.

## Verification

Rust `fmt`, tests (action-engine, adaptive-grasp, app-runtime) and clippy pass. Frontend `typecheck`, `lint`, `test`, and `build` are run from `apps/console-v2` after dependencies are installed; feature tests cover controller calls, model boundaries, explicit tactile fallback, abort, recording, speed/loop and stop.
