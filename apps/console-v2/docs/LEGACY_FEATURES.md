# 旧版 PyQt 功能基线（V2 迁移参考）

> 文档性质：迁移基线，不是用户手册，也不是硬件验收报告。
>
> 依据：本文件逐项阅读并对照当前 V2 树中已提交的 `example/gui_control` 源码、相关测试和资源；旧版另一个 worktree 的 dirty 状态不作为证据。另一个旧版 dirty worktree 中可能存在的性能/线程改动不纳入本基线；若后续决定迁移，必须单独进行 delta 审计。这里记录的是代码入口、状态、配置和迁移约束，不把“有实现”写成“已经在真实设备上验证”。

## 0. 范围、证据和阅读方式

旧版窗口由 `example/gui_control/main.py` 启动，`main_window.py` 组装 `ApiManager`、`DataSource`、`Recorder`、`ActionExecutor` 和页面栈。导航项来自 `lhgui/widgets/sidebar.py`：控制台、视觉识别、小游戏、日志、设置；演示模式从顶部栏进入，但不是侧边栏常规项。`Page.WAVEFORM` 和 `RecorderPage`/`PresetPanel` 等兼容或旧组件仍在代码树中，但当前 `MainWindow` 没有把它们放进页面栈。

本基线使用以下证据等级：

- **代码依据**：从源码可直接确认的入口、分支、常量或数据结构。
- **单测依据**：`example/gui_control/tests` 或旧版纯逻辑脚本明确覆盖的逻辑；不等于 UI 或硬件验收。
- **未验证**：需要摄像头、MediaPipe 模型、CAN/设备、PyQt 运行环境或完整端到端操作才能确定的结果，本文件明确保留为未验证。

主要核验来源：

- 主窗口与页面：`example/gui_control/main_window.py`、`example/gui_control/lhgui/pages/`。
- 控件与入口：`example/gui_control/lhgui/widgets/`、`example/gui_control/lhgui/styles/`。
- 硬件和状态：`example/gui_control/lhgui/core/api_manager.py`、`data_source.py`、`action_executor.py`、`joint_state_cache.py`、`signal_bus.py`、`ui_state.py`。
- 抓取/视觉/猜拳：`adaptive_grasp_controller.py`、`grasp_profile.py`、`grasp_calibration.py`、`grasp_state.py`、`joint_signal_analyzer.py`、`pages/vision_page.py`、`pages/game_page.py`。
- 测试：`example/gui_control/tests/test_adaptive_grasp_controller.py`、`test_joint_signal_analyzer.py`、`example/gui_control/test_preset_features.py`、`test_pure_logic.py`。

## 1. 入口与总览

| 能力 | 用户入口 | 旧版实际组合 | V2 迁移要求 |
| --- | --- | --- | --- |
| 设备和关节控制 | 启动后“控制台” | `ConsolePage` + `JointPanel` + `ApiManager` | 保留设备配置、连接状态、位置/速度/扭矩边界；硬件调用只能经过 V2 device adapter/sidecar，不复刻全局 PyQt signal bus。 |
| 快捷动作和循环 | 控制台右侧“快捷动作”、底部“开始循环” | 内置 `HAND_CONFIGS` 动作 + `ActionExecutor` + `_CycleController` | 统一 action DTO、生命周期、互斥和 stop/unlock 语义；区分 UI 选择和实际下发。 |
| 自定义预设 | 快捷动作中的“添加”卡片；抓取成功后的“定制并锁定” | YAML `CustomPresetStore` | 保留按型号隔离、当前反馈补位、0–255 校验、原子写入/损坏备份；迁移存储版本和错误提示。 |
| 实时曲线/触觉 | 控制台左下可见实时曲线；触觉矩阵当前无用户可见入口 | 已挂载 `WaveformPanel`；`MatrixPanel` 仅为未挂载组件，`DataSource`/`ApiManager` 保留采集信号和读取代码 | 保留 telemetry 采样、目标虚线、抓取事件标记；触觉能力需重新接入诊断入口并做 capability gating，不要声称当前页面正在显示矩阵或所有型号都有 3D/触觉。 |
| 录制回放 | 当前页面主入口是视觉页“录制与回放”；旧 `RecorderPage` 未挂载 | 两套录制实现：通用 `Recorder` 与 Vision O6 JSON 录制 | 明确“通用动作录制”和“视觉 pose 录制”的格式、互斥、停止/暂停/循环和安全步长。 |
| 视觉模仿 | 侧边栏“视觉识别” | MediaPipe 摄像头线程 + O6 6D 映射 | 迁移离线资源/Worker、权限失败、校准、输出开关、回放互斥和 O6 限制。 |
| 猜拳 | 侧边栏“小游戏” | MediaPipe 分类 + RPS 状态机 + O6 出拳 | 迁移摄像头、稳定帧、机器先锁拳、公平性和策略 profile。 |
| 日志/设置/演示 | 顶栏与侧边栏 | `TopBar`、`LogPage`、`SettingsPage`、`DemoPage` | 保留结构化事件、主题/演示门槛、设置占位和响应式规则；不要将命令 trace 当成硬件成功证明。 |

