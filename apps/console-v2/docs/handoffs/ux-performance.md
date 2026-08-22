# UX / Performance Handoff

## 交付信息

- 分支：`codex/v2-m5-ux-perf`
- 提交：`55ffff2`（离线主题、动效和布局基线）
- 本次交接提交：`d2354c6`（CSS 回归测试与本交接记录）
- 修改模块：`frontend/app`、`frontend/features/diagnostics`、`frontend/features/rock-paper-scissors`、`frontend/features/settings`、`frontend/features/vision`
- 公共接口：无变化；未修改 Rust、sidecar、Tauri 配置、package 或 lock 文件。

## 实施内容

- 移除 Google Fonts 远程依赖，统一使用 Windows/system-ui 本地字体栈和本地等宽字体回退。
- 建立 light/dark 语义 token，包括 surface、文字、边框、状态、相机底色、焦点环和阴影；深色模式仅更新根 token，不重建页面。
- 页面路由内容使用单一 `.page-transition` wrapper，150ms 自定义 cubic-bezier 的 opacity/translate 进入动效；移除卡片逐项 rise 和 hover 位移动效。
- 页面、主题过渡使用 120–180ms；range、关节滑块没有 CSS transition/animation，保留现有局部 RAF 和释放时 final commit 语义。
- 全局 reduced-motion 关闭非必要动画和过渡；主要按钮、导航、图标按钮和摘要控件提供约 44px 命中区域及清晰 `:focus-visible`。
- 1366×768 桌面布局保持侧栏、顶部操作区和主工作区不横向溢出；1100px 以下侧栏收起，720px 以下网格和表格采用单列策略。
- 诊断图使用当前主题 CSS token 取色；诊断导航圆点为装饰，未宣称存在真实告警。

## 验证

在 `apps/console-v2` 执行并通过：

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test --run`：17 个测试文件、96 个测试通过
- `pnpm check:contracts`（仅已有 ts-rs serde 属性解析 warning）
- `pnpm check:vision-assets`
- `pnpm check:boundaries`
- `pnpm build`（Vite 产物生成成功）

新增 `frontend/app/styles.test.ts` 覆盖离线 CSS、light/dark token、单一页面动效、reduced-motion、focus-visible、44px 命中区域及高频 range 无过渡契约。

## 限制与后续入口

- 本任务未进行真实摄像头和 O6 PCAN 实机测试；硬件正式版门槛仍由集成/RC 阶段完成。
- 视觉 Worker 的运行时背压、曲线不可见时停止绘制等行为保持现有实现，未在本模块重复实现。
- 下一入口：集成智能体将本分支提交 cherry-pick 到 `codex/v2-rewrite`，随后由 browser/verification 任务在 1366×768 下检查实际页面切换、主题切换、焦点和拖动帧预算。
