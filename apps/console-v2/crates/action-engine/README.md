# action-engine

纯状态机动作中心，边界由 `ActionPort` 接线到运行时：

- `register_preset` 校验名称、型号、关节数和完整 `0..=1` normalized 向量；不写文件。
- `start_recording_at` / `record_at` / `pause_recording` / `resume_recording` / `finish_recording` 支持单调 fake clock、50ms 采样合并和 4096 帧上限。
- `play_at` / `tick` 支持 0.25–2×、暂停继续、有限或无限循环（无限循环软件上限 1000 次）。输出始终标记 `Playback` / `Loop`，最后一帧标记 `final_command`。
- `cancel` / `stop_all` 清除录制与回放来源；状态机不持有线程、硬件或持久化句柄。

`record` 和 `next` 保留给旧运行时的同步兼容路径；产品接线应使用带时间戳的 API。