## 2. 设备连接、型号与通信

### 用户入口和流程

1. `MainWindow` 创建 `ApiManager`、`DataSource`，随后自动调用 `api_manager.connect()` 并启动轮询线程。
2. `ApiManager` 读取 SDK 的 `setting.yaml`。左手 `EXISTS` 优先于右手；选出 `hand_type`、`JOINT`、`TOUCH`、`CAN`、`MODBUS`。
3. 构造 `LinkerHandApi(hand_joint, hand_type, modbus, can)`，尝试初始化全部关节的速度和扭矩为 255，再读取固件版本和序列号作为在线可达性检查。
4. 成功发出 `connection_changed("connected")` 和 `hand_info_ready`；失败回收 API/CAN 资源，发出 `offline`，建立虚拟姿态并允许离线调试。
5. 顶栏显示手型、固件、连接徽章；“重新连接”先 dispose 旧实例再连接。`ConnectionBar` 仍存在，但当前主窗口使用的是 `TopBar`。

### 型号和通信事实

`lhgui/config/constants.py` 当前含 `L25`、`L21`、`L20`、`G20`、`L10`、`L7`、`O6`、`L6` 配置；部分历史型号定义以注释保留。每个 `HandConfig` 给出关节名称、初始位置和可选内置预设，关节数量从 6 到 25 不等。O6/L6 为 6 维；视觉模仿和猜拳的 pose 常量只面向 O6。

`ApiManager` 的下发路径是 `signal_bus.finger_move_requested` → `finger_move()` → `sanitize_finger_pose()` → `LinkerHandApi.finger_move()`。无效长度/非有限值/越界值会被拒绝或裁剪并记录命令 trace；离线模式只更新虚拟姿态并向 UI 广播，不触碰真实硬件。状态读取提供 `get_state/current/speed/matrix_touch`，连续读取失败达到阈值会转为断开。

### 关键状态/配置

- `ConnectionState`: `DISCONNECTED`、`CONNECTING`、`CONNECTED`、`OFFLINE`、`ERROR`。
- `ApiManager.hand_joint`、`hand_type`、`is_touch`、`can`、`modbus` 来自 `setting.yaml`；版本和序列号来自底层 API。
- `DataSource` 的代码在 QThread 中以默认 20 Hz 读 state/current/speed，并具备以 2 Hz 调用 `get_matrix_touch()`、发出 `matrix_updated` 信号的采集路径；但当前 `MainWindow`/`ConsolePage` 没有实例化 `MatrixPanel`，当前唯一对 `matrix_updated` 的 UI 订阅位于未挂载的 `MatrixPanel`，因此当前页面没有有效订阅/展示，不能描述为当前页面正在 2 Hz 更新触觉矩阵。未连接或未声明 `TOUCH` 时不发对应采集数据。
- `joint_state_cache` 保存带时间戳的反馈；自定义多关节预设要求缓存不超过 5 秒。

### 代码依据和 V2 迁移要求

依据：`main_window.py`、`core/api_manager.py`、`core/data_source.py`、`config/constants.py`、`utils/signal_bus.py`、`utils/ui_state.py`、`core/joint_state_cache.py`。

V2 必须保留“配置选择 → 连接探测 → 能力/版本信息 → telemetry”的顺序，明确真实、fake、offline 三种来源；不能把离线虚拟姿态、fake adapter 或静态构建写成真实设备在线。必须把 stop、断连、重连、错误映射和设备生命周期放在既有 V2 runtime/sidecar 边界内。

## 3. 关节控制、速度和扭矩

### 入口和流程

