# 《LinkerHand 机械手 GUI 控制系统二次开发总结报告》

生成时间：2026-06-24  
本地项目路径：`D:\Work Space\FFocalors-linkerhand-python-sdk`  
当前本地仓库：`https://github.com/FFocalors/FFocalors-linkerhand-python-sdk.git`  
原始开源项目：`https://github.com/linkerbotai/linker_hand_python_sdk`  
原始仓库 main HEAD：`305209e1f4c19fba380a4d4111046a862b5ec349`  
当前本地 HEAD：`5c41cac bug修完`

> 说明：本报告基于当前本地代码、`git status --short`、`git diff --stat`、指定文件 diff、核心目录阅读，以及原始 GitHub 仓库页面的只读结构对比整理。未执行 `git reset`、`git clean`、`git pull`、`git push`，未安装依赖，未回退任何改动。未将原始仓库 clone 到本地做逐行 diff，因此“原始项目对比”属于结构级、功能级对比。本轮只新增本 Markdown 汇报材料文件，未修改代码文件。

---

## 1. 项目背景

原始 LinkerHand Python SDK 是灵心巧手机械手的基础 Python 控制项目，核心能力集中在 `LinkerHand/` SDK、CAN/RS485 通讯、关节位置下发、速度/力矩设置、触觉/状态读取，以及若干示例脚本。原始项目已经具备让用户通过 Python API 调用 `LinkerHandApi.finger_move()` 控制机械手的能力。

本项目在原始 SDK 基础上进行了二次开发，目标是把“基础 SDK 调用示例”升级为一个可展示、可交互、可诊断、可视觉遥操作、可动作录制回放、可进行人机猜拳互动的 GUI 控制系统。改造重点不是替换原始 SDK，而是在尽量保护原有机械手可运行功能的前提下，围绕 GUI、视觉感知、安全下发和演示体验做系统增强。

二次开发的主要动机包括：

- 让机械手控制从命令行脚本升级为可视化 GUI，方便现场演示和非开发人员操作。
- 通过摄像头和 MediaPipe 实现人手到 O6 六维控制量的视觉遥操作。
- 支持动作录制、JSON 保存、加载和回放，形成可复现的动作序列能力。
- 增加人机猜拳小游戏，提升项目展示的互动性。
- 增加 CommandTrace、状态栏和自检按钮，解决“界面显示已连接但机械手不动”的诊断难题。

---

## 2. 项目整体结构

当前项目主要目录结构如下：

```text
FFocalors-linkerhand-python-sdk/
├── LinkerHand/                         # 原始 SDK 核心包：API、CAN/RS485、配置、工具
│   ├── linker_hand_api.py              # 统一控制入口 LinkerHandApi
│   ├── config/                         # setting.yaml、各型号动作/姿态配置
│   ├── core/can/                       # CAN 通讯实现，含 O6/L6/L7/L10/L20/L25/G20
│   ├── core/rs485/                     # RS485/Modbus 实现，含 O6/L6/L7/L10
│   └── utils/                          # open_can、mapping、yaml、颜色输出等工具
├── example/
│   ├── gui_control/                    # GUI 控制系统，当前二次开发重点
│   │   ├── main.py                     # 当前 GUI 启动入口
│   │   ├── main_window.py              # 主窗口、页面路由、全局状态绑定
│   │   ├── gui_control.py              # 原始/旧版 GUI 单文件入口，仍保留
│   │   └── lhgui/
│   │       ├── pages/                  # 页面层：控制台、视觉、猜拳、录制、设置等
│   │       ├── core/                   # 业务核心：ApiManager、Recorder、ActionExecutor
│   │       ├── utils/                  # SignalBus、CommandTrace、UI 状态等
│   │       ├── widgets/                # 组件层：左侧导航、连接栏、关节滑条、3D 姿态视图
│   │       ├── config/                 # GUI 内部手型和预设动作 constants.py
│   │       ├── resources/              # 图标、O6 3D 模型资源
│   │       ├── styles/                 # QSS 与主题管理
│   │       └── recordings/             # 录制动作文件目录
│   ├── vision_control/                 # 独立视觉遥操作/识别命令行原型与测试模块
│   ├── L10/ L24/ L7/                   # 原始 SDK 示例
│   ├── Linker_hand_Sapien/             # 仿真相关示例
│   └── linker_hand_mujoco/             # MuJoCo 相关示例
├── doc/                                # API 文档和图片
├── tools/                              # O6 模型导入转换工具
├── artifacts/                          # UI 设计/截图产物
├── requirements.txt                    # 项目依赖
├── run_gui.bat                         # Windows GUI 启动脚本
└── README.md / README_CN.md            # 原项目说明文档
```

目录分类：

