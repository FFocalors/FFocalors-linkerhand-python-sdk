# Diagnostics M3 handoff

分支：`codex/v2-m3-diagnostics`，基线：`4488ab3`。

## 交付

- telemetry crate 增加 `VisibilityAwareSampler` 和 `BoundedTelemetryWindow`，Hidden 停止采样、LowVisibility 降频，窗口固定容量并支持定点采样。
- structured-logging crate 增加关键词过滤、批量写入、有界分页（单页最多 512）与可返回错误的 JSON 导出，含 100,000 条回归测试。
- diagnostics feature 从静态 Mock 改为可独立渲染的曲线、触觉矩阵、连接自检和窗口化日志；只依赖现有端口，未注入的能力明确显示待检查。
- 浏览器下载仅为 feature 内 adapter；真实 Tauri 导出通过 `DiagnosticsExportPort` 留在 Port 边界。
- 复验修正：连接自检使用 `performance.now()` 与遥测单调时间，关节选择安全上限为 25（不再误截断到 4），触觉首帧/不完整 raw 数组显示等待态，日志导出遍历整个有界 store 而不受 UI 单页 512 限制。

## 边界

没有修改 generated.ts、console-contracts、app-runtime、Tauri、其他 feature 或 workspace 依赖。当前 App 装配仍只传入 `LogPort`，因此开发壳会显示遥测/设备待检查；未来装配可按 `Diagnostics` props 注入现有 `TelemetryPort`/`DevicePort`。

## 测试覆盖

前端 diagnostics 测试覆盖：无能力、首帧等待、J25 选择、单调时钟、自检建议、日志窗口/关键词过滤、visibilitychange 与卸载取消 RAF。Rust telemetry/structured-logging 共 7 项单元测试，其中 structured-logging 含 1,024 容量导出不截断和 100,000 批量输入回归。

## 验证

在 `apps/console-v2` 运行：

```text
cargo fmt --all --check
cargo test -p telemetry -p structured-logging
cargo clippy -p telemetry -p structured-logging --all-targets -- -D warnings
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```
