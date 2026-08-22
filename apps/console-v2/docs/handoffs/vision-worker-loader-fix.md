# Vision Worker MediaPipe Loader 修复交接

- 分支：`codex/v2-m5-vision-worker-loader-fix`
- 基线：`9180d68f05cdd0f46198d0c4e520401636b4f290`；开发构造器追加修复基线：`574030049a1cac2f66cd528aad1f19238eee868d`
- 修改范围：Vite Worker 输出格式、VisionRuntime Worker 装配、开发 classic loader、离线 MediaPipe bundle、构建契约
- 公共领域契约：未变化

## 根因与方案

MediaPipe Tasks 1.0.1 的官方 Emscripten loader 通过 `importScripts()` 执行脚本级 `var ModuleFactory`。module worker 中 `importScripts` 不可用，库回退到动态 `import()`；动态导入不会把该脚本变量暴露到 `self`，随后触发 `ModuleFactory not set.`。

V2 现在使用 Vite `worker.format: 'iife'` 输出独立 classic worker chunk，`VisionRuntime` 创建 Worker 时不再传递 `{ type: 'module' }`。classic worker 保留 `importScripts()`，官方 loader 可以在 Worker 全局建立 `ModuleFactory`。未使用 eval 或 CSP 放宽；现有 `worker-src 'self' blob:` 和离线资源保持不变。

## 不变量

- `vision-worker` 仍是独立 chunk，且必须是 classic IIFE。
- MediaPipe loader 只能从随包分发的 `/vision/wasm` 资源加载；不依赖网络 CDN。
- 单帧背压、Vision/RPS 共享 VisionRuntime、Tauri CSP 和 Worker 协议均未改变。

## 构建契约

`pnpm check:vision-worker` 检查 Vite classic IIFE 配置、Runtime 使用 Vite `?worker` 构造器且未绕过转换、产物存在且包含 `importScripts` 和 MediaPipe `ModuleFactory` guard。该检查已接入 `pnpm build`。

## 开发环境追加修复

浏览器 QA 发现直接使用 `new Worker(new URL(...))` 时，Vite dev 会把包含 ESM import 的 TypeScript 源文件交给 classic worker，产生 `Cannot use import statement outside a module`。现在由 `app/composition.ts` 使用 Vite `?worker` 构造器并注入 `VisionRuntime`；共享 Runtime 不反向依赖 workers。`worker.format: 'iife'` 保证生产产物仍为 classic loader 兼容格式。未修改公共领域契约、Worker 协议、CSP 或离线资产路径。

由于 Vite dev 默认将 `?worker` wrapper 标为 module worker，装配路径使用显式 `?worker&classic` 标记，并由 Vite 配置插件将该 wrapper 和 `worker_file` 请求改为 classic。Worker 不再运行时导入 ESM `@mediapipe/tasks-vision`，而是通过 `importScripts` 加载随包的官方 `vision_bundle.js` UMD 资产；构建将该资产写入 `dist/vision/vision_bundle.js`，开发服务器提供相同本地路径。这样 dev 和 production 均实际创建 classic Worker，官方 Emscripten `ModuleFactory` 路径保持可用，未使用 eval 或 CSP 放宽。

Vite 对带有 `import type` 的 dev worker 源会在末尾注入空 `export {};`。该语句对 classic worker 非法，因此插件仅在精确的 `/workers/vision-worker/index.ts?worker_file&type=classic` 响应上移除末尾空导出，不处理其他文件或任意 export。浏览器验证该响应无 `import`/`export`，构建契约同时检查精确路径和变换规则。

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
