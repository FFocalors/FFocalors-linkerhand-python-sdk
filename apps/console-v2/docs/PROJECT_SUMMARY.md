# LinkerHand Python SDK V2 项目总览

> 本文档整合仓库根目录 README、SDK API 文档、版本日志、旧版 GUI 二次开发报告，以及 `apps/console-v2/docs` 下的开发/交接/模块边界文档，形成一份统一的项目总览与接手入口。

---

## 1. 项目概述

LinkerHand Python SDK 是灵心巧手机械手的 Python 控制仓库，核心能力包括：

- `LinkerHand/`：统一 API、CAN/RS485 通讯、设备配置、状态读取和动作下发
- `example/gui_control/`：旧版 PyQt GUI 控制系统
- `example/vision_control/`：独立视觉遥操作/识别命令行原型
- `apps/console-v2/`：**V2 新版** Tauri + React + Rust 桌面控制台

当前仓库版本（SDK 包版本）：**V3.0.1**  
V2 Console 包版本：**2.0.0-rc.1**

---

## 2. V2 架构总览

```
前端 (Tauri + React + TypeScript)
        ↕ Tauri command/channel
Rust 层
  - console-contracts（公共 DTO 单一来源）
  - device-runtime / device-simulator
  - motion-engine（20 Hz 运动仲裁）
  - action-engine / adaptive-grasp（纯状态机）
  - telemetry / structured-logging
  - sidecar-client（严格 NDJSON）
  - app-runtime（UI facade ports）
        ↕ strict NDJSON envelope
Python sidecar（封装原始 LinkerHand SDK）
        ↕ CAN / RS485 / PCAN_USBBUS1
O6 机械手硬件
```

关键设计原则：

- 公共 DTO 唯一来源是 Rust `crates/console-contracts`，自动生成 TypeScript 投影
- 硬件调用只能经过 `device-adapter-api` / sidecar 边界
- Tauri shell 只负责 command/channel/actor 生命周期，不放业务逻辑
- feature 之间受 `check:boundaries` 和 ESLint restricted imports 约束，禁止跨 feature 深层导入

---

## 3. 文档地图

| 文档 | 定位 | 路径 |
|---|---|---|
| 仓库 README（中文/英文） | 项目入口、安装、基础示例、更新日志 | `README_CN.md` / `README.md` |
| SDK API 文档 | `LinkerHandApi` 公共接口说明 | `doc/API-Reference.md` |
| SDK 版本日志 | 发布版本与功能演进 | `release_3.1.0.txt` |
| 旧版 GUI 二次开发报告 | PyQt GUI 的视觉遥操作/猜拳/录制/诊断总结 | `linkerhand_gui_development_summary_report.md` |
| V2 开发进程 | V2 集成树状态、命令、模块边界、验收标准 | `apps/console-v2/docs/DEVELOPMENT.md` |
| V2 集成交接 | 给下一位 Agent 的快速入口 | `apps/console-v2/docs/HANDOFF.md` |
| 旧版功能基线 | V2 等价迁移参考（代码依据、迁移要求） | `apps/console-v2/docs/LEGACY_FEATURES.md` |
| Rust 模块边界 | 模块依赖、crate owner、 enforced boundaries | `apps/console-v2/docs/MODULES.md` |
| 模块交接记录索引 | handoff 模板和记录规则 | `apps/console-v2/docs/handoffs/README.md` |
| 各模块 handoff | runtime/sidecar/device-control/vision/rps/packaging 等 | `apps/console-v2/docs/handoffs/*.md` |

---

## 4. V2 当前开发进度（HEAD `5a854c0`）

### 4.1 已集成能力

| 层级 | 内容 |
|---|---|
| Rust contracts | 公共 DTO、枚举、WireEnvelope、结构化日志 |
| 设备层 | device-runtime 生命周期、device-simulator 确定性模拟 |
| 运动控制 | 20 Hz motion arbitration、telemetry buffer、action engine、adaptive grasp |
| Sidecar | Python strict NDJSON bridge、fake connect/telemetry/close smoke |
| Tauri 组装 | actor/command/channel assembly、browser simulator、release sidecar path |
| 前端功能 | Device control、Actions、Smart Grasp、Diagnostics、Settings、Vision、RPS |
| 管理页增强 | 动作中心循环/预设同步/关节滑块、诊断中心安全监控/红点/多关节曲线、设置页调试模式/摄像头覆盖/持久化 |
| 调试模式 | 未连接物理手时提供虚拟调试机械手；`canOperate = isPhysicalDevice || debugMode` 屏蔽相应功能 |
| Vision | 离线模型/WASM 资源清单、classic Worker + MediaPipe loader 路径、连续手部映射、录制/回放 |
| 打包发布 | Windows x64 RC：Tauri NSIS、PyInstaller sidecar、portable ZIP、bundle inventory、Windows Common Controls manifest |