| 目录/文件 | 类型 | 作用 |
|---|---|---|
| `LinkerHand/` | 核心 SDK | 统一 API、CAN/RS485 通讯、设备配置、状态读取和动作下发 |
| `example/gui_control/` | GUI 应用 | 当前二次开发主战场，提供完整桌面控制系统 |
| `example/gui_control/lhgui/pages/` | 页面层 | 控制台、视觉模仿、猜拳、录制、设置、日志、波形等页面 |
| `example/gui_control/lhgui/core/` | GUI 业务核心 | 连接管理、动作执行、录制回放、数据轮询等 |
| `example/gui_control/lhgui/utils/` | 通用工具 | 信号总线、CommandTrace、UI 状态管理、图标工具 |
| `example/gui_control/lhgui/widgets/` | UI 组件 | 连接栏、侧边栏、关节滑条、姿态卡片、3D 视图等 |
| `example/vision_control/` | 视觉原型 | custom11、手势识别、O6 映射、命令行遥操作与猜拳 |
| `run_gui.bat` | 启动适配 | Windows + Miniconda Python 3.9 GUI 启动脚本 |
| `requirements.txt` | 依赖 | python-can、pymodbus、mediapipe、pyqt5、pyqtgraph 等 |
| `test_out.log`、`__pycache__/` | 临时/缓存 | 调试日志和 Python 缓存，提交前建议清理或保持 ignored |

---

## 3. Git 状态与当前工作区

最终执行 `git status --short`：

```text
?? linkerhand_gui_development_summary_report.md
```

最终执行 `git diff --stat`：无代码 diff 输出。

当前代码文件相对 HEAD 没有未提交差异；本轮只新增了汇报材料：

- `linkerhand_gui_development_summary_report.md`

审计过程中重点检查过 `game_page.py`、`vision_page.py`、`api_manager.py`、`signal_bus.py`，其功能已存在于当前代码基线中。

指定文件 diff 状态：

| 文件 | 最终是否有未提交 diff | 说明 |
|---|---:|---|
| `example/gui_control/lhgui/pages/game_page.py` | 无 | 当前 HEAD 已包含硬件开关、CommandTrace、剪刀拇指横摆释放序列 |
| `example/gui_control/lhgui/pages/vision_page.py` | 无 | 当前 HEAD 已包含硬件开关连接、CommandTrace、跳过下发日志 |
| `example/gui_control/lhgui/core/api_manager.py` | 无 | 当前 HEAD 已包含连接和下发链路修复 |
| `example/gui_control/lhgui/utils/signal_bus.py` | 无 | 当前 HEAD 已包含 CommandTrace 和 pose 合法化 |

另有 ignored 文件：

- 多处 `__pycache__/`
- `example/gui_control/test_out.log`

当前检测到仍有 GUI 进程运行：

```text
D:\develop_tools\mini\envs\linkerhand_py39\python.exe
D:\Work Space\FFocalors-linkerhand-python-sdk\example\gui_control\main.py
```

注意：测试新代码前应关闭旧 GUI 进程，再重新运行 `run_gui.bat`，否则看到的可能仍是旧逻辑。

---

## 4. 原始项目功能概述

原始开源项目 `linkerbotai/linker_hand_python_sdk` 主要提供：

- `LinkerHand/` SDK 包：统一封装机械手通信和控制接口。
- `LinkerHand/linker_hand_api.py`：通过 `LinkerHandApi` 对外提供 `finger_move()`、`set_speed()`、`set_torque()`、状态读取等能力。
- `LinkerHand/core/can/`：CAN 方式控制多型号机械手。
- `LinkerHand/core/rs485/`：RS485/Modbus-RTU 方式控制 O6、L6、L7、L10 等型号。
- `LinkerHand/config/setting.yaml`：左右手、CAN、MODBUS、型号配置。
- `example/`：包含 L7、L10、L24、MuJoCo、Sapien 等示例。
- 原始 GUI 主要集中在 `example/gui_control/gui_control.py` 和原始 `views/` 结构，偏向基础滑条控制和示例演示。

原始项目局限性：

- GUI 更偏示例性质，页面组织、状态管理、诊断能力有限。
- 缺少完整的“视觉感知 -> 姿态映射 -> 实时下发”闭环。
- 缺少动作录制、动作文件管理、暂停/继续/倍速/循环回放等功能。
- 缺少适合汇报展示的人机交互玩法。
- 连接状态与实际指令下发之间缺少足够日志，出现“已连接但不动”时难定位。
- 对 Windows + PEAK USB-CAN + PCAN_USBBUS1 的展示型启动流程不够完整。

---

## 5. 二次开发总体目标

二次开发的目标可以概括为：

> 将原始 LinkerHand Python SDK 从“基础硬件控制库 + 示例脚本”升级为“面向展示、调试、遥操作和互动演示的机械手 GUI 控制系统”。

具体目标包括：

- 图形化：通过 PyQt5 建立主窗口、侧边导航、多页面控制结构。
- 可操作：支持手动滑条、预设动作、速度/力矩、复位和下发自检。
- 可感知：接入摄像头和 MediaPipe HandLandmarker，识别人手关键点。
- 可映射：将人手姿态映射为 O6 六维控制向量。
- 可回放：录制实时 pose 时间序列，保存 JSON，并按原始时间间隔回放。
- 可互动：通过猜拳小游戏展示人机交互。
- 可诊断：通过 CommandTrace、页面日志、`test_out.log` 追踪 GUI 到硬件的完整链路。
- 安全：所有真实机械手下发均受安全开关和状态判断约束。

---

