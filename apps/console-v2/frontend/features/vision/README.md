# Vision Mimic feature

视觉模仿只消费注入的 `VisionRuntimeLike`，不会创建摄像头、Worker 或第二个 runtime。页面卸载、停止预览和 runtime owner 为 `vision` 时，会释放该 feature 持有的 runtime；如果 owner 属于猜拳 feature，则不会误停它。

## 公开入口

```tsx
<VisionMimic
  capabilities={capabilities}
  locked={locked}
  runtime={sharedVisionRuntime}
  proposalController={{
    submit: proposal => featureLocalQueue.submit(proposal),
    revoke: reason => featureLocalQueue.revoke(reason),
  }}
/>
```

`proposalController` 是 feature 与上层 motion/app facade 之间的注入边界。此目录不导入 `device-control`、不导入 Tauri，也不调用 `VisionPort.sync`。没有 runtime 时页面保持预览/配置说明，不会自行补建 runtime。

`VisionFeatureController`、`canSubmitProposal`、`SessionCalibration`、`GestureStabilizer`、`PoseMapper`、`mapLandmarksToO6` 和固定的 `OPEN_HAND_LANDMARK_FIXTURE` / `FIST_HAND_LANDMARK_FIXTURE` 从本入口导出，便于上层集成和独立测试。

## 安全门控与映射

- 默认未授权；只有 O6、明确允许同步、张开/握拳会话校准完成、稳定置信度至少 0.70、runtime 为 `running` 且 owner 为 `vision`、未锁定时才提交 `VisionPoseProposal`。
- O6 以外仍可预览和识别，但同步控件禁用并解释原因。
- proposal 始终是完整六维 `0..1` 向量。映射后的输出通过高级抽屉配置 EMA、死区和单帧最大变化率；默认值是 `deadZone=0.025`、`emaAlpha=0.35`、`maxDeltaPerFrame=0.12`。
- 校准只保存在 `SessionCalibration` 实例内，不读写或迁移旧数据。

视觉运行、FPS、丢帧、错误和摄像头恢复按钮均读取共享 runtime/controller 状态，没有定时伪进度或伪识别结果。