控制台 `JointPanel` 为每个配置关节创建 `JointRow`：水平滑块和 0–255 数值框双向同步；反馈值以独立样式显示。用户修改值后 `values_changed` 更新 3D 姿态预览，并通过已有的 preset/action 下发链路执行。底部 `BottomBar` 提供“速度”和“扭矩”弹窗，均为单个值扩展为当前关节数数组后发 `speed_set_requested`/`torque_set_requested`；“恢复初始”发 `home_requested`；“紧急停止”发 `playback_stopped` 并写 warning。

`ActionExecutor` 仅在 `ui_state.connection == CONNECTED` 时执行动作；离线模式的直接 `finger_move` 支持调试，但离散动作执行器会以“设备未连接”拒绝。动作开始将 `ActionState` 置为 `ACTION_RUNNING`，约 300 ms 后回到 idle；循环使用 `CYCLE_RUNNING`。

### 关键状态/限制

- 位置范围由 `sanitize_finger_pose` 和 `JointRow` 的 0–255 控件共同约束。
- 速度/扭矩是按所有关节复制的单一标量 UI；旧版没有在 `BottomBar` 暴露逐关节速度/扭矩编辑。
- 自适应抓取会备份/临时降低扭矩，结束或释放时调用 `restore_saved_torque()`。
- 紧急停止信号在旧版主要是软件状态广播和停止播放/抓取；代码没有证明物理断电或硬件急停。

依据：`widgets/joint_panel.py`、`joint_row.py`、`bottom_bar.py`、`core/action_executor.py`、`core/api_manager.py`、`utils/signal_bus.py`。

V2 迁移时要将“位置写入、速度设置、扭矩设置、home、stop”统一接入 motion/action runtime，定义每种命令的确认/错误状态；保留 0–255 和关节数量校验，避免把软件 stop 说成物理急停。

## 4. 内置预设、自定义预设和循环

### 内置动作

控制台 `PresetGroup` 按当前型号读 `HAND_CONFIGS[hand_joint].preset_actions`，分为核心动作、数字手势和其他动作；点击发 `preset_triggered(name, positions)`。演示页按 `张开`、`握拳`、`OK`、`点赞` 优先展示最多 12 个动作，但进入演示模式的前提是已连接设备，并且页面文字明确会真实下发。

型号差异必须保留：O6/L6 的常见动作包括张开、壹到伍、OK、点赞、握拳；L7/L10/L20/G20 等拥有不同数量和命名，L25 有 25 维基础动作，L21 只有初始位置而没有当前内置动作表。确切 pose 以 `constants.py` 为准，不应在 V2 文档或 UI 中硬编码成所有型号通用。

### 自定义预设

入口是 `PresetGroup` 的“添加”卡片，或自适应抓取成功后的 `AdaptiveGraspCard → 定制并锁定`。编辑器允许“使用当前姿态”，但要求反馈新鲜且完整；保存时校验名称非空、无控制字符、不超过 16 字符、同型号内不与内置/自定义重名，数值必须在 0–255。`CustomPresetStore` 使用用户配置目录下的 `custom_presets.yaml`，结构为 `version: 1`、`models: {hand_model: [...]}`，每项含 UUID、名称、类别、型号、values、创建时间和可编辑关节索引。写入为临时文件替换；损坏 YAML 会备份为 `.corrupt-<timestamp>` 后从空结构启动。

执行自定义预设时，`ActionExecutor` 校验预设型号等于当前硬件型号。对超过 6 维型号，前 6 个编辑值覆盖当前姿态，其余隐藏关节必须来自不超过 5 秒的实时反馈；反馈过期或不存在时拒绝执行，避免误动隐藏轴。

### 循环

当前 `ConsolePage` 使用内部 `_CycleController`，按 `HAND_CONFIGS` 的动作字典每秒发下一项，末尾回到第一项；开始时清零索引、设 `CYCLE_RUNNING`，停止时停止 QTimer、回到 idle 并写“已停止循环”。另有未挂载的 `widgets/cycle_control.py` 和旧 `PresetPanel`，它们也实现按秒循环；V2 不应复制两套循环 owner。

依据：`widgets/preset_group.py`、`preset_editor_dialog.py`、`core/custom_preset_store.py`、`core/action_executor.py`、`pages/console_page.py`、`widgets/cycle_control.py`、`widgets/preset_panel.py`、`pages/demo_page.py`、`config/constants.py`。

V2 迁移要求：内置动作和用户动作使用同一 action schema 但标识来源；保留按型号和反馈补位安全条件；循环需要可取消、可观察、与其他写入互斥，并在持久化升级时保留损坏文件恢复策略。

## 5. 动作录制与回放

