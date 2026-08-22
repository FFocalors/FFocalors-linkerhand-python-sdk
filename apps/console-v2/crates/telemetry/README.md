# telemetry

职责：提供固定容量的状态/高频遥测缓存、可见性感知采样策略和有界时间窗口纯逻辑。不负责设备 I/O、线程/RAF 调度或 UI。

公开入口：`TelemetryStore`、`TelemetrySubscription`、`VisibilityAwareSampler`、`BoundedTelemetryWindow`。

状态与不变量：容量必须大于零；环形缓存超限只丢最旧值；窗口 `sampled(limit)` 最多返回 limit 个按时间顺序的点；Hidden 永不采样，LowVisibility 使用慢 cadence。

错误：容量为零会在构造时 panic（编程错误）；采样策略本身不产生设备错误。

测试：覆盖缓存丢弃、状态/帧分流、可见性停采样和固定点数。使用 `cargo test -p telemetry`。

扩展点：未来可让 Tauri Channel/前端调度器消费采样策略，不改变窗口数据结构。