## 6. 系统总体架构

当前系统可分为八层：

```text
硬件层
    ↓
PEAK USB-CAN / PCAN_USBBUS1 或 RS485/Modbus
    ↓
LinkerHand SDK 通讯层
    LinkerHandApi
    LinkerHand/core/can/linker_hand_o6_can.py
    LinkerHand/core/rs485/linker_hand_o6_rs485.py
    ↓
GUI 连接与下发层
    ApiManager
    signal_bus
    CommandTrace
    ↓
GUI 页面层
    ConsolePage / VisionPage / GamePage / RecorderPage / SettingsPage
    ↓
视觉识别层
    OpenCV camera
    MediaPipe Tasks HandLandmarker
    21 点关键点
    ↓
动作映射层
    11 点核心控制点
    finger curl / thumb_bend / thumb_swing
    O6 6D pose
    ↓
录制回放层
    pose 时间序列
    JSON 保存/加载
    pause/resume/speed/loop
    ↓
日志诊断层
    VisionSync / VisionJoint / GestureRecord / RPSGame / CommandTrace / test_out.log
```

核心调用链：

```text
GUI 页面 / 控件
    ↓ emit_finger_move_requested(...)
signal_bus.sanitize_finger_pose()
    ↓
SignalBus.finger_move_requested
    ↓
ApiManager.finger_move()
    ↓
LinkerHandApi.finger_move()
    ↓
O6 CAN / RS485 set_joint_positions()
    ↓
机械手硬件
```

---

## 7. 核心功能一：机械手 GUI 控制与连接诊断

### 做了什么

当前 GUI 入口为：

- `run_gui.bat`
- `example/gui_control/main.py`
- `example/gui_control/main_window.py`

`run_gui.bat` 指定：

```text
D:\develop_tools\mini\envs\linkerhand_py39\python.exe
```

并从项目根目录进入：

```text
example\gui_control\main.py
```

GUI 主窗口 `MainWindow` 负责：

- 初始化 `ApiManager`
- 创建全局 `Recorder`
- 创建 `ConsolePage`、`DemoPage`、`RecorderPage`、`GamePage`、`VisionPage`、`SettingsPage`
- 创建左侧导航和顶部状态区域
- 监听连接状态、录制状态、回放状态
- 页面切换与退出时资源释放

### 怎么做

关键文件：

- `example/gui_control/main.py`
- `example/gui_control/main_window.py`
- `example/gui_control/lhgui/core/api_manager.py`
- `example/gui_control/lhgui/utils/signal_bus.py`
- `example/gui_control/lhgui/widgets/connection_bar.py`
- `example/gui_control/lhgui/pages/settings_page.py`

`ApiManager` 负责读取 `LinkerHand/config/setting.yaml`，当前配置为：

- `LEFT_HAND.EXISTS: True`
- `LEFT_HAND.JOINT: O6`
- `LEFT_HAND.CAN: PCAN_USBBUS1`
- `LEFT_HAND.MODBUS: None`

也就是 Windows + PEAK USB-CAN / PCAN_USBBUS1 + O6 左手。

`signal_bus.py` 增加了：

- `command_trace(message)`
- `sanitize_finger_pose(pose, expected_len=None)`
- `emit_finger_move_requested(pose, source="GUI")`

### 解决的问题

原先 GUI 中可能出现“右上角显示已连接，但机械手动作无响应”的问题。当前链路通过 CommandTrace 将每一步记录出来：

- GUI 请求来源
- pose 是否合法
- 是否被 sanitize
- signal 是否发出
- ApiManager 是否收到
- 是否处于 offline
- 是否调用 `api.finger_move`
- SDK 返回或异常信息

### 展示价值

现场演示时可以先在设置页点击：

```text
下发链路自检：SAFE_OPEN
```

该按钮会通过统一链路发送安全张开 pose，验证从 GUI 到 SDK 到机械手的指令链路是否畅通。

---

## 8. 核心功能二：基于视觉手势识别的机械手遥操作

### 做了什么

在 `VisionPage` 中实现摄像头实时采集、MediaPipe 手部关键点识别、人手姿态到 O6 六维 pose 的映射，并在用户勾选安全开关后实时下发到机械手。

关键文件：

- `example/gui_control/lhgui/pages/vision_page.py`
- `example/vision_control/hand_pose_mapper.py`
- `example/vision_control/gesture_recognizer.py`
- `example/vision_control/left_hand_teleop.py`
- `example/vision_control/custom11_keypoints.py`

### 怎么做

`VisionPage` 中的 `ImitationWorker` 是 QThread，负责：

- 打开摄像头
- 初始化 MediaPipe Tasks `HandLandmarker`
- 读取图像帧
- 检测 21 点手部关键点
- 绘制关键点和 overlay
- 调用 `_compute_pose()` 计算 O6 pose
- 发出 `pose_computed` 信号给 GUI 主线程

O6 输出向量固定为 6 维：

```text
[thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]
```

其中第二维是 `thumb_swing / 大拇指横摆`，不是 wrist。

姿态映射逻辑包括：

