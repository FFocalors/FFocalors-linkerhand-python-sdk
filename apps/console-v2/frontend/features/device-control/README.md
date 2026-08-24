# 设备控制

关节目标滑块使用 0.001 步进（0.1% 显示精度）。调试模式且无真机时，实时曲线使用由应用壳注入的共享虚拟遥测；真实设备连接时仍直接使用注入的 `TelemetryPort`，关闭调试且无真机时保持空状态。

设备控制页是普通操作员调整机械手的入口。页面不生成硬件状态，也不在浏览器里循环发命令：

- `DeviceControlController` 是本 Feature 的公开、可 Mock 控制器入口。runtime adapter 负责实现连接、状态订阅、关节目标、速度/扭矩、快速动作和循环。
- 没有 controller 时，所有会影响设备的操作均禁用，并明确显示“控制器未接入”。配置和遥测仍可用于诊断展示。
- 关节数量严格来自 `DeviceCapabilities.jointCount`，支持 O6/L6/L7/L10/L20/G20/L21/L25。关节目标始终是完整 `0..1` normalized 向量；原始值只在高级抽屉中作为命令域估算展示。
- 每个浏览器帧最多排队一次完整向量。释放、取消、失焦、Enter 或 Space 会取消排队并强制发送 `finalCommand: true`。拖动关节期间，遥测不会覆盖该关节；结束后恢复遥测同步。
- `DevicePort.stopAll()` 是软件层“停止全部动作”并立即锁定本地控制；它不是物理断电急停。恢复会调用 `unlock()`，并只有在真实连接状态仍为 connected 时解除本地锁。
- 本页显示实时关节曲线以辅助操作；诊断中心保留更长窗口、时间窗和日志联动能力。

## runtime adapter 接入

在 App 装配层创建满足 `DeviceControlController` 的对象，再将其作为 `controller` 传给 `DeviceControl`。连接状态必须由 sidecar 返回的 `ConnectionSnapshot` 通过 `subscribeConnection` 推送；动作状态通过可选的 `subscribeOperation` 推送。`startLoop`/`stopLoop` 应交给 Rust/sidecar 的真实循环执行，浏览器不能自行使用定时器替代它。

建议在 controller 内拒绝断连、锁定或能力不匹配的命令；Feature 会同时将相应控件禁用并把错误展示给操作员。

## 调试模式与虚拟手

- 页面能力 `canOperate = isPhysicalDevice || debugMode`；`virtualHand = debugMode && !isPhysicalDevice`。
- `isPhysicalDevice` 由应用壳动态传入：仅当 `!simulator` 且连接状态为 `connected`（真实手已连接）才为真。
- 调试模式 ON + 未连接物理手：应用壳注入的虚拟手强制连接为 `connected`，设备读数、曲线和动作中心草稿共享同一个持续虚拟遥测流；连接/断开/重连/关节/速度/扭矩/快捷动作/停止/解锁全部作用于虚拟手（跳过真实设备调用），并显示「调试模式：操作作用于虚拟调试机械手」提示。
- 调试模式 OFF + 未连接物理手：连接管理、关节、速度/扭矩、快捷动作与自定义预设保存全部禁用，显示「未连接机械手，设备控制不可用」提示。
- 连接/遥测读取失败时按上下文显示「未连接机械手」而非笼统错误，避免误导操作员。

## 共享导出（供动作中心复用）

- `O6_BASIC_ACTIONS`（张开/握拳/OK/点赞）、`O6_NUMBER_ACTIONS`（壹贰叁肆伍）、`O6_JOINT_NAMES`、`JointSlider`、`BasicPresetIcon`、`NumberPresetIcon`、`toVector` 已导出。
- 动作中心的「内置预设」tab 与「关节滑块」卡片直接复用上述导出，保证首页与动作中心预设一致。
- 自定义预设通过 `customPresets` / `onCustomPresetsChange` props 与动作中心单向同步（首页 → 动作中心）。