### 通用录制（当前主窗口未挂载的旧路径）

`core/recorder.py` 监听所有 `finger_move_requested`。`start_recording(joint_len)` 开始采样，`stop_and_save(name)` 将姿态帧写入 `recordings` 目录；`play(name, speed)` 使用 QTimer 按帧间隔重发，倍速下限 0.1，录制和回放互斥，支持停止。`RecorderPage`/`RecorderAdapter` 提供保存记录列表、删除、倍速播放和进度，但 `MainWindow` 当前页面栈没有 `RecorderPage`，`Page` 只保留兼容状态枚举。

### 视觉页录制/回放（当前可见入口）

视觉页把 O6 pose 录为 JSON 类型 `linkerhand_gesture_recording`。开始录制前需要先启动摄像头/模仿；按 `RECORD_INTERVAL=0.12s`、姿态变化阈值 3 或 keepalive 0.60 s 采帧，最短 0.30 s、最多 60 s、至少 3 帧。保存/加载通过文件选择器；加载会丢弃无效、非单调时间帧，至少需要 2 个有效回放帧。

点击开始回放会停止录制；有硬件输出时先确认“暂停实时下发”，再确认设备上电/CAN/连接状态。回放开始关闭实时下发开关，设置 `live_emit_blocked_by_playback`；可暂停/继续、停止、循环和选择 0.5x/1.0x/1.5x/2.0x。每个目标 pose 以 `MAX_REPLAY_STEP=30`（拇指横摆另有 20 的步长限制）分段发送，按记录时间和倍速调度；回放完成恢复 idle。

依据：`core/recorder.py`、`core/recorder_adapter.py`、`pages/recorder_page.py`、`pages/vision_page.py`（录制常量、payload、`_start_recording`、`_load_recording_from_path`、`_playback_tick`）。

V2 迁移要求：明确通用 action 记录和视觉 pose 记录不是同一格式；把写锁、实时流屏障、回放分段限速、损坏/不足帧错误和文件版本作为可测试 contract。旧版没有证明跨版本文件兼容或真实硬件回放安全，应单独验收。

## 6. 关节曲线、触觉矩阵和机械手模型

### 曲线与矩阵

`WaveformPanel` 在控制台左下显示最近 200 个采样点，状态实线和最近目标虚线分别绘制；可按关节切换、折叠和全屏。它监听 `waveform_updated`，同时监听抓取曲线事件，用三角/星号/方块/叉号标记候选接触、确认接触、到达限位和中止。抓取回到 idle 时清除标记。

`MatrixPanel` 为拇指、食指、中指、无名指、小指各绘制 12×6 点阵，但它只是旧组件代码：当前 `MainWindow`/`ConsolePage` 没有实例化它，侧边栏和控制台也没有触觉矩阵入口；当前唯一对 `matrix_updated` 的 UI 订阅位于未挂载的 `MatrixPanel`，因此当前页面没有有效订阅/展示。不能把它描述成当前用户可见功能或正在 2 Hz 更新的页面。`DataSource` 仅保留以 2 Hz 调用 `get_matrix_touch()` 并发出矩阵采集信号的代码，`ApiManager.get_matrix_touch()` 仅把 SDK 五个矩阵接口映射到对应键；这些是可迁移的采集能力，不是当前 UI 证据。

### 模型现状

`HandPoseView` 使用 `pyqtgraph.opengl` 自绘手掌、拇指和四根三节手指，按 6 维值做平滑动画、视角固定为侧向约 45°，并在大于阈值的关节变化时短暂高亮。它只在 `len(joint_names) == 6` 时构建模型；其他型号 `is_supported()` 为 false，`HandPoseCard` 显示“不支持实时姿态图”。仓库只提供 `resources/models/linkerhand_o6` 的 GLB/URDF 资源，但当前控制台 3D 绘制代码并不从该模型目录加载；不能把资源存在写成所有型号已有可视化。

依据：`widgets/waveform_panel.py`、`matrix_panel.py`、`hand_pose_card.py`、`hand_pose_view.py`、`core/data_source.py`、`core/api_manager.py`、`resources/models/linkerhand_o6/`、`pages/waveform_page.py`（明确写着已废弃）。

V2 迁移要求：保留触觉采集能力，但重新接入诊断入口并做 capability gating；用 telemetry capability 决定曲线/矩阵/模型可见性；保存抓取事件的时间、关节和数值；将 O6 6D 模型与通用型号状态展示分开，不能把 GLB 资源误当作运行时已接入模型。

