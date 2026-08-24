# 猜拳互动 Feature

本模块只消费应用层注入的唯一 `VisionRuntime`，并以 `owner = 'rps'` 启动它；这里没有 `new VisionRuntime`、Worker 或 MediaPipe 加载逻辑。与视觉模仿 Feature 的共享边界只有 `frontend/shared/vision-runtime`。

## 集成契约

`RockPaperScissors` 接收：

- `runtime: RpsVisionRuntime`：应用创建的单例 runtime，提供 `start(video, 'rps')`、`stop`、`subscribe`、`onResult` 和 `snapshot`。
- `capabilities` 与 `locked`：O6 才显示动作授权；非 O6 只识别、显示比分，绝不下发动作。
- `actionController?: RpsActionController`：可选的 feature-local 动作控制器。它必须先由操作员显式 `authorize()`，揭晓后通过 Promise 的 `dispatch` 结果更新动作状态；`locked`、停止、重置和卸载都会 `cancel`。
- O6 且动作控制器已接线时，授权后会显示石头/布/剪刀“动作测试”；这些按钮仍经过同一个 controller，不绕过 motion 仲裁。非 O6、未授权、锁定或未接线时全部禁用或不显示。
- `scheduler` 与 `random`：可注入测试时钟和 RNG；默认实现只用于真实页面。

状态流为 `idle → cameraReady → countdown(3/2/1) → capture → recognized/invalid → reveal → score → ready`。`classifier.ts` 仅接收 runtime 的 21 点中性结果，使用连续稳定帧窗口（默认 3 帧）和置信度门槛；无手、多手、低置信度、模糊和不明确手势均不会出拳。

页面卸载时 controller 会解除结果订阅、清理倒计时、撤销动作并调用 runtime `stop()`，由 runtime 负责停止 tracks、Worker 和释放 `rps` owner。runtime 自己的 visibility 监听会在页面隐藏时 stop。
runtime 从 `running` 离开（hidden、device-lost、worker/error 或外部 stop）时，controller 会清理 capture/countdown timers、稳定帧和本局授权，并回到带错误信息的 idle；只有 runtime snapshot 的 owner 为 `rps` 时 feature 才会调用 `stop()`。

## 操作员流程

1. 开启摄像头并确认预览状态为“摄像头已就绪”。
2. O6 点击“授权本局机械手”；非 O6 直接点击“开始一局”。授权只覆盖当前一局。
3. 倒计时结束后保持石头、布或剪刀约三帧；识别不稳定会提示重试，不会伪造动作成功。
4. 揭晓与记分后可重试；“停止摄像头”、全局锁定或离开页面都会撤销未完成动作。

## 摄像头与调试模式

- 摄像头初始默认值来自 `preferredCameraDeviceId` prop（应用壳从设置页同步），用户可独立选择其他摄像头。
- 摄像头启动失败（含权限被拒）会给出恢复指引：允许本应用访问摄像头后重试，或在系统/浏览器设置中开启权限。
- 调试模式：`isPhysicalDevice` 为假（未连接真实手）时，本局的机械手动作下发禁用，并显示「调试模式」提示；识别与比分仍可正常进行。动作授权只有连接真实手或调试虚拟手场景下才有意义。