- index/middle/ring/little 的 proximal、distal 和 fused curl。
- thumb_bend 和 thumb_swing 独立处理。
- `OPEN_POSE` 和 `CLOSE_POSE` 作为映射端点。
- 输出统一限幅到 0~255。
- EMA 平滑，默认 `EMA_ALPHA = 0.35`。
- deadband 防抖。
- max_step 限制单次跳变。
- `SEND_INTERVAL` 控制下发频率，约 8Hz。
- 未检测到手时不下发。
- 勾选“允许下发到机械手”前只识别显示，不控制硬件。

### 解决的问题

- 解决摄像头画面与 PyQt5 界面线程阻塞问题：摄像头和 MediaPipe 在工作线程中运行。
- 解决 MediaPipe 新版本 Tasks API 与传统 `mp.solutions` 的兼容问题：使用 `mediapipe.tasks.python.vision.HandLandmarker`。
- 解决人手 3 个弯曲关节与 O6 单维手指弯曲控制量不一致的问题：通过 curl score 融合映射。
- 解决大拇指弯曲和横摆耦合复杂的问题：把 `thumb_bend` 和 `thumb_swing` 分开计算、校准和反向控制。
- 解决实时下发抖动：使用 EMA、deadband、max_step、发送间隔。

### 展示价值

该模块可以作为“视觉主从遥操作”展示：

```text
人手 = 主端
摄像头 + MediaPipe = 感知层
O6 pose mapper = 映射层
机械手 = 从端
```

适合演示“人手动作驱动机械手实时模仿”的效果。

---

## 9. 核心功能三：动作录制与回放

### 做了什么

当前项目具备两类录制回放能力：

1. 全局 `Recorder`：
   - `example/gui_control/lhgui/core/recorder.py`
   - `example/gui_control/lhgui/pages/recorder_page.py`

2. 视觉模仿页内置录制回放：
   - `example/gui_control/lhgui/pages/vision_page.py`

视觉页录制回放更加完整，面向“手势动作录制与回放”展示。

### 怎么做

在 `VisionPage` 中，录制模块支持：

- 开始录制
- 停止录制
- 清空录制
- JSON 保存
- JSON 加载
- 记录 pose 时间序列
- 记录相对时间戳 `t`
- 0~255 pose 校验
- 最短帧数校验
- 最大录制时长保护
- 最小记录间隔
- 最小 pose 变化阈值
- keepalive 记录

回放模块支持：

- 开始回放
- 暂停/继续
- 停止回放
- 倍速回放
- 循环回放
- `MAX_REPLAY_STEP` 限制回放单帧跳变
- 按原始时间间隔恢复动作节奏
- 回放期间阻断 live pose 下发

### 解决的问题

- 解决现场演示依赖实时手势稳定性的问题：动作可以提前录制并稳定复现。
- 解决实时视觉流和回放流冲突的问题：通过 `_live_emit_blocked_by_playback` 和 `_playing` 阻断 live 下发。
- 解决动作突变对机械手冲击的问题：回放中使用 `MAX_REPLAY_STEP` 做限幅。
- 解决录制数据污染原始 SDK 配置的问题：保存为 JSON，不写入原有 `*_positions.yaml`。

### 展示价值

可以展示“人手动作录制 -> 保存 -> 加载 -> 机械手复现”的完整流程，适合作为项目汇报中的可复现实验能力。

---

## 10. 核心功能四：人机猜拳小游戏

### 做了什么

在 `GamePage` 中实现摄像头识别人类石头/剪刀/布，同时机械手作为机器玩家随机出拳，并根据规则判断胜负。

关键文件：

- `example/gui_control/lhgui/pages/game_page.py`
- `example/vision_control/rps_game.py`
- `example/vision_control/gesture_recognizer.py`

### 怎么做

`game_page.py` 包含：

- 摄像头采集和画面显示
- MediaPipe 手势识别
- 石头/剪刀/布分类
- 稳定帧锁定
- 3、2、1 倒计时
- 机械手随机出拳
- 胜负判断
- 多轮比分
- 人赢/机器赢/平局/未识别结果
- 结果卡片和动画效果
- “启用机械手出拳”安全开关
- 每轮只下发一次机器出拳 pose

当前剪刀动作经过现场调参，采用：

```text
thumb_swing_only: [102, 167, 0, 0, 0, 0]
scissors_final : [102, 167, 255, 255, 0, 0]
```

含义：

- 大拇指弯曲保持握拳值 `102`。
- 只把大拇指横摆从握拳值移动到实测释放食指的 `167`。
- 再让食指和中指同时弹出。

### 解决的问题

- 猜拳页面与视觉模仿页面分离，避免“机器人出拳”被实时模仿逻辑干扰。
- 每轮只下发一次机器出拳，避免持续刷 pose。
- 通过硬件启用开关避免未确认时误下发。
- 通过稳定帧机制避免手势识别抖动导致误判。
- 通过剪刀分段下发解决拳头切剪刀时大拇指挡住食指的问题；该细节仍需现场继续微调确认。

### 展示价值

猜拳小游戏适合展示人机交互和机械手拟人化动作效果，是汇报中最直观的互动演示模块。

---

## 11. 核心功能五：安全机制与日志诊断

### 安全机制

