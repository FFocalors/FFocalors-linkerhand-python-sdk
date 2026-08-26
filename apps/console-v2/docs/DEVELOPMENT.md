# Console V2 开发进程

本文档是 `apps/console-v2` 的开发入口，记录当前集成树的真实状态、可复现命令和交接约束。旧版 PyQt 行为基线见 [`LEGACY_FEATURES.md`](LEGACY_FEATURES.md)；它用于 V2 等价迁移，不是用户手册或硬件验收报告。旧版 SDK 的一般说明仍在仓库根目录的 `README_CN.md` / `README.md`。

## 当前基线

截至 2026-08-26，本文档对应的工作树为：

- 路径：`E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2`
- 集成基线分支：`codex/v2-rewrite`
- 最近已验收代码节点：`37fe328`（`feat(console-v2): complete acceptance fixes and vision tracking`）；文档提交后的实时 HEAD 以 `git log -1 --oneline --decorate` 为准
- Console 包和 Rust workspace 版本：`2.0.0-rc.1`
- 前端包管理：`pnpm`，锁文件版本为 pnpm 9

旧版工作树 `E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk` 使用 V1 保留分支 `release/v1`。V2 开发、验证、提交均在上面的 `linkerhand-python-sdk-v2` 路径与 `codex/v2-rewrite` 基线上进行，不在 `main` 上开展 V1 或 V2 日常开发。

## 已完成里程碑

当前集成树已经包含以下可从代码和交接记录追溯的部分：

- Rust workspace 的 `console-contracts`、设备运行时/模拟器、20 Hz motion arbitration、telemetry、action、adaptive grasp、structured logging、sidecar client 和 `app-runtime` facade。
- `src-tauri` actor/command/channel 组装层，以及前端 feature-local controller 注入；业务逻辑不应下沉到 Tauri shell。
- Python NDJSON sidecar 的严格 envelope、模型/传输/向量校验、fake 模式和软件 stop/unlock barrier。
- Console UI 的 device control、actions、smart grasp、diagnostics、settings、vision 和 rock-paper-scissors feature；feature 之间受 boundary checker 和 ESLint restricted imports 约束。
- Rust 作为公共 DTO 单一来源，生成 `frontend/shared/contracts/generated.ts`，并有 `check:contracts` freshness check。
- Vision 离线模型/WASM 资源清单、classic Worker + MediaPipe loader 路径、`check:vision-assets` / `check:vision-worker`。
- Windows x64 RC 打包路径：真实 sidecar 的 PyInstaller 构建、Tauri NSIS、portable ZIP、bundle inventory，以及 Windows Common Controls manifest 检查。

各模块的历史分支、设计不变量和模块级验证记录见 [`MODULES.md`](MODULES.md) 与 [`handoffs/`](handoffs/README.md)。其中旧 handoff 的通过记录是当时分支的证据，不自动等同于当前 HEAD 的新一轮验证。

## 管理页、控制页与验收完善（4abd593—37fe328）

在 `4abd593`（设备控制页重构）之后，控制台围绕「动作中心 / 诊断中心 / 设置页 / 调试模式」完成管理页集成，并在 `37fe328` 前完成多轮本机 Tauri 验收修复。公共 Rust DTO 和 sidecar wire contract 未在最后一轮前端验收修复中改变。主要能力如下：

### 动作中心（`frontend/features/actions`）

- 循环序列：多选若干动作创建循环，支持命名、调整顺序、设置循环次数（1/3/5/10/无限）；循环列表可运行/编辑/删除。`ActionController` 扩展了 `playLoop`/`stopLoop`。
- 内置预设同步：首页 `O6_BASIC_ACTIONS`（4 个基础）+ `O6_NUMBER_ACTIONS`（5 个数字）作为动作中心的「内置预设」tab。
- 自定义预设单向同步：首页自定义预设同步到动作中心（带「首页」标签）；动作中心本页自定义不上传首页。
- 关节调节滑块卡片：只读展示当前关节位置，订阅遥测实时刷新。

### 诊断中心（`frontend/features/diagnostics`）

- 删除触觉矩阵（TactileMatrix），页面聚焦安全监控与日志审查。
- 新增安全监控卡片：错误/警告计数、遥测断线计数、安全状态徽章（正常/需关注/异常）。
- 日志面板新增时间范围筛选（最近 1 分钟 / 5 分钟 / 全部），导出遵循当前筛选。
- 侧边栏红点条件化：进入诊断页清除红点；检测到 error/warn 日志、连接异常或遥测断线时重新亮起。
- 关节曲线改为图例点击模式，支持多关节同时显示（替代原先单选下拉）。
- 修复日志虚报：未连接物理机械手时不再伪造「已连接」日志。

### 设置页（`frontend/features/settings`）

