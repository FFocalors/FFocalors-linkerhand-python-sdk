# StrictMode 生命周期与视觉错误处理交接

- 分支：`codex/v2-m5-strictmode-fix`
- 基线：`6a55be51b50fc439effa576d7e8fb5d0748f2375`
- 修改范围：App 生命周期、Vision/RPS 页面异步错误处理、StrictMode 回归测试
- 公共契约：未变化

## 不变量

- React effect cleanup 只执行幂等 `stop()`，不会在 StrictMode replay 中永久释放共享 `VisionRuntime`。
- `pagehide`/`beforeunload` 是应用终止边界，才调用 `VisionRuntime.dispose()`；监听器在 effect cleanup 中成对移除。
- Vision/RPS 页面离开时立即停止会话，永久 dispose 延迟到当前 effect replay 窗口结束；重新 setup 会取消延迟释放并复用同一控制器。
- Vision 与 RPS 的启动、停止、授权和动作测试错误都会被捕获，页面通过 `role="alert"` 呈现可恢复提示。

## 验证

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test`（18 files / 101 tests）
- `pnpm check:contracts`
- `pnpm check:vision-assets`
- `pnpm check:boundaries`
- `pnpm build`（包含离线 Vision Worker chunk）

## 后续入口

集成 agent 将本分支 fast-forward 到 `codex/v2-rewrite`，然后重新执行最终浏览器 QA；无需重建 NSIS，正式安装包在后续打包刷新。