当前系统的安全策略包括：

- 页面初始化不自动下发。
- 视觉模仿页必须勾选“允许下发到机械手”。
- 猜拳页必须勾选“启用机械手出拳”。
- 未检测到手不下发 live pose。
- 回放过程中阻断 live pose 下发。
- 录制和回放状态互斥。
- pose 下发前统一检查长度和 0~255 范围。
- offline/debug 状态不调用真实硬件。
- 连接失败时进入离线调试，不误报真实下发。
- 异常写入日志并通过 GUI 状态提示。

### 日志体系

| 日志名 | 位置/来源 | 作用 |
|---|---|---|
| `CommandTrace` | `signal_bus.py`、`ApiManager`、页面 | 追踪 GUI 到 SDK 的下发链路 |
| `VisionSync` | `vision_page.py` | 摄像头、MediaPipe、实时同步状态 |
| `VisionJoint` | `vision_page.py` | curl、pose、调参、校准细节 |
| `GestureRecord` | `vision_page.py` | 动作录制和回放状态 |
| `RPSGame` | `game_page.py` | 猜拳倒计时、出拳、识别和结果 |
| `test_out.log` | `example/gui_control/test_out.log` | 汇总调试输出，便于复盘 |

定位问题的建议顺序：

```text
摄像头问题
    看 VisionSync / RPSGame camera 日志
MediaPipe 问题
    看 mediapipe init / HandLandmarker 日志
pose 映射问题
    看 VisionJoint raw pose / ema pose / debug 指标
GUI signal 问题
    看 CommandTrace GUI request 和 signal emit
ApiManager 问题
    看 ApiManager received / calling api.finger_move
CAN/SDK 问题
    看 LinkerHandApi、PCAN、O6 CAN 输出
```

---

## 12. 技术难点与解决方案

| 难点 | 表现 | 解决方案 | 当前状态 |
|---|---|---|---|
| Windows + PCAN_USBBUS1 配置 | Windows 下 CAN 接口和驱动容易不一致 | `setting.yaml` 使用 `PCAN_USBBUS1`，`run_gui.bat` 固定 Python 环境 | 已配置，需现场硬件验证 |
| PyQt5 GUI 与线程 | 摄像头和 MediaPipe 容易阻塞 GUI | 使用 `QThread` 运行 `ImitationWorker`，通过信号回传图像和 pose | 已实现 |
| 摄像头黑屏 | 摄像头打开慢、backend 不稳定 | `_open_camera_with_timeout`、状态提示、超时日志 | 已实现，需不同电脑验证 |
| mediapipe 0.10.35 没有 `mp.solutions` | 传统接口不可用 | 使用 MediaPipe Tasks `HandLandmarker` | 已实现 |
| 人手 3 关节与 O6 控制量不一致 | 人手关键点维度和机械手控制维度不同 | proximal/distal/fused curl + O6 六维映射 | 已实现 |
| 大拇指方向与横摆范围 | thumb_bend/ thumb_swing 容易理解反 | 独立计算、反向选项、手动校准、猜拳剪刀现场调参 | 基本完成，需实物继续微调 |
| GUI 已连接但不下发 | 状态显示和命令链路不一致 | `CommandTrace` + `signal_bus` + `ApiManager` 全链路日志 | 已解决 |
| 回放与实时下发冲突 | live pose 和 playback 同时发会抢控制权 | `_live_emit_blocked_by_playback`、状态互斥 | 已实现 |
| 猜拳随机出拳与视觉模仿混淆 | 游戏动作不能被实时模仿覆盖 | `GamePage` 独立动作下发、每轮一次、硬件开关 | 已实现 |

---

## 13. 创新点总结

适合汇报的创新点：

1. 基于视觉手部姿态估计的机械手遥操作，实现人手作为主端、O6 机械手作为从端的实时模仿。
2. 将 MediaPipe 21 点手部关键点映射为 O6 六维控制向量，解决视觉高维输入与机械手低维控制之间的接口问题。
3. 针对人手三关节与机械手控制量不一致，引入 proximal/distal/fused curl 融合映射。
4. 对大拇指 `thumb_bend` 和 `thumb_swing` 单独建模、校准和调试，避免把横摆误认为 wrist。
5. 增加动作录制与回放能力，可以将视觉模仿过程保存为 JSON 时间序列并复现。
6. 构建人机猜拳小游戏，将视觉识别、随机出拳、机械手动作和胜负判断融合为互动演示。
7. 建立 GUI 内置下发链路诊断体系，通过 CommandTrace 定位从页面到 SDK 再到硬件的问题。
8. 形成多模式控制系统：手动滑条、预设动作、视觉模仿、动作回放、小游戏交互并存。

---

## 14. 文件改动与模块作用清单