- 连接状态实时显示（含已连接时长轮询）。
- 固件版本显示、日志级别配置、中英文切换、恢复出厂设置（含确认）、上次保存时间戳。
- 调试模式开关（见下）。
- 摄像头首选设置持久化并全局覆盖视觉/猜拳的默认摄像头；视觉/猜拳仍可独立选择其他摄像头。

### 调试模式与虚拟手

- `ConsoleComposition` 新增 `simulator` 判定；`isPhysicalDevice` 改为**动态**：仅当 `!simulator` 且连接状态为 `connected`（真实手已连接）才为真。
- 页面能力规则：`canOperate = isPhysicalDevice || debugMode`。
  - 调试模式 ON + 未连接物理手：设备控制 / 智能抓取可用（作用于虚拟手），但视觉模仿 / 猜拳互动的「下发到机械手」按钮禁用并显示提示。
  - 调试模式 OFF + 未连接物理手：首页连接管理、速度/扭矩、关节控制、快捷动作与智能抓取全部禁用，显示「未连接机械手」提示。
- 虚拟手模拟：`DeviceControl` 在调试模式下强制连接为 `connected`、遥测每 400ms 模拟、跳过真实设备调用；连接/遥测读取失败时按上下文显示「未连接机械手」而非笼统错误。
- 摄像头权限：视觉 / 猜拳每次请求预览都会调用 `getUserMedia` 触发权限申请；被拒时给出「在系统/浏览器设置中为本应用开启摄像头权限」的恢复指引。

### 环境修复

- Vite 依赖预打包：`vite.config.ts` 的 `optimizeDeps.include` 加入 `react`、`react-dom`、`react-dom/client`、`scheduler`，修复 React 19 + CJS 导致的空白页。
- Vite 开发服务器固定 `host: 127.0.0.1`、`strictPort`，避免 IPv4/IPv6 绑定不一致与端口残留导致的空白页。
- 显式安装 `scheduler` 依赖（react-dom 的传递依赖缺失问题）。

### 2026-08-25 验收节点

- 设备控制：首页恢复初始张开姿态、关节目标内部滚动、调试模式虚拟曲线、快捷动作配色和数字/交互色语义完成收口。
- 动作中心：姿态编辑与动作编排按左右工作流重排，支持内置/数字/自定义姿态、顺序关键帧、方向、低于或等于 1x 的倍速与循环次数。
- 设置与摄像头：摄像头枚举改为页面加载即执行，权限查询不再阻塞首屏列表；修复左右手单选框命中区域污染。
- Vision/RPS：共享显式摄像头选择；视觉模仿恢复一手、最高 640x480 推理输入，连续 21 点骨架不再受离散手势门控，并修复 `object-fit: contain` 坐标错位与短暂漏检闪断。
- 诊断与 UI：调试虚拟曲线、真实结构化日志入口、紧凑曲线卡片、语言切换、高级设置布局和全局 UI token 完成统一。
- 本节点实际执行并通过：`pnpm vitest run --maxWorkers=2`（24 个文件、179 项测试）、`pnpm typecheck`、`pnpm lint`、`pnpm check:boundaries`、`pnpm build`。Tauri dev 在本机启动并完成操作员页面验收；这不替代 O6 PCAN 实机或干净 Windows 安装验收。

详细的分页改动、端口 seam 与验证记录见 [`handoffs/management-pages.md`](handoffs/management-pages.md)。

## 未完成项与硬件门槛

以下事项不能用 fake sidecar、Rust 单元测试或静态构建代替：

1. 需要在 Windows x64 上使用真实 O6 + PCAN 设备完成正式验收：连接、能力/遥测读取、位置写入、停止后写入锁、显式 unlock、断开/重连和异常恢复。
2. 需要在干净 Windows 机器上验证离线 WebView2 NSIS 安装和安装后的 sidecar 发现；已有构建下载并嵌入离线 WebView2，但不等于完成了干净机安装验收。
3. 当前工作树的最终 RC 需要重新执行完整验证和必要的浏览器交互 QA；不要把其他分支或旧 handoff 的浏览器/打包记录写成当前 HEAD 已验证。
4. 软件 `stop` 是队列屏障和写锁，不是物理断电，也不是硬件急停。产品或验收文字不得夸大其安全语义。

正式版仍以 O6 Windows PCAN 实机验收为硬门槛；在该门槛完成前只能称为 RC/simulator-ready，不得宣称 V2.0 formal release。

## 目录入口

从 `apps/console-v2` 开始：

旧版功能迁移对照：[`LEGACY_FEATURES.md`](LEGACY_FEATURES.md)。

