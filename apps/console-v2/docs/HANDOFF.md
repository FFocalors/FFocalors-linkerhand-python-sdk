# Console V2 集成交接

这是一份给下一位 Agent 的快速入口。详细开发规则见 [`DEVELOPMENT.md`](DEVELOPMENT.md)，旧版 PyQt 功能等价迁移基线见 [`LEGACY_FEATURES.md`](LEGACY_FEATURES.md)，模块边界见 [`MODULES.md`](MODULES.md)，历史模块交接见 [`handoffs/README.md`](handoffs/README.md)。

## 当前集成基线

- 工作树：`E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2`
- 集成基线分支：`codex/v2-rewrite`
- 最近已验收代码节点：`37fe32857d549dfb253aa2c92846f0d99e02c9c5`；当前文档 HEAD 请运行 `git log -1 --oneline --decorate` 获取
- 版本：`2.0.0-rc.1`
- Console 根：`E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk-v2\apps\console-v2`
- 最近变更：完成设备控制、动作中心、诊断、设置、全局 UI 和多语言验收修复；摄像头枚举与选择统一；视觉模仿恢复低延迟连续骨架追踪并修复半握拳闪断。最后一轮验收修复未改公共 Rust DTO 或 sidecar wire contract。

分支策略：`release/v1` 保留 V1，`codex/v2-rewrite` 是 V2 唯一集成基线，`main` 暂不用于日常开发。旧版 worktree `E:\OneDrive\Desktop\必备安装\linkerhand-python-sdk` 不是 V2 工作目录，不能从 V2 任务清理或重置。

## 一分钟接手

首次参与项目应先阅读 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)，按其中版本要求建立环境。已有仓库可从仓库根目录执行：

```powershell
Set-Location (git rev-parse --show-toplevel)
Set-Location .\apps\console-v2
git status --short --branch
git log -1 --oneline --decorate
pnpm install --frozen-lockfile
pnpm check:boundaries
pnpm check:contracts
pnpm typecheck
pnpm test
pnpm build
```

如果依赖未安装，先完成 `pnpm install --frozen-lockfile`。如果目标是 sidecar/Windows 包，再按 [`DEVELOPMENT.md`](DEVELOPMENT.md) 安装 Python 依赖并执行 fake smoke；不要因没有 O6/PCAN 就伪造硬件通过记录。

## 当前状态

已集成并可继续开发：

- Rust contracts、runtime、simulator、motion/telemetry、actions/grasp、sidecar-client、app facade。
- Tauri actor/channel assembly、browser simulator 和 release sidecar path selection。
- Device control（含 Three.js 数字孪生 3D、预设分类与自定义预设）、actions（循环 + 内置/自定义预设同步 + 关节滑块）、smart grasp、diagnostics（安全监控 + 红点 + 多关节曲线）、settings（调试模式 + 摄像头覆盖 + 持久化）、vision（连续映射 + 录制/回放）、RPS（重构）。
- 调试模式 / 虚拟手：未连接物理手时提供虚拟调试机械手，并按 `canOperate = isPhysicalDevice || debugMode` 屏蔽相应功能。
- Python strict NDJSON bridge，fake connect/telemetry/close smoke，离线 Vision assets 和 classic Worker 检查。
- Windows x64 RC 的 Tauri/NSIS、PyInstaller sidecar、portable 打包脚本和 bundle inventory。
- 2026-08-25 本机验证：24 个 Vitest 文件、179 项测试以及 typecheck、lint、boundary、frontend build 通过；Tauri dev 启动并完成当前页面操作员验收。

当前不要声称已经完成：

- O6 Windows PCAN 真实连接/读写/stop-unlock/重连验收。
- 干净 Windows 机器上的离线 NSIS 安装验收。
- 可复现的干净环境 camera/Worker/Tauri 全链路验收；本机操作员验收不等于跨机器发布证据。
- V2.0 正式发布。

## 下一步优先级

1. 先用本文件“一分钟接手”命令建立当前 HEAD 的可重复基线，保存失败命令和环境信息。
2. 若继续做软件开发，优先补齐集成测试/浏览器 QA 中尚未在当前 HEAD 复验的路径，保持 `MODULES.md` 的边界和 frozen contract。
3. 若进入发布准备，重跑真实 sidecar smoke、`pnpm build:windows`、`pnpm build:portable`，检查产物 inventory，并在 clean Windows 机器安装验证。
4. 准备硬件验收时，只使用 O6 + PCAN 的专用测试窗口；记录设备型号、手型、PCAN channel、驱动、SDK 根和每个操作结果。正式版 gate 仍是 O6 PCAN 实机验收。

## 风险和限制

- `stop` 是软件队列屏障/写锁，不是物理急停。
- fake/simulator/NDJSON smoke 不覆盖 PCAN 驱动、真实 SDK、供电、线缆和设备安全风险。
- `pnpm build` 的离线资源和 Worker 静态检查不等于真实摄像头权限、WASM、Tauri webview 初始化成功。
- `build:windows` 依赖 Windows x64、Rust MSVC target、Tauri/WebView2 环境和 sidecar 构建依赖；portable 脚本依赖 real release exe、sidecar binary 和 bundle inventory。
- 生成文件和构建输出（`node_modules`、`target`、`dist`、PyInstaller 输出、`src-tauri/binaries`、`artifacts`）不应作为业务代码提交。

## 开工前核验

- [ ] 当前路径是 `linkerhand-python-sdk-v2\apps\console-v2`，不是旧版 worktree。
- [ ] `git status --short --branch` 的已有修改已被识别；不覆盖其他 Agent 的改动。
- [ ] 当前分支是 `codex/v2-rewrite`，并已用 `git log -1` 记录实时 HEAD。
- [ ] 变更范围对应一个模块/Port/assembly seam，并先阅读相关 handoff、ADR、contract 文档。
- [ ] 若改公共 DTO，已准备 Rust source → generator → TypeScript projection → Python/sidecar/UI consumers 的同步计划。
- [ ] 若涉及硬件或打包，已明确哪些证据是 fake/static、哪些需要真实设备或 clean machine。

## 交付清单

- [ ] 代码/文档变更范围、公共契约变化和分支/基线已写明。
- [ ] 运行了与变更匹配的 Rust、Python、frontend、boundary、contract、asset、build 检查，并记录真实输出。
- [ ] 失败项、未运行项和环境原因没有被写成通过。
- [ ] 真实硬件证据包含 O6 PCAN 的设备和连接信息；没有硬件时明确写“未验证”。
- [ ] 更新 `docs/handoffs/<scope>.md`，并保留可复制的下一入口。
- [ ] 提交前确认没有把旧版 worktree 用户文件、生成产物或无关公共契约改动带入。
- [ ] 除非用户明确要求，交接完成后不自动创建 commit。
