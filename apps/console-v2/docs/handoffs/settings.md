# Settings feature handoff

## Scope

基于集成提交 `e421e7a3d27a8ee31a1fa739603dbc3a7da50ba7`，本分支 `codex/v2-m3-settings` 只修改：

- `frontend/features/settings/index.tsx`
- `frontend/features/settings/settings.css`
- `frontend/features/settings/index.test.tsx`
- `frontend/features/settings/README.md`
- `docs/handoffs/settings.md`

没有修改 App/shared contracts/Rust/sidecar/package/lock。当前 App 尚未装配 controller，因此默认路径仍是兼容性的只读摘要；集成时由 App 注入 controller 和 ThemePort 即可启用真实操作。

## Public feature contract

`SettingsController` 是 feature-local seam：

```ts
load(): Promise<SettingsSnapshot>
validate(draft: SettingsDraft): SettingsValidationResult | Promise<SettingsValidationResult>
save(draft: SettingsDraft): Promise<SettingsSaveResult>
testSidecar(): Promise<SidecarCheckResult>
checkOfflineAssets(): Promise<OfflineAssetsCheckResult>
listCameras(): Promise<{ cameras: CameraDevice[]; permission: CameraPermission }>
subscribe(listener: (snapshot: SettingsSnapshot) => void): () => void
```

`SettingsSaveResult` 的 `applied`、`reconnectRequired`、`restartRequired`、`errors` 原样决定页面状态；保存成功不会自行更新 shared `DeviceConfig`，也不会假设设备已立即切换。`ThemePort` 提供 `getTheme`、`setTheme` 和可选订阅，主题值为 `light | dark | system`。

## Delivered behavior

- O6/L6/L7/L10/L20/G20/L21/L25、左右手、CAN channel、RS485 port/baudrate 都由 staged draft 驱动；联合类型切换会丢弃无关字段。
- 校验设备型号、左右手、CAN channel、COM 或 `/dev/tty` 串口格式、波特率和连接超时；非法草稿不会提交。
- 页面显示未保存、已保存、已应用、需要重连、需要重启服务等运行时返回状态。
- 摄像头只调用 `listCameras`，显示 permission/枚举错误并保存首选 `deviceId`；不创建 `VisionRuntime` 或打开视频流。
- 主题、版本/构建信息、sidecar 与离线资源检查入口、V2 不迁移旧配置提示已覆盖。
- 普通设置默认可见，高级设置收纳 autoReconnect、连接超时和诊断参数；无 controller 时保存、自检、摄像头操作禁用并显示未接线。
- 订阅在卸载时清理，CSS 使用紧凑双列布局、可见焦点和 reduced-motion 规则。

## Verification

在 `apps/console-v2` 执行：

- `pnpm typecheck` ✅
- `pnpm lint` ✅
- `pnpm test -- frontend/features/settings/index.test.tsx` ✅（4 tests）

全量 `pnpm test`、`pnpm build` 应在最终集成 worktree 再执行；本 worktree 仅完成依赖安装后验证过 feature test，未对现有 App 做 controller wiring。

## Integration notes

App 装配层需要创建一个持久的 SettingsController 实例并传入 `<Settings controller={...} themePort={...} />`。controller 的 `load` 应返回真实保存配置与 camera permission snapshot；`save` 应由 runtime/sidecar 处理重连或服务重启，而不是在 React 中直接重连。摄像头枚举应复用已有 vision owner 的设备列表能力，不应在 Settings 中实例化共享视觉运行时。