## 7. 视觉识别与视觉模仿（O6）

### 用户入口和工作流

侧边栏“视觉识别”进入 `VisionPage`。页面启动默认是预览模式：点击“开始模仿”后，工作线程按 `CAP_DSHOW`、`CAP_MSMF`、默认后端尝试打开 640×480 摄像头，每个后端约 3 秒超时；初始化 MediaPipe `solutions` 或 Tasks 后端，使用一只手、21 个 landmark，抽取 11 个控制点并计算拇指弯曲/横摆和四指 curl，映射为 O6 6D pose。

页面默认只识别显示，不下发动作。用户需先在摄像头运行状态下点击“校准张开”和“校准握拳”，再自行确认机械手上电、CAN 已连接、右上角为“已连接”，勾选“允许下发”。“拇指外展/内收”保存横摆基线；弯曲/横摆反向开关改变映射方向；“测试张开/握拳”和六个通道测试走同一输出开关。

### 参数和状态

- 常量默认：EMA `0.35`，死区 `4`，发送间隔 `0.12s`（约 8 Hz），手指最大单步 `35`，拇指横摆最大单步 `20`；UI 可改 EMA 0.05–0.95、死区 0–30、间隔 0.03–0.50 s、步长 1–80。
- O6 端点来自 `HAND_CONFIGS["O6"]`：张开 `[250]*6`，握拳 `[102,18,0,0,0,0]`，初始 `[250]*6`；pose 每轴限制 0–255。
- `unstarted`/`opening`/`running`/`stopped`/`error` 是页面状态；摄像头错误、打开超时、MediaPipe 初始化失败会停止或仅进入不可识别状态并写日志。
- 实时路径先 EMA，再限频、最大步长和 deadband；没有有效手时跳过下发。回放时 `live_emit_blocked_by_playback` 阻塞实时 pose。

### 录制、回放和失败/互斥

视觉页可录制 raw pose、EMA pose、curl 和检测标记，保存到 `recordings`。回放前确认设备，回放开始会关闭硬件实时同步并暂停实时发送；回放结束/停止才解除屏障。切换页面或关闭窗口会停止 worker、录制和回放；`hideEvent` 也会关闭硬件开关。

视觉输出开关只在本页生效；代码没有把 Vision 的运行状态写入 `ui_state.ActionState`，因此不能推导出它与主控制台/猜拳的全局写入互斥。页面自身通过硬件开关、回放屏障和停止清理降低风险，但摄像头、猜拳和普通动作的跨页面资源互斥仍是 V2 需要明确实现/验证的事项。

依据：`pages/vision_page.py`、`utils/signal_bus.py`、`config/constants.py`、`main_window.py`。

V2 迁移要求：MediaPipe 模型使用离线资源/Worker 边界；把摄像头权限、后端超时、模型缺失、无手、输出关闭、校准不足和硬件断连做成可观察错误；保留 O6-only 限制和所有平滑/限步/回放屏障参数，不宣称已完成真实摄像头或机械手端到端验证。

## 8. 自适应抓取

### 用户入口和操作流程

入口在控制台右侧 `AdaptiveGraspCard`，不是单独侧边栏页面。卡片按当前型号列出抓取 Profile 和每个关节的接触评分/状态，提供“开始自适应抓取”“停止并锁定”“安全释放”“定制并锁定”“空载基线标定”。配置编辑按钮只在状态 idle 可用。

正式流程：

1. 选择当前型号的 Profile；控制器要求自身处于 `IDLE`，否则拒绝重复启动。
2. 检查设备连接、型号配置、固件版本匹配的空载标定。没有标定时卡片弹窗允许用户选择最低速试验模式；正式模式拒绝运行。
3. 进入预抓取姿态，按 Profile 设置临时扭矩（拇指轴 40、闭合轴 80、其余 255），等待约 500 ms 后开始周期控制。
4. 各关节以粗步长闭合；接触评分达到候选后切换细步长，连续窗口确认后冻结该关节。满足拇指接触和至少 N 个其他手指后预紧、保持和稳定性验证。
5. 成功后可保持当前姿态，或“安全释放”按 Profile 周期逐步回到预抓取位置；成功后可将当前实时姿态保存为带型号的自定义预设。

### Profile、标定和支持型号

