# 管理页与控制页完善 handoff

## Scope

- Branch: `feat/pages-round2`（已并入集成基线 `codex/v2-rewrite`）
- Base / HEAD: 基于 `4abd593` 之后的累积改动，HEAD `5a854c0`（`feat(console-v2): 完善控制与管理页面`）
- Changed paths:
  - `frontend/features/actions/*`
  - `frontend/features/diagnostics/*`
  - `frontend/features/settings/*`
  - `frontend/features/device-control/*`
  - `frontend/features/smart-grasp/*`
  - `frontend/features/vision/*`
  - `frontend/features/rock-paper-scissors/*`
  - `frontend/app/{App.tsx,composition.ts,settings.ts}`
  - `frontend/shared/contracts/mock-runtime.ts`
  - `vite.config.ts`、`package.json`、`pnpm-lock.yaml`
- Public contracts changed: `no`（未改公共 DTO / Rust contracts / sidecar wire contract）
- Related docs: [`../DEVELOPMENT.md`](../DEVELOPMENT.md)、[`../MODULES.md`](../MODULES.md)

## Delivered

### 动作中心

- 循环序列：多选若干动作 → 创建循环，命名、调整顺序（↑/↓）、设置循环次数（1/3/5/10/无限）；循环列表可运行/编辑/删除。
- 内置预设 tab：复用首页导出的 `O6_BASIC_ACTIONS`（张开/握拳/OK/点赞）+ `O6_NUMBER_ACTIONS`（壹贰叁肆伍）。
- 自定义预设单向同步：首页自定义预设 → 动作中心「自定义」tab（带「首页」标签）；动作中心本页自定义不上传首页。
- 关节调节滑块卡片：只读，订阅遥测显示归一化位置。
- `ActionController` seam 扩展 `playLoop(loop, options)` / `stopLoop()`；`composition.ts` 提供浏览器模拟器桩。

### 诊断中心

- 删除触觉矩阵（TactileMatrix）组件、CSS 与测试。
- 新增安全监控卡片：错误/警告计数、遥测断线计数（`connected` true→false 递增）、安全徽章（正常/需关注/异常）。
- 日志面板时间范围筛选（1 分钟 / 5 分钟 / 全部），导出 JSON 遵循当前筛选。
- 侧边栏红点条件化：`Diagnostics` 接收可选 `onAlertChange`；挂载清除红点，卸载时若存在 error/warn 日志、连接异常或遥测断线则亮红点；`App.tsx` 的 `nav-alert` 受 `diagnosticsAlert` 控制。
- 关节曲线改为图例点击模式，支持多关节同时显示；至少保留一个可见关节。
- mock-runtime 初始日志改为「运行在浏览器模拟器模式，未连接物理机械手」，不再虚报「已连接」。

### 设置页 + 调试模式 + 摄像头

- 设置页新增：连接状态实时显示（含时长）、固件版本、日志级别、中英文切换、恢复出厂设置（确认对话框）、上次保存时间戳、调试模式开关。
- 持久化修复：`settingsController.load()` 现在返回 `advanced.debugMode` 与 `preferredCameraDeviceId`；`save()` 持久化摄像头 deviceId 到 localStorage 并 emit 快照；重进设置页调试模式保持开启状态。
- 摄像头全局覆盖：`App.tsx` 订阅 settings 快照，首选摄像头变化实时同步到视觉 / 猜拳默认值；两页仍可独立选择其他摄像头。
- 调试模式：
  - `ConsoleComposition` 新增 `simulator`；`isPhysicalDevice` 改为动态（`!simulator && connection.state === 'connected'`）。
  - 页面能力 `canOperate = isPhysicalDevice || debugMode`。
  - 调试模式 ON + 未连接物理手：设备控制 / 智能抓取可用（作用于虚拟手），视觉 / 猜拳「下发到机械手」禁用并显示提示。
  - 调试模式 OFF + 未连接物理手：首页连接管理、速度/扭矩、关节、快捷动作与智能抓取禁用，显示「未连接机械手」。
- 虚拟手模拟（`DeviceControl`）：调试模式下强制连接为 `connected`、遥测每 400ms 模拟、跳过真实设备调用（`submitJointVector`/`setVectorCapability`/`applyPreset`/`stopAll`/`unlock`/connect/disconnect/reconnect 均加 `virtualHand` 守卫）。
- 摄像头权限：视觉 / 猜拳每次请求预览调用 `getUserMedia` 触发权限申请；被拒时给出「在系统/浏览器设置中为本应用开启摄像头权限」的恢复指引。

### 环境修复

- `vite.config.ts`：`optimizeDeps.include` 加入 `react`、`react-dom`、`react-dom/client`、`scheduler`；`server: { host: '127.0.0.1', port: 5173, strictPort: true }`。
- 显式安装 `scheduler` 依赖（react-dom 传递依赖缺失）。

## Verification

在 `apps/console-v2` 执行的真实命令和结果：

- `pnpm typecheck`（`npx tsc -b --pretty false`）— **pass**（0 错误）
- `npx vitest run frontend/features/settings/index.test.tsx` — **pass**（14/14）
- `npx vitest run frontend/features/actions/index.test.tsx frontend/features/diagnostics/index.test.tsx frontend/features/rock-paper-scissors/index.test.tsx frontend/features/smart-grasp/index.test.tsx` — **pass**（新增循环/预设/红点/调试模式测试）
- 全量 `npx vitest run` — 122 passed / 13 failed；13 个失败均为基线（`4abd593` 之前分支）就存在的预存问题：vision（7）、styles（1）、device-control（4 个测试与未渲染的 loop 按钮/按钮命名有关）。未把预存失败写成通过。
- `pnpm tauri dev` — **pass**（Rust 编译 45s，窗口启动；未进行真实 O6 PCAN 硬件验收）
- `pnpm dev`（Vite，127.0.0.1:5173）— **pass**（页面与预打包依赖正常返回 200）

明确区分：以上均为静态检查、前端单元测试与开发服务器证据；没有 O6 PCAN 真实硬件或干净 Windows 安装证据。

## Limits / remaining gates

- O6 + PCAN 真实连接/读写/stop-unlock/重连验收未验证。
- 干净 Windows 机器离线 NSIS 安装未验证。
- 摄像头权限每次申请依赖 WebView2 / 浏览器策略；被拒后需用户在系统/浏览器设置中恢复，应用只能给出指引并重试 `getUserMedia`。
- 调试模式是「虚拟手」模拟：`stop` 仍是软件队列屏障/写锁，不是物理急停；虚拟手不会驱动任何真实硬件。
- 全量前端测试仍存在基线遗留失败（vision 手势 fixture、device-control 未渲染 loop 按钮等），接手后如需全绿需先修这些预存测试。

## Next agent entry points

1. 从 `frontend/app/App.tsx`（Shell 装配）和 `frontend/features/{actions,diagnostics,settings}/index.tsx` 开始，验证调试模式在各页面的 `canOperate` 与虚拟手行为。
2. 复验命令：`pnpm tauri dev`（真实壳）或 `pnpm dev --host 127.0.0.1 --port 1420`（浏览器模拟器）。
3. 预期风险：`isPhysicalDevice` 依赖 `runtime.deviceController.subscribeConnection`；若 Tauri 侧 connection 快照语义变化，需同步更新 Shell 判定。预存测试失败（vision/device-control/styles）与本次改动无关，勿当作本次回归。
