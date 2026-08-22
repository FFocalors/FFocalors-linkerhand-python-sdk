# Console V2 UI Shell handoff

- 分支：`codex/v2-m1-ui-shell`
- 提交：`f5aefd6`（feat(console-v2): add operator UI shell and mock runtime）
- 范围：React + TypeScript + Vite 的普通操作员工作台，包含设备控制、智能抓取、视觉模仿、猜拳互动、动作中心、诊断中心、设置。
- 模块：`frontend/app` 负责壳与路由状态；`frontend/features/{device-control,smart-grasp,vision,rock-paper-scissors,actions,diagnostics,settings}` 仅通过各自 `index.tsx` 公开；`frontend/shared/{ui,theme,contracts,utilities}` 提供 UI、主题、契约和合帧工具；`frontend/workers/vision-worker` 保留视觉 Worker 边界。
- 公共接口：`shared/contracts` 对齐 DeviceConfig、DeviceCapabilities、ConnectionSnapshot、JointTargetCommand、TelemetrySnapshot、OperationSnapshot、StructuredLogEntry、AppError、ActionRecording、VisionPoseProposal，并提供 Device/Motion/Telemetry/Action/Grasp/Vision/Log ports。当前实现由可替换的 `mockRuntime` 提供数据。
- 交互：关节滑块以局部状态响应，`requestAnimationFrame` 合帧提交；拖动期间遥测不覆盖；pointerup / Enter 提交最终值。主题有约 180ms 颜色过渡，页面有短 opacity/transform 动效并尊重 reduced motion。停止全部动作会进入锁定态；该动作不是物理断电急停，恢复需点击“恢复控制”。
- 视觉权限：视觉模仿与猜拳共享 VisionPort；只有 O6 可同步动作，其他型号可预览并明确禁用。
- 验证：`pnpm typecheck`、`pnpm lint`、`pnpm test`（4/4）、`pnpm build` 均通过；模块级 `.gitignore` 已覆盖依赖、dist、coverage、Vite/TS 缓存。ESLint `no-restricted-imports` 对 `frontend/features/**` 的 `../../features/*` 导入执行 boundary 检查，临时跨 feature 导入探针确认会失败。
- 视觉验收（2026-08-23，真实 Chrome）：在 `1366×768` 检查七页导航、浅/深主题、操作员层级、滚动和锁定提示；设备控制/视觉模仿/猜拳/动作/诊断/设置均在首屏完整，智能抓取仅需约 83px 页面滚动到底部触觉矩阵。在 `1600×900` 复验七页，智能抓取仅约 10px 溢出，其余页面无溢出；视觉模仿和猜拳均无 3D 空白区，使用共享视觉输入占位与动作建议。停止全部动作后锁定横幅、顶部恢复按钮和 6 个禁用滑块均可见，恢复后滑块恢复可用。
- 交互验收：真实拖动 J1 连续移动后最终显示 53°，等待约 2.2s 遥测仍保持 53°；键盘 ArrowRight 后值从 53° 到 54°且焦点 outline 为 solid 2.4px。页面切换到视觉模仿后设备滑块节点降为 0，确认隐藏页不继续绘制；各页交互只更新所在页面状态。
- 未解决项：真实 Tauri/Rust、Python sidecar、摄像头输入与硬件连接未接入，留在 ports/worker 边界之外。
- 下个智能体入口：从 `frontend/shared/contracts` 注入真实 ports；保持 feature 只从 public index 导出，补充真实视觉 Worker 和 E2E。
