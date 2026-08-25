# LinkerHand GUI 架构约定

本文记录当前控制台的运行时边界。后续功能应遵守这些边界，以保持界面流畅、硬件安全和模块可替换。

## 1. 总体数据流

```text
Qt GUI 主线程
  ├─ QWidget / 页面切换 / 用户输入
  ├─ ApiManager：校验请求、维护缓存、提交有界命令
  └─ DataSource：仅负责启停遥测
             │
             ▼
       DeviceIoWorker(QObject)
             │  所属独立 QThread
             ▼
       LinkerHandApi / CAN / RS485
```

`ApiManager` 在 GUI 线程创建 `DeviceIoWorker`，随后将 worker 移入独立 `QThread`。真实 `LinkerHandApi` 只能由 worker 创建、使用和销毁；GUI 线程不得读取或保存真实 API 对象。旧代码访问 `ApiManager.api` 时得到的只是固件/序列号元数据 proxy。

`DataSource` 是兼容层。它的 `start()`/`stop()` 只调用 `ApiManager.start_polling()`/`stop_polling()`，不创建自己的硬件定时器，也不直接停止 worker 所属的 `QTimer`。

## 2. 命令与安全边界

worker 内部硬件读写始终串行：一次 API 调用完成后才会处理下一项命令或下一次轮询。

命令分为三层：

1. `shutdown` 具有最高优先级；连接、重连、断开等生命周期命令单独排队并去重，不能被普通参数命令淘汰。
2. 速度、扭矩、临时扭矩、恢复扭矩各有一个参数槽位，重复提交采用 latest-wins，参数邮箱最多 4 项。
3. `finger_move` 只保留一个最新姿态，硬件下发间隔不小于 50 ms（约 20 Hz）；拖动过程中的中间姿态可以丢弃，最终姿态必须保留。

安全/生命周期命令不得进入 finger_move 队列，也不得依赖 GUI 线程的同步等待。关闭时 GUI 提交 shutdown，worker 在线程内清理 API、停止自己的定时器并通知完成，随后 GUI 才停止 QThread。

## 3. 遥测与快照

`DeviceIoWorker` 使用 deadline 风格的单一 service timer，禁止重入和堆积旧读请求：

| 数据 | 频率 | 上行方式 |
| --- | ---: | --- |
| state | 约 20 Hz | 与 current/speed 合并为一个快照 |
| current | 约 10 Hz | 写入最新快照 |
| speed | 约 1 Hz | 写入最新快照 |
| 触觉矩阵 | 约 2 Hz | 独立 `matrix_ready`/`matrix_updated` |

`ApiManager` 只缓存最新 `state/current/speed/matrix`，再通过 `snapshot_ready`、`matrix_ready` 和现有信号总线上传。UI 不应为每个硬件读请求创建任务或保存无限历史。

## 4. 采样与渲染解耦

- `WaveformPanel` 使用 NumPy 固定环形缓冲，最多保存 200 个采样点。数据回调只写入缓冲，不操作曲线；可见时由 75 ms 定时器统一更新，最高约 13 FPS；隐藏或折叠时停止渲染。
- `HandPoseView` 只保留最新目标姿态，OpenGL 动画定时器约 30 FPS。高亮使用一个可重启定时器；页面隐藏时停止动画和高亮。
- 采样频率由设备 worker 决定，绘制频率由控件自己的渲染定时器决定。新增实时视图必须沿用“最新值 + 固定容量 + 独立帧率”的模式。

## 5. 日志与页面生命周期

`command_trace()` 只入后台 writer 队列，不在调用线程打开或写文件。writer 队列上限为 4096，单批最多 64 行；普通噪声可丢弃，连接、错误、超时、断开等重要消息优先保留。设置 `LINKERHAND_TRACE=all` 才恢复高频诊断追踪。

`LogPage` 的 Python 日志记录和 Qt 文档均限制为 2000 条。可见页面以 50 ms 批量增量刷新，禁止每条消息整体重建 HTML；隐藏页面不触发绘制。

`MainWindow` 首屏只构建 Console、Log、Settings、Demo。Vision/Game 模块在后台线程预热导入，但后台线程不得创建 QWidget；用户首次访问时在 GUI 线程构建页面，构建失败显示 placeholder，已构建页面缓存复用。页面切换统一调用 `activate()`/`deactivate()`：Vision/Game 的摄像头、录制、回放和定时任务必须在 deactivate 时停止。

主题切换使用一次全局样式表替换和已登记 inline stylesheet 注册表，不再每次遍历所有 QWidget 或强制 `processEvents()`；新增控件应避免高成本逐控件主题转换。

## 6. 扩展功能的禁止事项

- 禁止在 QWidget、页面、`ApiManager` 的 GUI 方法中直接调用 `LinkerHandApi`、CAN/RS485、摄像头或阻塞式文件 I/O。
- 禁止用无上限 `queue.Queue`、列表或 Qt 事件逐帧承载高频输入；控制值使用 latest-wins，安全命令使用独立优先级通道。
- 禁止在遥测回调中调用 Matplotlib/Qt 图表绘制、整页 `setHtml()` 或全量重建历史数据。
- 禁止为同一数据流增加重复 signal 订阅；新增页面必须有明确的 activate/deactivate 资源边界。
- 禁止在后台预热线程创建或操作 QWidget；页面模块导入和 QWidget 构建必须分开。
- 新增硬件命令必须说明优先级、队列上限、关闭行为和异常恢复方式，并补充无硬件线程归属测试。

## 7. 核心回归与性能指标

提交前至少运行：

```powershell
python -m unittest tests.test_device_io_worker tests.test_adaptive_grasp_controller tests.test_joint_signal_analyzer test_preset_features test_pure_logic
python -m unittest tests.test_render_pipeline tests.test_ui_lazy_pages
git diff --check
```

核心回归必须覆盖连接/离线/重连/断开、单关节拖动最终值、速度/扭矩、预设动作、急停/自适应抓取、遥测曲线、触觉矩阵、Vision/Game 启停、日志上限和主题切换。

验收目标：连续遥测时事件循环 P95 小于 20 ms、P99 小于 50 ms；页面切换小于 100 ms；主题切换小于 150 ms；finger_move 队列长度不随拖动时长增长；关闭和急停不被普通控制值或日志洪峰挤掉；在模拟高频遥测下环形缓冲、日志文档和命令队列保持固定上限。