| 目录 | 责任 |
| --- | --- |
| `frontend/app` | App 壳、路由、composition、Tauri/browser runtime 装配 |
| `frontend/features/*` | 页面和 feature-local controller；不得直接互相导入 |
| `frontend/shared` | UI、theme、contracts、utilities、vision runtime 等共享基础 |
| `frontend/workers/vision-worker` | Vision Worker 协议和 classic loader 边界 |
| `crates/console-contracts` | 公共 DTO、枚举、envelope 的 Rust 源 |
| `crates/device-adapter-api` | 唯一硬件 adapter 边界 |
| `crates/device-runtime` / `device-simulator` | adapter 生命周期与确定性模拟器 |
| `crates/motion-engine` / `telemetry` | 运动仲裁、安全锁、遥测缓冲 |
| `crates/action-engine` / `adaptive-grasp` | 纯状态机 |
| `crates/sidecar-client` | Rust 侧严格 NDJSON client 和 raw vector mapper |
| `crates/app-runtime` | UI facade Ports 和运行时组合 |
| `src-tauri` | Tauri command/channel assembly shell；不放业务逻辑 |
| `sidecar/linkerhand-bridge` | Python SDK sidecar、协议和真实/fake adapter |
| `docs/contracts` / `docs/adr` / `docs/handoffs` | 契约、架构决策和模块交接记录 |

模块依赖和边界以 [`MODULES.md`](MODULES.md) 及 `scripts/check-boundaries.mjs` 为准。

## Windows 环境准备

完整的全新克隆、工具版本和 Tauri 首次运行说明见 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)。建议在 PowerShell 中执行；每个共建者都应先确认 `git status` 和 `git branch --show-current`。

```powershell
Set-Location (git rev-parse --show-toplevel)
Set-Location .\apps\console-v2
git status --short --branch
git branch --show-current
```

需要：

- Windows x64、Git、Node.js 22.13+、pnpm 10、stable Rust/Cargo MSVC 工具链（当前验证 1.97.1），以及 Tauri Windows 构建所需的 MSVC 工具链和 WebView2 环境。
- Python 3.12 x64（sidecar 最低支持 3.10，共建与 CI 统一使用 3.12）。
- 真实 sidecar 构建需要仓库根目录中包含 `LinkerHand\`；`scripts/build-sidecar.ps1` 默认从当前仓库推导 SDK 根，也可显式传 `-SdkRoot`。
- 真实硬件验收还需要 O6、PCAN 适配器/驱动、正确供电和不会与其他控制程序冲突的设备连接。没有硬件时只运行 fake 路径。

安装 JavaScript 依赖：

```powershell
pnpm install --frozen-lockfile
```

安装 sidecar 的 Windows 构建依赖（只在需要 PyInstaller 或真实 sidecar smoke 时）：

```powershell
$python312 = py -3.12 -c "import sys; print(sys.executable)"
& $python312 -m pip install -r sidecar/linkerhand-bridge/requirements-windows-x64.txt
```

## 常用启动、检查、测试和打包命令

### 开发运行

```powershell
# 浏览器/Vite 开发服务器
pnpm dev --host 127.0.0.1 --port 1420

# Tauri 开发壳；beforeDevCommand 会启动同一 Vite 地址
pnpm tauri dev
```

未明确选择真实设备时，使用浏览器 simulator 或显式 fake sidecar。不要把 simulator 连接状态写成真实硬件在线。

### 前端和边界检查

```powershell
pnpm typecheck
pnpm lint
pnpm test
pnpm test:boundaries
pnpm test:lint-boundary
pnpm check:boundaries
pnpm check:contracts
pnpm check:vision-assets
pnpm check:vision-worker
pnpm check:native-windows
pnpm build
```

`pnpm build` 会先检查离线 Vision 资源，生成 Vite/TypeScript 产物，再检查 classic Vision Worker。`pnpm vision:download` 会访问网络，仅在 manifest 资源缺失且获准下载时使用；正常验证应依赖仓库内已记录 hash 的资源。

### Rust 和 Python

```powershell
cargo fmt --manifest-path Cargo.toml --all -- --check
cargo check --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

py -3.12 -m pytest -q sidecar/linkerhand-bridge/tests
py -3.12 scripts/smoke-sidecar.py
```

`smoke-sidecar.py` 是真实 stdin/stdout NDJSON 子进程边界测试，不连接硬件。它检查 fake bridge 的 connect、getTelemetry、close 三个 envelope，以及 stdout 没有 SDK 日志污染。

### 真实 sidecar、Windows 构建和 portable 包

```powershell
# 默认 SDK 根目录是当前 V2 仓库根；也可传 -SdkRoot 'D:\path\to\sdk-root'
$python312 = py -3.12 -c "import sys; print(sys.executable)"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Python $python312
py -3.12 scripts/smoke-sidecar.py --executable 'src-tauri\binaries\linkerhand-sidecar-x86_64-pc-windows-msvc.exe'

# build:windows 会执行 Tauri beforeBuildCommand：前端 build、sidecar build、bundle inventory
pnpm build:windows

