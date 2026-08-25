# 动作中心

动作中心使用两个明确的数据概念：`PosePreset` 是一个静止关键帧，`ProgrammedAction` 是按顺序引用多个姿态并带有播放配置的动作。

- 页面采用左右双栏：左侧先管理姿态和姿态编辑器，右侧再编辑动作。点击“＋新建动作”后，在左侧勾选姿态并点击“添加到动作”转移到右侧序列。
- 姿态库保留全部、内置、自定义筛选，内置姿态仍区分基础预设和数字预设；首页自定义姿态只读，动作中心本地姿态可保存和删除。
- 动作编辑器支持按顺序重排、移除和清空，并在保存前设置动作的单次/循环、倍速（最高 1×）、正放/倒放和循环次数。
- 首页姿态在动作中心只读；动作中心通过 `localPresets`/`onLocalPresetsChange` 维护本地姿态，不回写首页。
- `programmedActions`/`onProgrammedActionsChange` 可由集成层控制，未提供时使用 feature-local 会话状态。
- 旧 `ActionRecording` 类型和 `ActionController` 录制方法仍保留用于共享运行时兼容，但页面不再展示录制兼容区或录制入口。
- 姿态编辑器在调试模式开放 6 个关节滑块；草稿与遥测当前位置分离，支持读取当前位置、重置草稿、预览和“保存到自定义姿态”。`onVirtualPoseChange` 可将未保存草稿同步给虚拟机械手。
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
