# 视觉控制模块（Vision Control）

本模块只在 `example/vision_control/` 下开发，**不修改 SDK、GUI、O6 参数文件**。

## 1. 设计原则

- **只读复用 O6 参数**：来源 `example/gui_control/lhgui/config/constants.py` 中的 `_HAND_CONFIGS["O6"]`
- **默认 dry-run**：所有脚本默认只打印，不控制机械手
- **显式硬件**：只有 `--enable-hardware` 才调用 `LinkerHandApi.finger_move(pose)`
- **不修改受保护文件**

## 2. O6 控制向量（固定 6 维）

```text
[thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]
```

- 索引 1 是 `thumb_swing`（大拇指横摆），**不是手腕**

## 3. 文件结构

```text
example/vision_control/
├── o6_gui_params_adapter.py    # 只读复用 GUI O6 参数
├── o6_hardware_adapter.py      # 默认 dry-run，可选硬件
├── custom11_keypoints.py       # custom_11 关键点格式
├── gesture_recognizer.py     # 手势识别
├── hand_pose_mapper.py       # 11 点 -> 6 维 O6 pose
├── custom11_stream_reader.py # 线程安全最新帧缓存
├── custom11_server.py        # HTTP server：接收/返回关键点
├── stream_demo.py            # 模拟前端发送样例
├── sample_keypoints_11.json  # 离线样例
├── rps_game.py               # 视觉猜拳
├── left_hand_teleop.py       # 左手动态控制
├── README.md
└── requirements_vision.txt
```

## 4. 输入模式

### 4.1 sample 模式（默认）

从 `sample_keypoints_11.json` 读取离线样例。

### 4.2 stream 模式

从 `custom11_server.py` 的 `GET /latest` 获取实时帧。

## 5. custom11_server.py 接口

启动：

```bash
python example/vision_control/custom11_server.py --host 127.0.0.1 --port 8765
```

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回 `{"ok":true,"service":"custom11_server"}` |
| POST | `/keypoints` | 接收 custom_11 payload（JSON body） |
| GET | `/latest` | 返回最新一帧，格式 `{"ok":true,"fresh":true,"frame":{...}}` |

### 5.1 POST /keypoints 格式

```json
{
  "source": "frontend",
  "timestamp": 1234567890,
  "hand": "left",
  "keypoints": [
    {"x": 0.1, "y": 0.2}, ...  // 共 11 个点
  ]
}
```

keypoints 必须正好 11 个点，每个点至少包含 x、y。

### 5.2 custom_11 点序

| idx | name |
|-----|------|
| 0 | thumb_base |
| 1 | thumb_mid_or_swing_ref |
| 2 | thumb_tip |
| 3 | index_base |
| 4 | index_tip |
| 5 | middle_base |
| 6 | middle_tip |
| 7 | ring_base |
| 8 | ring_tip |
| 9 | little_base |
| 10 | little_tip |

无 wrist 点。掌心参考用 `virtual_palm_center`（局部计算，非 O6 控制量）。

## 6. 使用示例

### 6.1 stream_demo 模拟前端

```bash
python example/vision_control/stream_demo.py \
    --url http://127.0.0.1:8765/keypoints \
    --interval 1.0
```

### 6.2 left_hand_teleop stream 模式

```bash
python example/vision_control/left_hand_teleop.py \
    --dry-run \
    --input-mode stream \
    --stream-url http://127.0.0.1:8765/latest
```

### 6.3 rps_game stream 模式

```bash
python example/vision_control/rps_game.py \
    --dry-run \
    --input-mode stream \
    --stream-url http://127.0.0.1:8765/latest \
    --rounds 3
```

### 6.4 完整测试流程（三个终端）

终端1：
```bash
python example/vision_control/custom11_server.py --host 127.0.0.1 --port 8765
```

终端2：
```bash
python example/vision_control/stream_demo.py --interval 1.0 --loop
```

终端3：
```bash
python example/vision_control/left_hand_teleop.py --dry-run --input-mode stream
# 或者
python example/vision_control/rps_game.py --dry-run --input-mode stream --rounds 3
```

## 7. 手势映射

| 视觉手势 | O6 动作 |
|----------|---------|
| rock | 握拳 |
| paper | 张开 |
| scissors | 贰（临时映射） |
| pinch / ok | OK |
| thumb_up | 点赞 |

## 8. 安全提示

- **默认 dry-run**
- 只有 `--enable-hardware` 才控制机械手
- 无 fresh frame 时不下发 pose
- 不建议与原 GUI 同时运行
- 不设置速度/力矩，不读取触觉

## 9. 接入真实 11 点实时源

1. 实时源按 custom_11 格式输出 11 个 `{"x":float,"y":float,"z":float}` 点
2. 通过 `POST /keypoints` 发送到 `custom11_server.py`
3. 复用现有 recognizer / mapper / hardware adapter
4. 如需摄像头模型，在 requirements_vision.txt 添加依赖，保证默认 dry-run 仍可运行
