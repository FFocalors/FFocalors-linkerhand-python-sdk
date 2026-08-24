# 诊断中心

## 职责

面向普通操作员呈现只读的连接自检、定长关节曲线、安全监控与结构化日志。入口是 `Diagnostics`，依赖现有 `TelemetryPort`、`LogPort`，并可选注入 `DevicePort`、配置/能力快照与未来的 `DiagnosticsExportPort`。

## 不负责

本 feature 不访问设备、不发动作、不实现 Tauri Channel、sidecar、抓取、视觉或 3D，也不扩展公共 contracts。未注入的端口显示“待检查”，不会伪造设备值。

## 状态与不变量

- 曲线只保留并绘制最多 240 点；关节选择最多 25 个 capability joints，遥测回调写入 ref，RAF 每帧最多一次。
- 页面隐藏或组件卸载时取消 RAF；低可见度策略由 telemetry crate 的纯逻辑 sampler 提供。
- 日志最多从 `LogPort` 请求 512 条，过滤后只渲染可视窗口；导出失败必须显示可执行错误。
- raw 遥测仅在操作员主动打开抽屉后展示；连接自检的 `nowMs` 必须与 `TelemetrySnapshot.monotonicTimeMs` 使用同一单调时钟（默认 `performance.now()`）。
- 安全监控卡片统计当前日志窗口中的错误/警告数量，并跟踪遥测断线次数（`connected` 从 `true` 变为 `false` 时递增）。

## 错误与扩展点

读取/导出端口错误保留在页面内并给出重试或桌面导出建议。真实 Tauri 导出通过 `DiagnosticsExportPort` 注入；浏览器开发环境使用 `browserDownloadDiagnostics`。`buildConnectionChecks` 是无副作用的 view-model，可独立测试。

## 测试

feature 测试覆盖隐藏页面停绘/卸载取消 RAF、定长点数、全关节选择、遥测点不触发父级渲染、安全状态徽章（正常/需关注/异常）、日志窗口/关键词过滤/时间范围过滤/导出错误及确定性自检。运行 `pnpm test`、`pnpm typecheck`、`pnpm lint`。