`grasp_profile.py` 的默认 Profile 为 `default_power_grasp_o6`、`_l6`、`_l7`、`_l10`、`_l20`，均有型号、pregrasp、close_limits、粗/细步长、周期、超时、窗口、接触阈值、拇指必需、最少手指接触、预紧步数、验证时间和反馈过期阈值。配置持久化为用户配置目录 `grasp_profiles.yaml`；卡片只展示 `get_profiles_for_model(current_hand_model)` 的匹配项。

标定由 `grasp_calibration.py` 按 `hand_model + hand_type + firmware_version` 建 key，记录每关节误差阈值、抖动阈值、运动阈值。标定入口要求设备连接，并要求机械手悬空、动作区无物体、急停可用；控制器先回到初始位置，再以 50 ms 周期按 4 的步长做全行程扫描，计算并持久化数据，最后复位。没有匹配标定时正式抓取禁止开始；`force_test=True` 使用兜底阈值 `error=15、jitter=2、movement=2`，并发出低速试验提示。

代码定义了 O6、L6、L7、L10、L20 的默认抓取 Profile；`HAND_CONFIGS` 还含更多型号，但并不等于它们拥有抓取 Profile 或通过了抓取验证。没有任何真实硬件验收结论可从这些源码/单测推出。

### 状态机和核心算法

总状态 `GraspState`：`IDLE → PREPARING → PREGRASP → CLOSING_COARSE → CLOSING_FINE → PRELOADING → HOLDING → SUCCESS`，另有 `CALIBRATING`、`RELEASING`、`FAILED`、`ABORTED`；枚举还保留 `FORMING_CONTACT`、`VERIFYING`。关节状态含 `IDLE`、粗/细闭合、候选接触、确认接触、冻结、到达限位和 ERROR。

`JointSignalAnalyzer` 用误差、误差变化/抖动和运动量构造接触评分；连续 `confirmation_windows` 个周期满足阈值才确认。控制器检查反馈时间戳，默认超过 300 ms 即中止；离线/虚拟模式通过 `_simulate_feedback()` 使目标跟随，并在低于 150 的闭合轴模拟阻挡，用于软件测试/演示，不是物理仿真证明。

抓取中 `ui_state.ActionState` 被锁为 `ACTION_RUNNING`，结束/中止恢复 idle，并恢复用户扭矩。`playback_stopped` 被控制器当作紧急停止信号；这仍是软件事件，不等价于硬件急停。

依据：`widgets/adaptive_grasp_card.py`、`core/adaptive_grasp_controller.py`、`grasp_profile.py`、`grasp_calibration.py`、`grasp_state.py`、`joint_signal_analyzer.py`、`joint_state_cache.py`、`tests/test_adaptive_grasp_controller.py`、`tests/test_joint_signal_analyzer.py`。

### 单测覆盖与迁移要求

已有测试覆盖：从启动到粗闭合、候选接触到预紧/保持/成功、紧急停止、反馈过期、安全释放、非确认关节在预紧时冻结，以及分析器正常跟随/停滞/抖动/脏数据。它们使用 fake API/缓存，不是 CAN 或机械手测试。

V2 必须把 Profile schema、型号/手型/固件标定 key、反馈新鲜度、临时扭矩恢复、每关节冻结、预紧/保持/释放和试验模式警告迁移为纯状态机/运行时 contract；UI 只调用 feature-local controller。必须明确支持型号、缺少 Profile/标定、数据过期、断连和 stop/unlock 的可见状态。

## 9. 猜拳小游戏

### 流程、摄像头和授权

入口为侧边栏“小游戏”。点击“开始游戏”后进入 `CAMERA_OPENING`，按 DSHOW/MSMF/default 后端打开摄像头并初始化 MediaPipe；成功后每轮依次进入 `COUNTDOWN`（3、2、1）、`SHOOT`、`JUDGING`、`ROUND_RESULT`，结果展示约 1.8 s 后下一轮。停止会结束 worker、计时器和当前轮。

摄像头 worker 每帧检测一只手并以指弯曲/伸展评分分类“石头/剪刀/布”；连续同一候选达到 `STABLE_FRAMES=6` 才锁定人类手势，2 秒内未锁定则判为 invalid。识别只用 MediaPipe 21 点，不复用视觉模仿的 O6 pose 映射。

机械手出拳需要单独勾选“启用”，弹窗要求上电、CAN 连接、顶栏状态已连接；关闭时游戏仍可识别人类和计分但不发送动作。机器在倒计时结束、识别人类之前先根据策略锁定手势，UI 明确记录 `locked_before_human=True`。石头/布为一次 pose 下发；剪刀先发拇指横摆阶段，约 360 ms 后发最终阶段。手动“石头/剪刀/布”、恢复初始也受该开关约束。