# 已有 release exe、sidecar binary 和 artifacts/bundle-inventory.json 后
pnpm bundle:inventory
pnpm build:portable
```

若只需构建前端，不要误用 `pnpm build:windows`；它需要 Rust target、sidecar 构建依赖和 Windows Tauri 环境。`build:portable` 会写入 `apps/console-v2/artifacts`，生成物属于构建输出，不应作为业务源码提交。

## 模块化开发流程

1. 先读 [`MODULES.md`](MODULES.md)、相关 ADR 和最近的 [`handoffs/`](handoffs/README.md)，确认模块 owner、依赖方向和可用 Port。
2. 将工作限定在一个 feature、一个 Rust crate 或一个明确的 assembly seam；先写/更新模块测试，再实现行为。
3. 公共 DTO 只改 `crates/console-contracts`；运行 `pnpm generate:contracts` 后再运行 `pnpm check:contracts`，不要手改生成的 TypeScript。
4. 硬件调用只能经过 `device-adapter-api` / sidecar 边界；Tauri 只负责命令、channel、actor 生命周期和错误映射。
5. 新增跨模块能力时优先增加已有 facade Port 或 feature-local controller；不要引入全局 event bus、跨 feature 深层相对导入或浏览器 timer 直接发硬件命令。
6. 完成后执行与影响范围匹配的 Rust、Python、frontend、boundary、contract、asset 和 build 检查，并在 handoff 记录实际命令、结果、未验证项和下一入口。

## Worktree、分支和提交规则

- 集成基线是 `codex/v2-rewrite`；当前 V2 集成 worktree 是 `E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2`。
- `release/v1` 从当前 `main` 引出，保存 V1 代码；`codex/v2-rewrite` 保存 V2 开发线。`main` 暂不承载任何代际的日常开发，待正式发布策略确定后再做晋升。
- 旧版 `E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk` 是独立 worktree；不要从 V2 任务清理、重置或覆盖其中的用户文件。
- 模块开发使用 `codex/v2-<milestone>-<scope>` 分支；合并/快进前先核对目标分支和 worktree，避免在集成树直接重写历史。
- 提交应小而可回溯，subject 标明 scope（例如 `feat(console-v2): ...`、`docs(console-v2): ...`）。不要把 `node_modules`、`target`、`dist`、PyInstaller `build/dist`、`src-tauri/binaries` 或 `artifacts` 中的生成物混入源码提交。
- 交接文档写分支、基线/HEAD、公共契约是否变化、验证命令和硬件/环境限制。仅在用户明确要求时提交；本开发文档本身不要求自动 commit。

## 公共契约变更流程

公共边界包含 Rust DTO/enums、camelCase JSON、`WireEnvelope`、sidecar operation/error、Python schema、生成 TypeScript 和 raw-capability fixture。变更时：

1. 先更新 `crates/console-contracts` 及必要的 `docs/contracts` / ADR，说明兼容性和所有消费者。
2. 用 `pnpm generate:contracts` 更新投影；用 `pnpm check:contracts` 确认没有漂移。
3. 同步 Rust serde、Python protocol、sidecar-client、frontend Port 与测试；不要只改一侧字段。
4. 运行 `pnpm check:boundaries`、`cargo test --workspace`、sidecar pytest、前端 typecheck/test/build，并在 handoff 明确契约版本和迁移要求。

## 验收标准

一个模块可交接至少应具备：

- 代码边界通过，公共契约没有未记录的漂移。
- 与模块相关的单元/集成测试、类型检查、lint 和构建命令有可复制记录。
- fake sidecar / simulator 证明不依赖硬件的路径；涉及真实设备的结论单独标为硬件证据。
- UI 行为有浏览器或 Tauri 交互证据时，记录浏览器尺寸、入口、结果和失败截图/日志位置；静态 `pnpm build` 不等于 camera/Worker 已初始化。
- 打包交付记录版本、目标架构、产物路径、hash（如有）和 clean-machine/hardware gate 状态。
- stop/unlock、错误恢复、未支持能力和降级 UI 使用准确语义，不能宣称物理急停或真实设备在线。

## 已知限制

- `2.0.0-rc.1` 是 RC，不是正式版；O6 PCAN 实机验收仍未被本开发入口证明完成。
- fake adapter、device simulator 和 sidecar smoke 不覆盖 PCAN 驱动、真实 SDK、供电、线缆、设备状态或运动风险。
- offline asset hash 检查保证文件存在和内容一致，不保证摄像头权限、WASM loader、浏览器 Worker 和 Tauri webview 在每台机器上都成功启动。
- Tauri NSIS 使用 offlineInstaller 配置，但必须在独立干净 Windows 机器复验安装；本地 build 成功不是安装验收。
- 任何新的硬件、驱动、SDK 或协议假设都必须在交接文档中写成可验证的门槛，而不是默认为已具备。
