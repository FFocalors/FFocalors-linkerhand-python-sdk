# Console V2 共建指南

本文档用于共建者从远端全新检出 `codex/v2-rewrite` 后建立一致的 Windows 开发环境。项目状态、架构边界和验收门槛分别见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)、[`docs/MODULES.md`](docs/MODULES.md) 与 [`docs/HANDOFF.md`](docs/HANDOFF.md)。

## 1. 分支和目录

- `release/v1`：V1 保留与维护线。
- `codex/v2-rewrite`：V2 集成基线；所有 V2 分支都从这里建立。
- `main`：暂不承载 V1 或 V2 的日常开发。
- 不要求使用固定盘符或目录名。下列命令从 Git 仓库根目录推导路径。

首次克隆：

```powershell
git clone --branch codex/v2-rewrite --single-branch https://github.com/FFocalors/FFocalors-linkerhand-python-sdk.git linkerhand-python-sdk-v2
Set-Location .\linkerhand-python-sdk-v2
git status --short --branch
Set-Location .\apps\console-v2
```

开始新任务前：

```powershell
git switch codex/v2-rewrite
git pull --ff-only
git switch -c codex/v2-<milestone>-<scope>
```

不要清理、重置或覆盖其他 worktree，也不要提交 `node_modules`、`target`、`dist`、`artifacts`、PyInstaller 输出或 `src-tauri/binaries`。

## 2. 统一工具版本

推荐并由 CI 对齐的环境：

| 工具 | 版本/要求 |
| --- | --- |
| Windows | Windows 11 x64 |
| Node.js | 22.13 或更高的 Node 22；推荐 `.node-version` 中的版本 |
| pnpm | 10.x；CI 使用 `package.json` 的 `packageManager` 版本 |
| Rust | stable x86_64-pc-windows-msvc；当前已验证 1.97.1，包含 rustfmt 与 clippy |
| Python | 3.12 x64 |
| 原生依赖 | Visual Studio Build Tools（Desktop development with C++、MSVC v143、Windows SDK）与 WebView2 Runtime |

确认环境：

```powershell
node --version
pnpm --version
rustc --version
cargo --version
py -3.12 --version
```

若尚未安装 pnpm：

```powershell
corepack enable
corepack prepare pnpm@10.15.0 --activate
```

## 3. 安装与前端开发

在 `apps\console-v2` 执行：

```powershell
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --port 1420
```

浏览器开发、前端测试和生产前端构建不需要真实机械手或已打包 sidecar。离线 Vision 模型、WASM 和 Worker 均随仓库检出，不应在日常验证中改用 CDN。

## 4. Tauri 开发前置

Tauri 配置声明了发布包需要的 sidecar 和 bundle inventory。它们是生成物，不进入 Git；全新检出后首次运行 Tauri 前需生成：

```powershell
$python312 = py -3.12 -c "import sys; print(sys.executable)"
& $python312 -m pip install -r sidecar\linkerhand-bridge\requirements-windows-x64.txt

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1 -Python $python312
pnpm build
pnpm bundle:inventory
pnpm tauri dev
```

真实 sidecar 构建要求仓库根目录包含 `LinkerHand\`。仅做浏览器 UI 开发时使用上一节的 `pnpm dev` 即可。

单元测试 CI 会创建同名的空 sidecar 和最小 inventory，只为让 Tauri build script 完成编译检查。占位文件不能运行、不能连接硬件，也绝不能进入安装包或发布产物。

## 5. 提交前验证

前端与边界检查：

```powershell
pnpm typecheck
pnpm lint
pnpm test --maxWorkers=2
pnpm test:boundaries
pnpm test:lint-boundary
pnpm check:contracts
pnpm check:boundaries
pnpm build
```

Python：

```powershell
py -3.12 -m pytest -q sidecar\linkerhand-bridge\tests
py -3.12 scripts\smoke-sidecar.py
```

Rust（需要上一节的 Tauri 资源已生成；CI 会自动创建测试占位资源）：

```powershell
cargo fmt --all -- --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
```

按实际改动选择验证范围，但不能把未运行、fake/simulator 或静态检查写成真实硬件通过。

## 6. 开发约束

- 公共 DTO 只从 `crates/console-contracts` 修改，然后运行 `pnpm generate:contracts` 与 `pnpm check:contracts`。
- 前端 feature 不跨 feature 深层导入；依赖方向以 `docs/MODULES.md` 和 `pnpm check:boundaries` 为准。
- 真实硬件调用必须经过 device adapter/sidecar；React 页面不直接访问 SDK。
- 软件停止不是物理急停。O6/PCAN 测试前固定机械手、确认供电和驱动，并关闭其他控制进程。
- Vision/RPS 的浏览器或 fake 通过不等于摄像头权限、Tauri WebView2 或机械手指令链路已经验收。

## 7. 常见问题

### `resource path ... linkerhand-sidecar ... doesn't exist`

本地 Tauri 开发应按第 4 节生成真实 sidecar 和 inventory。CI 单元测试由工作流自动生成占位资源，不提交二进制。

### `pnpm install --frozen-lockfile` 拒绝安装

确认当前分支为 `codex/v2-rewrite`，Node/pnpm 版本符合第 2 节，且 `package.json` 与 `pnpm-lock.yaml` 来自同一提交。不要手工拼接锁文件。

### 拉取后 Vision hash 失败

确认根目录 `.gitattributes` 生效，不要让 Git 转换 Vision 模型、WASM 和 loader JS 的字节内容；执行 `pnpm check:vision-assets` 查看具体文件。

### 没有机械手能否开发

可以。前端、Rust 状态机、Python fake sidecar、Vision UI 和大多数测试均可离线开发；真实连接、位置写入、stop/unlock、重连和安装包验收必须单独记录为硬件/环境门槛。
