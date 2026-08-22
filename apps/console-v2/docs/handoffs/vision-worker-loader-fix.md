# Vision Worker MediaPipe Loader 修复交接

- 分支：`codex/v2-m5-vision-worker-loader-fix`
- 基线：`9180d68f05cdd0f46198d0c4e520401636b4f290`
- 修改范围：Vite Worker 输出格式、VisionRuntime Worker 装配、构建契约
- 公共领域契约：未变化

## 根因与方案

MediaPipe Tasks 1.0.1 的官方 Emscripten loader 通过 `importScripts()` 执行脚本级 `var ModuleFactory`。module worker 中 `importScripts` 不可用，库回退到动态 `import()`；动态导入不会把该脚本变量暴露到 `self`，随后触发 `ModuleFactory not set.`。

V2 现在使用 Vite `worker.format: 'iife'` 输出独立 classic worker chunk，`VisionRuntime` 创建 Worker 时不再传递 `{ type: 'module' }`。classic worker 保留 `importScripts()`，官方 loader 可以在 Worker 全局建立 `ModuleFactory`。未使用 eval 或 CSP 放宽；现有 `worker-src 'self' blob:` 和离线资源保持不变。

## 不变量

- `vision-worker` 仍是独立 chunk，且必须是 classic IIFE。
- MediaPipe loader 只能从随包分发的 `/vision/wasm` 资源加载；不依赖网络 CDN。
- 单帧背压、Vision/RPS 共享 VisionRuntime、Tauri CSP 和 Worker 协议均未改变。

## 构建契约

`pnpm check:vision-worker` 检查 Vite classic IIFE 配置、Runtime 未创建 module worker、产物存在且包含 `importScripts` 和 MediaPipe `ModuleFactory` guard。该检查已接入 `pnpm build`。

## 验证

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test`（19 files / 104 tests）
- `pnpm check:contracts`
- `pnpm check:vision-assets`
- `pnpm check:vision-worker`
- `pnpm check:boundaries`
- `pnpm build`

## 后续入口

集成后必须由浏览器 QA 点击“开始预览”，确认 WASM loader 成功、模型初始化完成并进入摄像头权限阶段；本交接不将静态构建通过等同于真实 Worker 初始化通过。
