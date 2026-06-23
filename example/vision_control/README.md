# 视觉控制模块（Vision Control）

本模块只在 `example/vision_control/` 下开发，**不修改 SDK、GUI、O6 参数文件**。

---

## 1. 模块目标

通过 `custom_11` 手部关键点输入，实现两种控制模式：

- **pose 模式**（默认）：连续姿态匹配，根据每根手指弯曲程度实时映射 O6 pose
- **gesture 模式**：手势识别 → 预设动作

默认 dry-run，可选 `--enable-hardware` 控制真实机械手。

## 2. O6 控制向量（固定 6 维）

```text
[thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]
```

| dim | 名称 | 中文 | 说明 |
|-----|------|------|------|
| 0 | thumb_bend | 大拇指弯曲 | |
| 1 | thumb_swing | 大拇指横摆 | **不是手腕！** |
| 2 | index_bend | 食指弯曲 | |
| 3 | middle_bend | 中指弯曲 | |
| 4 | ring_bend | 无名指弯曲 | |
| 5 | little_bend | 小拇指弯曲 | |

O6 参数只读复用 `example/gui_control/lhgui/config/constants.py`。

## 3. custom_11 输入格式

11 点固定顺序（无 wrist）：thumb_base[0], thumb_mid[1], thumb_tip[2], index_base[3], index_tip[4], middle_base[5], middle_tip[6], ring_base[7], ring_tip[8], little_base[9], little_tip[10]。

每个点格式：`{"x":float,"y":float,"z"?:float}`, `[x,y]`, `(x,y)` 等。

## 4. 文件结构

```text
example/vision_control/
├── o6_gui_params_adapter.py    # 只读复用 GUI O6 参数
├── o6_hardware_adapter.py      # 默认 dry-run，可选硬件
├── custom11_keypoints.py       # keypoints 格式/校验/Schema
├── gesture_recognizer.py     # 手势识别（+稳定帧）
├── hand_pose_mapper.py       # 11点 → 6维 O6 pose 连续映射
├── custom11_stream_reader.py # 线程安全帧缓存 + 统计
├── custom11_server.py        # HTTP server（延迟信息）
├── stream_demo.py            # 模拟前端（fps/trajectory）
├── sample_keypoints_11.json  # 离线样例
├── rps_game.py               # 视觉猜拳（随机）
├── left_hand_teleop.py       # 实时同像动态控制
├── hardware_smoke_test.py    # 单动作冒烟测试
└── README.md
```

## 5. 石头剪刀布（rps_game.py）

- **robot-policy 默认 `random`**：机器人公平随机出拳，不根据用户当前手势作弊选择克制动作
- 没有 counter 策略，排除作弊可能
- `scissors` 仍临时映射为 GUI 预设动作"贰"
- 支持 `--input-mode stream`（倒计时后读取实时帧）、`--countdown N`、`--print-json`

```bash
python example/vision_control/rps_game.py --dry-run --rounds 3
python example/vision_control/rps_game.py --dry-run --input-mode stream --rounds 5 --countdown 3
```

## 6. 实时同像动态控制（left_hand_teleop.py）

**默认 `pose` 模式**：不是只识别 rock/paper/scissors，而是根据用户左手 11 点连续计算五指弯曲程度和大拇指横摆，再映射为 O6 六维控制量，实现同像、低延迟的动态姿态跟随。

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--control-mode` | pose | pose=连续映射, gesture=手势识别 |
| `--mirror-mode` | same | 同像控制（不翻转） |
| `--preset` | balanced_realtime | 实时预设 |
| `--dry-run` | True | 默认 dry-run |
| `--enable-hardware` | False | 显式启用硬件 |

### 三种实时预设

| 预设 | smoothing_alpha | max_delta | deadzone | 适用场景 |
|------|-----------------|-----------|----------|----------|
| `fast_realtime` | 0.45 | 10 | 1 | 延迟敏感 |
| `balanced_realtime` | 0.35 | 8 | 2 | 通用推荐 |
| `stable_precise` | 0.25 | 5 | 3 | 抖动优化 |

**推荐实机参数**：先从 `balanced_realtime` 开始；延迟高用 `fast_realtime`；抖动大用 `stable_precise`。

### 用法

```bash
# sample 模式 + explain
python example/vision_control/left_hand_teleop.py --dry-run --preset balanced_realtime --explain

# stream 模式 + 延迟/FPS log
python example/vision_control/left_hand_teleop.py --dry-run --input-mode stream \
    --preset balanced_realtime --latency-log --fps-log --max-frames 30

# 硬件模式
python example/vision_control/left_hand_teleop.py --enable-hardware --input-mode stream \
    --preset balanced_realtime --max-frames 30
```

## 7. stream 模式三终端

**终端1**：`python example/vision_control/custom11_server.py --port 8765`

**终端2**（模拟前端 + 连续过渡）：
```bash
python example/vision_control/stream_demo.py --fps 15 --trajectory smooth --loop
```

**终端3**（消费端）：
```bash
python example/vision_control/left_hand_teleop.py --dry-run --input-mode stream \
    --preset balanced_realtime --latency-log --fps-log --max-frames 30
```

## 8. custom11_server 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/status` | 统计（含 receive_fps_estimate） |
| GET | `/schema` | custom_11 格式说明 |
| GET | `/latest[?max_age_sec=N]` | 最新帧 + latency_sec + server_receive_time |
| POST | `/keypoints` | 接收关键点 |
| OPTIONS | `*` | CORS |

## 9. 手势映射

| 视觉手势 | O6 动作 |
|----------|---------|
| rock | 握拳 |
| paper | 张开 |
| scissors | 贰（临时映射） |
| pinch / ok | OK |
| thumb_up | 点赞 |

## 10. 硬件冒烟测试

```bash
python example/vision_control/hardware_smoke_test.py --list
python example/vision_control/hardware_smoke_test.py --action 张开 --dry-run
python example/vision_control/hardware_smoke_test.py --action 张开 --enable-hardware
```

## 11. 部署到另一台电脑

1. 同步代码 + `pip install pyyaml opencv-python`
2. dry-run 验证：`python left_hand_teleop.py --dry-run --preset balanced_realtime`
3. 启动 server + stream_demo + 客户端测试 stream 链路
4. 硬件冒烟：`python hardware_smoke_test.py --action 张开 --enable-hardware`
5. 实时控制：`python left_hand_teleop.py --enable-hardware --input-mode stream --preset balanced_realtime`

## 12. 安全注意事项

- **默认 dry-run**，只有 `--enable-hardware` 才控制机械手
- 无 fresh frame 时不下发 pose
- **不建议与原 GUI 同时运行**（抢 CAN 总线）
- 硬件模式前先 `hardware_smoke_test`
- 不设置 speed/torque，不读取触觉
- `thumb_swing` 是大拇指横摆，不是手腕

## 13. 故障排查

| 问题 | 解决 |
|------|------|
| `No module named yaml` | `pip install pyyaml` |
| `No module named can` | `pip install python-can` |
| CAN 设备找不到 | 检查 setting.yaml CAN 配置 |
| 没有 fresh frame | 确保 server + demo 都在运行 |
| 中文乱码但 pose 正确 | 不影响功能，pose 数值正确 |
| GUI 与视觉控制抢控制 | 关闭 GUI 再运行 |
| scissors 临时「贰」 | 设计行为，非 bug |