| 文件 | 作用 |
|---|---|
| `run_gui.bat` | Windows 启动脚本，固定 Miniconda Python 3.9 环境，进入 `example/gui_control/main.py` |
| `example/gui_control/main.py` | 当前 GUI 应用入口，初始化 QApplication、主题、主窗口 |
| `example/gui_control/main_window.py` | 主窗口、页面切换、全局状态、Recorder 和 ApiManager 组装 |
| `example/gui_control/lhgui/core/api_manager.py` | 读取配置、连接 SDK、区分 connected/offline、执行 `finger_move`、速度和力矩设置 |
| `example/gui_control/lhgui/utils/signal_bus.py` | 全局信号总线、CommandTrace、pose 合法化、统一动作下发入口 |
| `example/gui_control/lhgui/core/action_executor.py` | 预设动作执行、连接状态检查、动作最终下发 |
| `example/gui_control/lhgui/core/recorder.py` | 全局动作录制、JSON 保存、播放和进度信号 |
| `example/gui_control/lhgui/widgets/connection_bar.py` | 顶部/连接状态展示，支持已连接、未连接、离线调试等状态 |
| `example/gui_control/lhgui/widgets/joint_panel.py` | 手动关节滑条，滑动时通过统一 signal_bus 下发 |
| `example/gui_control/lhgui/pages/settings_page.py` | 设置页和“下发链路自检：SAFE_OPEN”按钮 |
| `example/gui_control/lhgui/pages/vision_page.py` | 视觉模仿、摄像头、MediaPipe、O6 映射、调参、录制回放、安全开关 |
| `example/gui_control/lhgui/pages/game_page.py` | 猜拳小游戏、倒计时、手势识别、随机出拳、胜负判断、剪刀动作调参 |
| `example/gui_control/lhgui/pages/recorder_page.py` | 全局录制页面，管理录制动作和回放 |
| `example/gui_control/lhgui/widgets/hand_pose_view.py` | 基于 `pyqtgraph.opengl` 的 O6 3D 姿态可视化 |
| `example/gui_control/lhgui/config/constants.py` | GUI 内部型号、关节名、预设动作配置 |
| `example/vision_control/hand_pose_mapper.py` | custom11 到 O6 六维 pose 的连续映射器 |
| `example/vision_control/gesture_recognizer.py` | custom11 石头/剪刀/布识别器 |
| `example/vision_control/left_hand_teleop.py` | 命令行视觉遥操作入口 |
| `example/vision_control/rps_game.py` | 命令行猜拳原型 |

---

## 15. 环境与依赖分析

当前 `requirements.txt` 主要包含：

- 通讯：`python-can`、`python-can-candle`、`pymodbus==3.5.1`、`pyserial`、`minimalmodbus`
- GUI：`pyqt5`、`pyqtgraph`
- 视觉/感知：`mediapipe`
- 科学计算与工具：`PyYAML`、`h5py`、`matplotlib`、`tqdm`
- 其他：`dm_control`、`uvicorn`、`wandb` 等

`example/vision_control/requirements_vision.txt` 包含：

```text
opencv-python>=4.5.0
```

注意事项：

- 当前 GUI 的 `vision_page.py` 直接 `import cv2`，因此运行视觉页时环境中必须安装 OpenCV。
- `hand_pose_view.py` 使用 `pyqtgraph.opengl`，运行 3D 视图时通常需要 OpenGL 相关运行环境。
- `mediapipe` 未固定版本；若使用 `0.10.x`，应优先按当前代码的 MediaPipe Tasks 路线运行。
- `run_gui.bat` 固定使用 `D:\develop_tools\mini\envs\linkerhand_py39\python.exe`，现场演示时应确认该环境依赖完整。

---

## 16. 演示流程

推荐汇报演示步骤：

1. 关闭旧 GUI 进程，双击或执行 `run_gui.bat`。
2. 确认右上角连接状态为“已连接”，设备为 O6，CAN 为 `PCAN_USBBUS1`。
3. 进入设置页，点击“下发链路自检：SAFE_OPEN”，观察机械手是否安全张开。
4. 进入控制台页面，使用滑条或预设动作测试张开、握拳、OK、点赞等基础动作。
5. 进入视觉模仿页，启动摄像头，确认画面、关键点、raw pose、ema pose 显示正常。
6. 完成张开手/握拳校准，必要时调整 thumb_bend、thumb_swing 反向和单指校准。
7. 勾选“允许下发到机械手”，展示人手驱动机械手实时模仿。
8. 在视觉模仿页点击“开始录制”，做一段动作，停止录制并保存 JSON。
9. 加载录制文件，演示暂停/继续/倍速/循环回放。
10. 进入猜拳小游戏，勾选“启用机械手出拳”，展示 3、2、1 倒计时、人类手势识别、机械手随机出拳、胜负判断。
11. 打开或展示 `test_out.log` 中的 CommandTrace、VisionSync、RPSGame 日志，说明诊断能力。

---

## 17. 当前状态与待完善方向

已完成：

- GUI 多页面结构。
- Windows `run_gui.bat` 启动适配。
- O6 + PCAN_USBBUS1 配置读取。
- GUI 到 SDK 下发链路日志化。
- `finger_move_requested` 统一下发入口。
- `ApiManager` connected/offline 区分。
- 设置页 SAFE_OPEN 下发自检。
- 视觉模仿页摄像头、MediaPipe、pose 映射、EMA、deadband、max_step。
- 视觉页动作录制与 JSON 回放。
- 猜拳小游戏基本流程。
- 猜拳剪刀动作针对实物反馈进行横摆调参。

