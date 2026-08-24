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

controller 必须提供 `load`、`validate`、`save`、`testSidecar`、`checkOfflineAssets`、`listCameras`、`openCameraPrivacySettings`、`getConnectionState`、`getFirmwareVersion`、`getLogLevel`、`setLogLevel`、`getLocale`、`setLocale`、`resetToFactory` 和 `subscribe`。`save` 的 `applied`、`reconnectRequired`、`restartRequired`、`errors` 是唯一的保存结果来源；页面不会假装硬件即时生效。保存期间所有可编辑字段锁定，并以 draft revision 防止迟到的旧保存结果覆盖当前草稿。订阅在卸载时清理；摄像头是一次性枚举调用，当前没有 camera subscription。

`ThemePort` 是应用主题适配器（`getTheme`、`setTheme`、可选 `subscribe`），支持 `light`、`dark`、`system`。主题持久化仍由应用层负责。

## 设备与摄像头规则

- 支持 O6、L6、L7、L10、L20、G20、L21、L25，左右手和 CAN/RS485 为类型安全联合类型。
- transport 切换会清除另一种传输的字段，只提交当前联合分支；CAN channel、串口格式、波特率、超时在提交前校验。
- 摄像头只通过 controller 枚举并保存首选 `deviceId`，设置页不创建 `VisionRuntime`、不请求视频流，也不打开第二个摄像头。
- 摄像头结果区分 WebView 拒绝、Windows 隐私设置阻止、无设备和设备占用，并显示普通用户可执行的恢复说明和“重试摄像头”。Windows 桌面应用可能没有单独条目，应检查“允许桌面应用访问摄像头”；“打开 Windows 摄像头设置”只启动 `ms-settings:privacy-webcam`，不会自动修改系统隐私开关。
- 无 controller 时是只读展示，保存、自检和摄像头枚举禁用，并明确显示“未接线”。
- V2 不迁移旧配置；页面会明确提示操作员重新确认设置。

## 新增功能

### 实时连接状态

- 设备连接卡片显示实时连接状态指示器（绿/琥珀/红/灰圆点）和文字（已连接 / 连接中... / 已断开 / 未知）。
- controller 每 2 秒轮询 `getConnectionState()`；状态变更时 UI 自动更新。
- 已连接时显示“已连接时长”，每秒刷新一次。
- `SettingsSnapshot` 支持 `connectionState?: ConnectionStateInfo`，其中 `ConnectionStateInfo` 为 `{ state: 'connected' | 'disconnected' | 'connecting' | 'error'; since?: number }`。

### 固件版本

- 版本与离线资源卡片显示固件版本，格式：`固件 v1.2.3 · 构建 2024-01-15`。
- 通过 `getFirmwareVersion()` 异步获取； unavailable 时显示“固件版本未知”。
- `SettingsSnapshot` 支持 `firmwareVersion?: FirmwareVersion`，其中 `FirmwareVersion` 为 `{ version: string; buildDate?: string }`。

### 日志级别配置

- 高级设置中新增日志级别下拉框，可选 `trace` / `debug` / `info` / `warn` / `error`。
- 变更时调用 `setLogLevel(level)` 并更新 draft；页面显示当前日志级别徽章。
- `SettingsSnapshot` 支持 `logLevel?: LogLevel`。

### 语言 / 地区设置

- 外观卡片中新增语言切换按钮组：中文 / English。
- 变更时调用 `setLocale(locale)` 并更新 draft。
- `SettingsSnapshot` 支持 `locale?: 'zh' | 'en'`。

### 保存状态与时间戳

- 保存成功后，顶部状态徽章显示“上次保存: YYYY-MM-DD HH:MM:SS” tooltip。
- 当 draft 与 savedDraft 不一致时，状态徽章显示为琥珀色“未保存”。

### 恢复出厂设置

- 高级设置中新增“恢复默认设置”按钮，点击后弹出内联确认对话框：“确定要恢复所有设置为出厂默认值吗？此操作不可撤销。”
- 确认后调用 `resetToFactory()`，随后重新加载 `load()` 和各项状态接口，刷新页面快照。
- 保存中和未接线时按钮禁用。

### 调试模式（虚拟调试机械手）

- 高级设置中新增「调试模式」开关。
- `controller.getDebugMode()` / `controller.setDebugMode(enabled)` 持久化到 `localStorage`（`linkerhand-console-v2-debug-mode`）。
- 未连接真实物理手时，开启调试模式 = 提供一个虚拟调试机械手：设备控制、智能抓取可用，但视觉模仿 / 猜拳互动的「下发到机械手」按钮禁用。
- 关闭调试模式 + 未连接物理手：首页连接管理、速度/扭矩、关节、快捷动作与智能抓取全部禁用。
- 真实物理手已连接时（`isPhysicalDevice` 为真），无论开关状态均可用完整功能。
- 调试模式通过 `onDebugModeChange` 回传给应用壳（`App.tsx`），并同步到所有页面。
- `SettingsSnapshot` 支持 `debugMode?: boolean`；`load()` 返回 `advanced.debugMode`，`draftFromSnapshot` 合并，保证重进设置页状态保持。

### 摄像头首选设置全局覆盖

- 设置页保存 `preferredCameraDeviceId` 时写入 `localStorage`（`linkerhand-console-v2-camera-device-id`），并随 `load()`/`save()` 快照 `emit`。
- 应用壳（`App.tsx`）订阅 settings 快照，把首选摄像头实时同步给视觉模仿 / 猜拳互动作为默认摄像头。
- 视觉 / 猜拳仍可在各自页面独立选择其他摄像头，不会回写设置页的首选值。

### 保存持久化

- `save()` 现在同时持久化设备配置（model/hand/transport）、首选摄像头 deviceId 与调试模式。
- 修复了旧实现中调试模式「重进设置页变回关闭」的竞态：`load()` 直接返回 `advanced.debugMode`，不再依赖单独的 `getDebugMode()` effect 与 `load()` 的先后顺序。

### 扩展的 SettingsController 接口

```ts
getConnectionState(): Promise<ConnectionStateInfo>;
getFirmwareVersion(): Promise<FirmwareVersion>;
getLogLevel(): Promise<LogLevel>;
setLogLevel(level: LogLevel): Promise<void>;
getLocale(): Promise<'zh' | 'en'>;
setLocale(locale: 'zh' | 'en'): Promise<void>;
getDebugMode(): Promise<boolean>;
setDebugMode(enabled: boolean): Promise<void>;
resetToFactory(): Promise<void>;
```

### 扩展的 SettingsSnapshot

```ts
interface SettingsSnapshot {
  config: DeviceConfig;
  preferredCameraDeviceId?: string | null;
  cameraPermission?: CameraPermission;
  theme?: ThemePreference;
  version?: string;
  build?: string;
  cameras?: CameraDevice[];
  advanced?: Partial<SettingsAdvancedDraft>;
  connectionState?: ConnectionStateInfo;
  firmwareVersion?: FirmwareVersion;
  logLevel?: LogLevel;
  locale?: 'zh' | 'en';
  debugMode?: boolean;
}
```

## 布局与样式

- 保持现有 `.settings-grid` 两列布局，响应式断点 950px 下切为单列。
- 连接状态指示器使用语义化 CSS 变量（`--green`、`--amber`、`--danger`、`--muted`）。
- 所有新组件（状态圆点、确认对话框、语言切换、日志级别下拉）均复用现有 `.card`、`.button`、`.badge` 样式体系。
- 尊重 `prefers-reduced-motion: reduce`。
