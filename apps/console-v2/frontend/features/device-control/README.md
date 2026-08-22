# 设备控制

设备控制页是普通操作员调整机械手的入口。页面不生成硬件状态，也不在浏览器里循环发命令：

- `DeviceControlController` 是本 Feature 的公开、可 Mock 控制器入口。runtime adapter 负责实现连接、状态订阅、关节目标、速度/扭矩、快速动作和循环。
- 没有 controller 时，所有会影响设备的操作均禁用，并明确显示“控制器未接入”。配置和遥测仍可用于诊断展示。
- 关节数量严格来自 `DeviceCapabilities.jointCount`，支持 O6/L6/L7/L10/L20/G20/L21/L25。关节目标始终是完整 `0..1` normalized 向量；原始值只在高级抽屉中作为命令域估算展示。
- 每个浏览器帧最多排队一次完整向量。释放、取消、失焦、Enter 或 Space 会取消排队并强制发送 `finalCommand: true`。拖动关节期间，遥测不会覆盖该关节；结束后恢复遥测同步。
- `DevicePort.stopAll()` 是软件层“停止全部动作”并立即锁定本地控制；它不是物理断电急停。恢复会调用 `unlock()`，并只有在真实连接状态仍为 connected 时解除本地锁。
- 关节趋势和完整曲线属于诊断中心；本页只显示当前摘要并提供进入诊断中心的入口。

## runtime adapter 接入

在 App 装配层创建满足 `DeviceControlController` 的对象，再将其作为 `controller` 传给 `DeviceControl`。连接状态必须由 sidecar 返回的 `ConnectionSnapshot` 通过 `subscribeConnection` 推送；动作状态通过可选的 `subscribeOperation` 推送。`startLoop`/`stopLoop` 应交给 Rust/sidecar 的真实循环执行，浏览器不能自行使用定时器替代它。

建议在 controller 内拒绝断连、锁定或能力不匹配的命令；Feature 会同时将相应控件禁用并把错误展示给操作员。
