# Vision 资源路径修复交接

- 分支：`codex/v2-m5-vision-assets-fix`
- 基线：`d6d79631d6a488fbd573f59ef0dd36a9a2a141d6`
- 修改范围：Vision 资源 URL 解析、WASM 根路径装配、设置页离线资源自检、协议与运行时测试
- 公共领域契约：未变化；`VisionWorkerRequest` 字段和错误码均未改变

## 修复不变量

- 资源 URL 相对于 `import.meta.env.BASE_URL` 和当前应用 `document.baseURI` 解析，覆盖 Vite dev、非根 production base 以及 Tauri webview。
- `FilesetResolver.forVisionTasks` 会自行拼接文件名，因此传入的 `wasmRootUrl` 始终去除尾斜杠，避免生成 `wasm//vision_wasm...`。
- 设置页离线自检复用同一 `visionAssetUrl`，检查地址与运行时加载地址不会分叉。
- 未修改公共领域协议；协议测试仅将 fixture 根路径改为实际要求的无尾斜杠形式。

## 验证

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test`（19 files / 104 tests）
- `pnpm check:contracts`
- `pnpm check:vision-assets`
- `pnpm check:boundaries`
- `pnpm build`（包含 `vision-worker` chunk）

## 后续入口

集成 agent 将本分支快进到 `codex/v2-rewrite`；浏览器 QA 需再次点击“开始预览”确认 WASM 请求为单斜杠路径，并在 Tauri/production base 下检查同一资源地址。