### 状态、计分和限制

状态常量：`IDLE`、`CAMERA_OPENING`、`COUNTDOWN`、`SHOOT`、`JUDGING`、`ROUND_RESULT`、`STOPPED`、`ERROR`。比分是 human/machine/draw 三项；“重置比分”只清比分，不自动清个体化策略 profile，需另点“重置当前玩家策略”。动作 pose 常量硬编码来自 `HAND_CONFIGS["O6"]`，所以机械手授权和出拳只对 O6 pose 直接有定义。

依据：`pages/game_page.py`（`RPSWorker`、`GamePage`、`RPS_POSES`、`STABLE_FRAMES`、`_emit_scissors_sequence`）。

V2 迁移要求：摄像头/MediaPipe 资源、稳定帧窗口、倒计时/判定定时器、硬件授权、剪刀两段动作和 invalid 结果必须可测试；策略状态与比分分开 reset；不把无硬件模式的识别/计分写成机械手验证。

## 10. 策略模式、历史、公平性和重置

策略下拉框包含四项：

- **随机模式 (`random`)**：预测和机器出拳都从三种手势随机选择，置信度为 0。
- **频率统计 (`frequency`)**：按当前玩家历史 `human_counts` 的频率预测；历史不足时随机 fallback/低置信度。
- **马尔可夫预测 (`markov`)**：优先使用“上一次人类手势 → 下一次手势”的 transition counts，没有转移数据时退回全局频率。
- **个体化自适应 (`personalized_adaptive`)**：组合 streak、cycle、ABAB alternation、transition、胜负/平局后的反应、recent shape、frequency bias 专家；根据专家置信度和已学习分数选择，并以 `EPSILON=0.15` 小概率随机探索。

所有非随机策略的预测来源在日志中标为 `prediction_source=history_only`。当置信度低于 0.45 时机器随机出拳；有置信度时选择预测手势的克制手势（石头→布、剪刀→石头、布→剪刀）。每轮结束更新：总轮数、手势计数、最近 10 手、转移计数、上次结果后的手势计数、机器/人类/平局数、专家分数和 `round_history`。

页面展示预测、置信度、理由、机器决定、计数、最近窗口、转移提示、输/赢/平反应和机器胜率。`重置当前玩家策略` 会新建 profile、清 round history、预测和专家分数；`重置比分` 只清 scoreboard。当前代码没有跨进程/跨会话玩家身份持久化，`player_profile` 是页面内存状态。

### 公平性边界

机器在同一轮先于人类锁定出拳，且策略日志标注 history-only；这是代码层面的先后顺序和数据来源约束。它不构成统计公平性证明，也没有外部随机种子、可审计 RNG 或长时间偏差验收。V2 若保留策略，需要保存可审计的策略输入、随机分支和 reset 边界，避免把“展示 fairness 文案”当作公平性测试。

依据：`pages/game_page.py` 的 `STRATEGY_*` 常量、`predict_human_next_gesture()`、`choose_machine_gesture_by_personalized_strategy()`、`_update_player_profile()`、`_reset_player_strategy()`、策略 UI 区域。

## 11. 结构化/界面日志、主题、演示模式和响应式布局

### 日志

`signal_bus.connection_message(level, message)` 驱动 `LogPage`，页面最多保留 2000 条，显示时间、级别和颜色；支持自动滚动、复制、导出 TXT、确认清空。连接、动作、抓取、视觉、猜拳还会写 stdout/`command_trace` 前缀日志（例如 `VisionSync`、`VisionJoint`、`GestureRecord`、`RPSGame`），这些不是同一个持久化日志存储。导出只包含界面消息队列，不会自动包含全部 stdout/command trace。

### 深色模式

`TopBar` 的“深色模式”按钮调用 `ThemeManager`，主题写入 Qt settings 的 `appearance/theme`，通过 QSS、palette、内联样式刷新；`WaveformPanel` 和 3D 模型监听主题变化。默认主题、保存路径和动画由 `styles/theme_manager.py` 决定。不能仅凭按钮存在断言所有第三方绘图部件均完整适配。

### 演示模式

顶部“演示模式”只有在连接状态 `CONNECTED` 时允许打开，否则发 warning 并自动取消。打开后切换到 `DemoPage`，按钮执行当前型号真实 preset；退出回到上一个普通页。它不是离线模拟开关，页面文字写明动作将真实下发。离线调试来自 `ApiManager` 的连接失败分支，与演示模式是不同状态。