### 4.2 当前版本与工作树

- **版本**：`2.0.0-rc.1`
- **集成基线分支**：`codex/v2-rewrite`（管理页开发在 `feat/pages-round2` 完成并已并入）
- **V2 工作树**：`E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2`
- **旧版 worktree**：`E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk`（有 dirty GUI 修改，不可触碰/重置）

---

## 5. 未完成项与硬门槛

以下事项在完成前**不能宣称 V2.0 正式发布**：

1. **O6 + PCAN 真实硬件验收**：连接、能力/遥测读取、位置写入、stop-unlock、显式 unlock、断开/重连、异常恢复
2. **干净 Windows 机器安装验收**：离线 WebView2 NSIS 安装及 sidecar 发现
3. **当前 HEAD 完整浏览器 QA 复验**：camera 权限、WASM loader、Tauri webview 初始化
4. **软件 stop 语义边界**：stop 是队列屏障/写锁，不是物理急停；产品或验收文字不得夸大其安全语义

---

## 6. 旧版 PyQt 功能基线（迁移参考）

旧版由 `example/gui_control/main.py` 启动，核心页面包括：

- 控制台：`ConsolePage` + `JointPanel` + `ApiManager`
- 视觉识别：`VisionPage`（MediaPipe + O6 6D 映射）
- 猜拳：`GamePage`（摄像头识别 + O6 出拳）
- 日志：`LogPage`
- 设置：`SettingsPage`（含 SAFE_OPEN 自检）
- 演示模式：`DemoPage`

已具备但需迁移/复验的能力：

- 设备连接、型号与通信（CAN/RS485、配置选择、在线探测）
- 关节控制、速度/扭矩、home、stop
- 内置预设、自定义预设（YAML 持久化、损坏备份）、循环
- 动作录制与回放（通用 action 录制 + 视觉 pose 录制）
- 关节曲线、触觉矩阵（当前旧版页面未挂载 MatrixPanel）
- 3D 姿态视图（仅 O6 6 维，`pyqtgraph.opengl` 自绘）
- 视觉模仿（EMA、deadband、max step、回放屏障、O6-only）
- 自适应抓取（Profile、标定、状态机、反馈过期、试验模式）
- 猜拳小游戏（稳定帧、倒计时、公平性策略、reset 边界）

---

## 7. Rust 模块边界（V2）

| 模块 | 责任 |
|---|---|
| `console-contracts` | 公共 DTO、枚举、WireEnvelope 单一来源 |
| `device-adapter-api` | 唯一硬件 adapter 边界 |
| `device-runtime` | adapter 生命周期与连接快照 |
| `device-simulator` | 确定性模拟器（fake 路径） |
| `motion-engine` | 20 Hz 运动仲裁、安全锁、遥测缓冲 |
| `action-engine` | 纯动作状态机 |
| `adaptive-grasp` | 纯自适应抓取状态机 |
| `telemetry` | 遥测采样与缓冲 |
| `structured-logging` | 结构化日志、分页 |
| `sidecar-client` | 严格 NDJSON client、raw vector mapper |
| `app-runtime` | UI facade Ports 和运行时组合 |
| `src-tauri` | Tauri command/channel 组装壳 |

 enforced boundaries：
- `scripts/check-boundaries.mjs` 校验 feature/import 边界
- `cargo metadata` 校验 Rust 反向依赖和循环
- Python scan 防止 sidecar 导入 UI/product state

---

## 8. 快速接手命令（V2）

```powershell
# 进入 V2 Console
Set-Location 'E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2\apps\console-v2'

# 检查状态
git status --short --branch
git log -1 --oneline --decorate

# 安装 JS 依赖
pnpm install --frozen-lockfile

# 类型/边界/测试/构建
pnpm typecheck
pnpm check:boundaries
pnpm check:contracts
pnpm test
pnpm build

# Rust 检查
cargo fmt --manifest-path Cargo.toml --all -- --check
cargo check --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

# Python sidecar smoke（不连接硬件）
python -m pytest -q sidecar/linkerhand-bridge/tests
python scripts/smoke-sidecar.py

# 前端开发服务器
pnpm exec vite --configLoader native dev --host 127.0.0.1 --port 1420
```