需现场实物测试验证：

- 不同光照和背景下 MediaPipe 检测稳定性。
- 大拇指 `thumb_swing=167` 是否在所有拳头到剪刀切换场景下稳定释放食指。
- 回放速度、`MAX_REPLAY_STEP` 对实际机械手动作平滑度的影响。
- 长时间运行时摄像头、CAN、GUI 线程稳定性。
- 不同 PC、不同 PEAK USB-CAN 驱动版本下的连接表现。

未来可扩展：

- 将 `custom11` 输入接入 GUI，支持外部视觉系统或网络关键点流。
- 建立可配置动作库，把剪刀、抓取、释放等动作参数放入 JSON/YAML。
- 增加更细的 O6 方向标定界面和动作参数调试面板。
- 增加远程遥操作接口，例如 WebSocket/FastAPI。
- 增加姿态评分和动作质量评估。
- 增加演示模式脚本，一键串联自检、视觉模仿、录制回放、猜拳。

---

## 18. 风险点和提交前清理建议

风险点：

- 当前仍有运行中的 GUI 进程；测试新代码必须先关闭旧进程。
- 当前工作区只有新增报告文件 `linkerhand_gui_development_summary_report.md` 未跟踪；代码文件相对 HEAD 无未提交 diff。
- `api_manager.py` 和 `signal_bus.py` 当前无 diff，但报告依赖其当前 HEAD 中已有实现。
- `mediapipe` 版本未固定，换环境可能出现 Tasks 模型加载差异。
- `opencv-python` 不在主 `requirements.txt` 中，而是在 `example/vision_control/requirements_vision.txt` 中；GUI 视觉页也需要 OpenCV。
- `pyqtgraph.opengl` 对 OpenGL 环境有要求。
- 猜拳剪刀动作已经按实物反馈调参，但仍应现场复测。

提交前建议：

- 如需提交：单独提交 `linkerhand_gui_development_summary_report.md` 作为汇报材料；代码文件当前无需额外提交。
- 不提交或清理：`__pycache__/`。
- 不提交或清理：`example/gui_control/test_out.log`。
- 检查 `.vscode/` 是否包含个人路径配置。
- 检查 `artifacts/` 是否为汇报截图资源，若用于汇报可保留，否则不建议混入功能提交。
- 如需提交报告材料，可单独提交 Markdown/Word，不与控制逻辑混在同一个 commit 中。

---

## 19. 总结

当前项目已经从原始 LinkerHand Python SDK 的基础控制示例，扩展为一个较完整的机械手 GUI 控制与人机交互系统。二次开发的核心成果包括：可视化主界面、多页面组织、连接诊断、统一下发链路、视觉模仿控制、动作录制与回放、人机猜拳小游戏以及日志化安全机制。

该系统的价值不只在于“能控制机械手”，还在于把机械手控制变成了可展示、可调试、可复现、可交互的完整应用。对于项目汇报而言，可以突出“SDK 工程化封装”“视觉主从遥操作”“动作轨迹复现”“人机交互小游戏”和“安全诊断体系”五条主线。

---

# 额外输出 A：300 字左右项目简介

本项目基于 LinkerHand Python SDK 进行二次开发，面向灵心巧手 O6 机械手构建了一套桌面 GUI 控制与视觉交互系统。原始 SDK 已具备 CAN/RS485 通讯、关节位置下发和状态读取等基础能力，本项目在此基础上增加了 PyQt5 多页面主界面、连接状态显示、统一下发链路、CommandTrace 日志诊断和 Windows + PCAN_USBBUS1 启动适配。系统支持手动滑条控制、预设动作执行、设置页安全自检、摄像头视觉模仿、动作录制与 JSON 回放，以及人机猜拳小游戏。视觉模块通过 OpenCV 采集摄像头画面，使用 MediaPipe HandLandmarker 获取手部 21 点关键点，再映射为 O6 六维控制向量，实现人手作为主端、机械手作为从端的实时遥操作。系统强调安全控制，所有真实机械手下发都需要用户显式开启安全开关，并通过 pose 合法化、离线调试、日志追踪等机制降低误操作风险。

---

# 额外输出 B：500 字左右项目成果总结

本项目在原始 LinkerHand Python SDK 的基础上完成了面向展示和交互的系统级升级。原始 SDK 主要提供底层 API、CAN/RS485 通讯和示例脚本，适合开发者直接调用接口控制机械手。本次二次开发将其扩展为完整的 GUI 控制系统，形成了从硬件连接、状态显示、手动控制、视觉识别、动作映射、动作录制回放到人机小游戏的完整闭环。

在 GUI 方面，项目引入 `main.py`、`main_window.py` 和 `lhgui/` 模块化架构，将页面、核心业务、工具和组件拆分管理。主界面包含控制台、演示、录制、视觉模仿、猜拳、设置等页面，并通过左侧导航和连接状态栏组织操作流程。在通信链路方面，系统构建了 `GUI -> signal_bus -> ApiManager -> LinkerHandApi -> finger_move -> 硬件` 的统一下发路径，增加 CommandTrace 日志和 `sanitize_finger_pose` 合法化，解决了“界面显示已连接但动作不下发”时难以定位的问题。

