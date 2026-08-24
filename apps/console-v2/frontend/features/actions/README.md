# 动作中心

动作中心使用两个明确的数据概念：`PosePreset` 是一个静止关键帧，`ProgrammedAction` 是按顺序引用多个姿态并带有播放配置的动作。

- “＋新建动作”直接进入姿态编排器。候选只包含 4 个基础预设、5 个数字预设、首页自定义姿态和动作中心本地自定义姿态。
- 编排器支持按选择顺序选择、重排、移除和清空，并在保存前设置动作的单次/循环、倍速、正放/倒放和循环次数。
- 首页姿态在动作中心只读；动作中心通过 `localPresets`/`onLocalPresetsChange` 维护本地姿态，不回写首页。
- `programmedActions`/`onProgrammedActionsChange` 可由集成层控制，未提供时使用 feature-local 会话状态。
- 旧 `ActionRecording` 只显示在独立“录制兼容区”，不混入全部姿态或编排候选。
- 姿态编辑器在调试模式开放 6 个关节滑块；草稿与遥测当前位置分离，支持读取当前位置、重置草稿、预览和保存为动作中心自定义姿态。`onVirtualPoseChange` 可将未保存草稿同步给虚拟机械手。
- 物理设备通过 `isPhysicalDevice` 开启预览/应用门槛：选择姿态只生成预览，只有明确点击“应用到设备”才调用 `applyPose`（缺少该方法时回退到 `playPose`）。
- 编排倍速固定为 `0.25×/0.5×/0.75×/1×`，运行和持久化都会将旧数据速度归一化到该范围。

## ActionController 集成清单

`ActionController` 优先使用完整目标接口：

```ts
playPose(pose: PosePreset, options: PlaybackOptions): Promise<void>
playProgrammedAction(action: ProgrammedAction, options: PlaybackOptions): Promise<void>
```

其中 `ProgrammedAction` 携带 `poseIds`、完整 `poses` 快照和 `playback` 配置；运行时不需要猜测内置/local ID。旧 `play(id, { speed, loopCount, direction? })` 仅作为兼容降级路径，新集成应实现上述两个方法。

建议后续将这两个 feature-local DTO 固化到共享契约，并让播放状态事件增加 `sequenceId`、`itemIndex`、`direction`，以便准确显示序列进度。