---

## 9. 模块交接记录索引

| 主题 | 文件 |
|---|---|
| 运行时 | `docs/handoffs/runtime.md` |
| Sidecar | `docs/handoffs/sidecar.md` |
| UI Shell | `docs/handoffs/ui-shell.md` |
| Device Control | `docs/handoffs/device-control.md` |
| Actions/Grasp | `docs/handoffs/actions-grasp.md` |
| Diagnostics | `docs/handoffs/diagnostics.md` |
| Settings | `docs/handoffs/settings.md` |
| Vision Feature | `docs/handoffs/vision-feature.md` |
| Vision Runtime | `docs/handoffs/vision-runtime.md` |
| Vision Assets Loader Fix | `docs/handoffs/vision-assets-fix.md` |
| Vision Worker Loader Fix | `docs/handoffs/vision-worker-loader-fix.md` |
| RPS Feature | `docs/handoffs/rps-feature.md` |
| Transport | `docs/handoffs/transport.md` |
| Packaging | `docs/handoffs/packaging.md` |
| Release Integration | `docs/handoffs/release-integration.md` |
| UX/Performance | `docs/handoffs/ux-performance.md` |
| StrictMode Fix | `docs/handoffs/strictmode-fix.md` |
| Architecture/CI | `docs/handoffs/arch-ci.md` |
| Contract Freeze | `docs/handoffs/contract-freeze.md` |
| Core Wiring | `docs/handoffs/core-wiring.md` |
| Integration 1/2 | `docs/handoffs/integration-1.md` / `integration-2.md` |
| M1 Integration | `docs/handoffs/m1-integration.md` |
| Management Pages（动作/诊断/设置 + 调试模式） | `docs/handoffs/management-pages.md` |

---

## 10. 当前已知限制与风险

- `stop` 是软件队列屏障/写锁，不是物理急停
- fake/simulator/NDJSON smoke 不覆盖 PCAN 驱动、真实 SDK、供电、线缆和设备安全风险
- `check:vision-assets` / `check:vision-worker` 保证文件存在和内容一致，不保证摄像头权限、WASM、Worker 和 Tauri webview 在每台机器上都成功启动
- Tauri NSIS 使用 offlineInstaller 配置，但必须在独立干净 Windows 机器复验安装
- 旧版 dirty worktree 的 GUI 修改不纳入 V2 基线；若需迁移功能，应单独做 delta 审计
- 3D 模型当前仅对 O6 6 维配置构建；多型号姿态图、L20/L25 模型和传感器显示需要 capability 设计

---

## 11. 下一步优先级建议

1. **先建立可重复基线**：执行第 8 节命令，记录失败项和环境信息
2. **补齐集成测试/浏览器 QA**：保持 `MODULES.md` 边界和 frozen contract
3. **发布准备**：重跑真实 sidecar smoke、`pnpm build:windows`、`pnpm build:portable`，检查产物 inventory，并在 clean Windows 机器安装验证
4. **硬件验收**：只使用 O6 + PCAN 的专用测试窗口；记录设备型号、手型、PCAN channel、驱动、SDK 根和每个操作结果
5. **前端体验优化**：当前已按“控制台风格 + 单屏完整显示 + 首页数字孪生预留”完成首轮 UI 收紧；如有具体页面仍溢出，可继续针对该页面做专项压缩

---

## 12. 附：旧版 GUI 二次开发成果摘要

基于原始 SDK 的旧版 PyQt GUI 已完成以下增强（详细报告见 `linkerhand_gui_development_summary_report.md`）：

- 视觉遥操作：MediaPipe HandLandmarker → O6 六维映射，EMA/deadband/max_step 平滑
- 动作录制/回放：JSON 保存、暂停/继续/倍速/循环、回放与 live 互斥
- 人机猜拳小游戏：摄像头识别 + 机械手随机出拳 + 胜负判断
- CommandTrace 全链路日志诊断
- Windows `run_gui.bat` + PCAN_USBBUS1 启动适配

这些成果是 V2 迁移的重要功能基线，但具体迁移范围需按 `LEGACY_FEATURES.md` 和当前 V2 架构重新评估。