在视觉交互方面，项目使用 OpenCV 与 MediaPipe Tasks HandLandmarker 实现手部关键点识别，并将人手姿态映射为 O6 的六维控制量。系统支持 EMA 平滑、deadband、防抖、max_step 限幅、单指校准、张开/握拳校准和匹配度评分，初步实现了基于摄像头的人手机械手主从遥操作。在动作复现方面，系统支持录制实时 pose 时间序列，保存为 JSON，并提供加载、暂停、继续、倍速、循环回放等能力。猜拳小游戏则将视觉识别和机械手随机出拳结合起来，形成更具展示性的交互应用。总体来看，本项目完成了从“SDK 示例”到“可汇报、可演示、可扩展的人机交互控制系统”的升级。

---

# 额外输出 C：创新点列表

- 基于摄像头和 MediaPipe 的机械手视觉遥操作。
- 人手 21 点关键点到 O6 六维控制向量的实时映射。
- proximal、distal、fused curl 融合的人手弯曲估计。
- 大拇指 `thumb_bend` 与 `thumb_swing` 分离建模和调试。
- 动作 pose 时间序列录制、JSON 保存和机械手回放。
- 回放与 live pose 互斥的安全下发机制。
- 人机猜拳小游戏，将视觉识别、随机出拳和机械手动作结合。
- CommandTrace 全链路日志诊断，覆盖 GUI、signal_bus、ApiManager 和 SDK 调用。
- 多模式控制：手动控制、预设动作、视觉模仿、录制回放、游戏交互。
- Windows + PCAN_USBBUS1 + Miniconda Python 3.9 的演示环境适配。

---

# 额外输出 D：答辩汇报用演讲稿提纲

1. 项目背景：介绍 LinkerHand O6 机械手和原始 Python SDK，说明原始 SDK 具备基础控制能力，但缺少完整展示和交互系统。
2. 开发目标：说明本项目目标是从基础 SDK 调用升级为 GUI 控制、视觉遥操作、录制回放和人机交互系统。
3. 系统架构：从硬件层、SDK 通讯层、GUI 控制层、视觉识别层、动作映射层、录制回放层、游戏交互层和日志诊断层展开。
4. GUI 控制系统：介绍 `run_gui.bat`、主窗口、左侧导航、连接状态、控制台、设置页和 SAFE_OPEN 自检。
5. 视觉遥操作：介绍摄像头采集、MediaPipe 21 点识别、O6 六维向量、thumb_bend/thumb_swing、平滑和安全开关。
6. 动作录制回放：介绍 pose 时间序列、JSON 保存加载、暂停继续、倍速循环、回放限步和 live 互斥。
7. 猜拳小游戏：介绍 3、2、1 倒计时、人类手势识别、机械手随机出拳、胜负判断和剪刀动作实物调参。
8. 安全与诊断：介绍 CommandTrace、VisionSync、VisionJoint、GestureRecord、RPSGame 和 `test_out.log`。
9. 技术难点：讲 Windows PCAN、PyQt5 线程、MediaPipe Tasks、O6 映射、大拇指横摆、已连接但不下发等问题和解决方案。
10. 成果总结：强调系统实现了可操作、可展示、可复现、可诊断的人机交互机械手控制系统。
11. 未来展望：custom11 外部输入、动作库、Web/API 远程遥操作、姿态评分和更精细的动作调参。

---

# 额外输出 E：项目演示流程脚本

1. 打开项目目录，关闭旧 GUI 进程，双击 `run_gui.bat` 启动系统。
2. 观察右上角连接状态，确认显示“已连接”，说明 O6 机械手和 `PCAN_USBBUS1` 已被识别。
3. 进入设置页，点击“下发链路自检：SAFE_OPEN”，观察机械手安全张开，并说明该动作验证了 GUI 到 SDK 到硬件的完整链路。
4. 进入控制台页面，拖动 O6 六维滑条，演示大拇指弯曲、大拇指横摆、食指、中指、无名指、小拇指控制。
5. 点击预设动作，例如张开、握拳、OK、点赞，展示基础动作库。
6. 进入视觉模仿页面，点击启动摄像头，展示画面、关键点、raw pose、ema pose 和匹配度。
7. 进行张开手和握拳校准，说明校准用于适配不同用户手型和摄像头距离。
8. 勾选“允许下发到机械手”，缓慢做张开、握拳、单指弯曲等动作，展示机械手实时模仿。
9. 点击“开始录制”，做一段手势动作；点击停止并保存 JSON。
10. 点击加载录制文件，演示回放、暂停、继续、倍速和循环。
11. 进入猜拳小游戏页面，勾选“启用机械手出拳”，点击开始，展示 3、2、1 倒计时。
12. 人类在摄像头前出石头/剪刀/布，机械手随机出拳，界面显示胜负结果和比分。
13. 打开 `test_out.log` 或展示日志区域，说明 CommandTrace 如何定位下发链路问题。
14. 总结：本系统把原始 SDK 扩展为具备视觉遥操作、动作复现、人机游戏和安全诊断能力的完整 GUI 控制平台。
