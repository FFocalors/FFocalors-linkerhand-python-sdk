# Settings feature

设置页是普通操作员的配置入口。它只维护 `SettingsDraft`，不会直接调用设备、创建摄像头运行时或把草稿写进 shared contracts。

## 注入边界

应用装配层把 feature-local `SettingsController` 传给 `Settings`：

```tsx
<Settings
  model={config.model}
  transport={config.transport}
  controller={settingsController}
  themePort={appThemePort}
/>
```

controller 必须提供 `load`、`validate`、`save`、`testSidecar`、`checkOfflineAssets`、`listCameras` 和 `subscribe`。`save` 的 `applied`、`reconnectRequired`、`restartRequired`、`errors` 是唯一的保存结果来源；页面不会假装硬件即时生效。保存期间所有可编辑字段锁定，并以 draft revision 防止迟到的旧保存结果覆盖当前草稿。订阅在卸载时清理；摄像头是一次性枚举调用，当前没有 camera subscription。

`ThemePort` 是应用主题适配器（`getTheme`、`setTheme`、可选 `subscribe`），支持 `light`、`dark`、`system`。主题持久化仍由应用层负责。

## 设备与摄像头规则

- 支持 O6、L6、L7、L10、L20、G20、L21、L25，左右手和 CAN/RS485 为类型安全联合类型。
- transport 切换会清除另一种传输的字段，只提交当前联合分支；CAN channel、串口格式、波特率、超时在提交前校验。
- 摄像头只通过 controller 枚举并保存首选 `deviceId`，设置页不创建 `VisionRuntime`、不请求视频流，也不打开第二个摄像头。
- 摄像头权限拒绝或枚举失败时显示普通用户可执行的恢复说明和“重试摄像头”；异步失败会收敛为页面状态，不产生 unhandled rejection。
- 无 controller 时是只读展示，保存、自检和摄像头枚举禁用，并明确显示“未接线”。
- V2 不迁移旧配置；页面会明确提示操作员重新确认设置。

高级字段（自动重连、连接超时、诊断参数）默认收在抽屉中。普通设置默认在 1366×768 紧凑布局可见，并尊重 `prefers-reduced-motion`。