### 响应式布局

主窗口宽度小于 1500 时侧边栏 compact；小于 980 时通知 `ConsolePage.set_layout_mode`。控制台内部按自身宽度分三档：`>=1420` wide 三列（关节+曲线、3D 姿态、预设/抓取），`1100–1419` compact 三列但间距较小，`<1100` narrow 使用滚动区，把左侧/姿态并排后纵向放预设和抓取。主窗口最小尺寸 1100×700。视觉和猜拳页面右侧控制区使用 `QScrollArea`。

依据：`main_window.py`、`widgets/top_bar.py`、`styles/theme_manager.py`、`pages/demo_page.py`、`pages/console_page.py`、`pages/log_page.py`、`widgets/waveform_panel.py`、`widgets/hand_pose_view.py`。

V2 迁移要求：结构化事件（source、level、operation、device/session、error）与 UI 日志渲染分离；主题/compact 是 presentation state，不改变硬件语义；演示模式必须保留已连接门槛和“真实下发”警示；响应式断点和窄屏滚动应由 V2 layout 验证而非只复制 CSS 数值。

## 12. 核心互斥和已知问题

### 已能从代码确认的互斥

- `ActionExecutor` 在非 idle（允许循环）时忽略新的离散动作；录制中拒绝通用回放，回放中拒绝录制。
- 自适应抓取把 `ActionState` 锁为 `ACTION_RUNNING`，并监听 `playback_stopped` 作为软件中止事件；配置、标定按钮在非 idle 禁用。
- Vision 回放阻塞 Vision 实时输出；Vision/猜拳硬件输出需要各自显式授权。
- 主窗口切换普通页面会关闭演示模式；关闭窗口会停止视觉/猜拳线程、录制回放、数据源和 API。

### 需要 V2 明确或复验的缺口

1. VisionPage 和 GamePage 的运行/输出开关没有统一写入 `ui_state.ActionState`；仅凭页面内开关不能证明它们与控制台动作、循环、抓取全局互斥。
2. `playback_stopped` 同时承担回放停止和抓取“紧急停止”信号名，语义容易误用；V2 应拆成明确的 software stop、playback stop、unlock/physical E-stop 事件。
3. `ApiManager` 连接失败的离线虚拟反馈可用于调试；但 `ActionExecutor` 的离散动作要求 `CONNECTED`，各页面的直接 pose 流又有自己的开关，形成不同的“离线可操作”边界。
4. `RecorderPage`、`PresetPanel`、`CycleControl`、`ConnectionBar` 和 `Page.WAVEFORM` 等旧组件仍在树中但未由 `MainWindow` 挂载；迁移时应以当前挂载路径为基线，不把死代码算作用户可用入口。
5. 3D 模型只对 6 维配置构建，O6 资源目录存在但未证明被旧版运行时加载；多型号姿态图、L20/L25 的模型和传感器显示需要 capability 设计。
6. MediaPipe Tasks 模型在缺少本地环境变量文件时尝试网络下载；摄像头后端、权限、网络、模型下载和线程退出均需真实环境复验。
7. 抓取 Profile/标定文件写入用户配置目录，当前没有版本迁移、并发锁或 UI 导入导出；损坏文件只在自定义预设 store 中有显式备份策略。
8. 旧测试集中在纯逻辑、fake API、状态缓存和部分单测；没有替代真实 CAN、上电、运动风险、摄像头权限、MediaPipe Worker、PyQt 交互或跨页面竞争验收。
9. `SettingsPage` 实际是占位页，仅提供 `SAFE_OPEN` 下发链路自检按钮；运行时设置仍由 `setting.yaml` 管理。
10. “紧急停止”按钮、软件 stop 和抓取中止都不能从源码证明会切断电源或阻止底层驱动已排队的物理运动；V2 文案必须保持软件安全锁/写锁的准确边界。

### 迁移验收最小集合

V2 接手 Agent 至少应分别证明：fake/simulator 下的 contract 和状态机；真实 O6 + PCAN 下的连接、能力读取、位置/速度/扭矩写入、反馈、stop/unlock、断连/重连；浏览器/Tauri 下的 Vision/猜拳摄像头与 Worker；以及窄屏、主题、日志导出和动作互斥。每项记录环境、入口、输入、观察到的事件和未验证限制，禁止以本基线的代码依据替代验收证据。
