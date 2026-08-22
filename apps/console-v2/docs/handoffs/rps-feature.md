# RPS Feature handoff

## 本分支交付

分支 `codex/v2-m4-rps-feature` 从 `6f614a7866eb1133c9be7b081cbed3b872e6962a` 创建，所有实现限于 `frontend/features/rock-paper-scissors/**` 与本 handoff。RPS 包含：

- `RpsGameController`：`idle → cameraReady → countdown → capture → recognized/invalid → reveal → score → ready`，倒计时、捕获窗、揭晓和记分均走可注入 scheduler。
- `classifier.ts`：基于 runtime 的 21 landmarks，连续 3 稳定帧、手部置信度和手势置信度门槛；无手、多手、低置信度、模糊和不明确结果不会伪造出拳。
- `game.ts`：注入 RNG 的 AI 出拳、纯函数胜负和比分。
- `RpsActionController`：只在 O6 + `setPosition` + 明确本局 `authorize()` 后 dispatch；非 O6 是识别预览；O6 接线后额外提供三种动作测试按钮，仍走同一个 controller；锁定、停止、重置、卸载都会 cancel。
- React 页面含摄像头预览、中文操作状态、倒计时、结果、比分、重试/重置；组件不创建 VisionRuntime、Worker 或摄像头。

## 应用集成门槛

基线 `apps/console-v2/frontend/app/App.tsx` 仍将 RPS 当作旧的 `{ vision, capabilities, locked }` 页面，且没有注入 `RpsVisionRuntime`。集成时必须由 App/应用 facade 创建一份共享 runtime，并传入 `runtime={sharedVisionRuntime}`；不能在 RPS 或 Vision Feature 中各自 `new VisionRuntime`。O6 动作侧传入实现 `RpsActionController` 的 controller；其他型号可省略该 prop。

页面组件卸载会调用 runtime `stop()`，runtime 自己处理 hidden visibility、tracks、Worker 与 owner 释放。全局 stop/lock 应由 App 同时传入 `locked`，使 feature 立即 cancel。
controller 用 generation token 使迟到的 start/authorize/dispatch Promise 失效，并保证最多一个 dispatch in-flight。runtime 从 running 离开时会清理本局 timers/stable window/授权；busy 的 vision owner 在 RPS 中始终显示为 idle + `VISION_BUSY`，不会误显示运行中的摄像头。全局 lock/stop 会在 owner 为 `rps` 时有界异步 stop runtime，owner 为 vision 时绝不误停。reset 在摄像头仍 running 时回到 `cameraReady` 并清零比分。

## 验证记录

在本 worktree 安装了 `pnpm-lock.yaml` 对应依赖。controller/classifier/game/UI tests 覆盖 fake countdown、recognized/invalid 全链路、稳定帧、单次记分、runtime busy/permission/device-lost、owner 隔离、异步取消竞态、reset/retry/卸载和动作门控。`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm check:vision-assets`、`pnpm build` 应从 `apps/console-v2` 执行；入口尚未注入 runtime，因此若 worker chunk 仍被 tree-shake，只能记录为集成门槛，不能宣称端到端 camera/runtime 集成通过。集成后应额外确认生产 dist 含本地 `vision-worker` chunk/`/vision` 资源且没有 CDN URL。
