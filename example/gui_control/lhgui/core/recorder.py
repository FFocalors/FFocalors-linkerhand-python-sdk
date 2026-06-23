#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动作录制与回放。

录制：订阅 finger_move_requested 信号，记录每一帧 (相对时间戳, pose)。
回放：按原始时间间隔（可设倍速）依次下发 finger_move_requested。
持久化：录制结果以 JSON 存到 recordings/ 目录，不污染原有 *_positions.yaml。

状态机：idle <-> recording / playing。
"""
import os
import json
import time
from typing import List, Dict, Optional

from PyQt5.QtCore import QObject, QTimer

from lhgui.utils.signal_bus import signal_bus


RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recordings")


class Recorder(QObject):
    def __init__(self):
        super().__init__()
        self._frames: List[Dict] = []          # [{"t": ms, "pose": [...]}]
        self._start_wall: float = 0.0
        self._recording = False
        self._playing = False
        self._play_frames: List[Dict] = []
        self._play_index = 0
        self._play_speed = 1.0
        self._play_timer: QTimer = None
        self._bound_joint_len: int = 0

        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        signal_bus.finger_move_requested.connect(self._on_finger_move)

    # —— 录制 ——
    def start_recording(self, joint_len: int):
        if self._playing:
            signal_bus.connection_message.emit("warning", "回放进行中，无法录制")
            return
        self._bound_joint_len = joint_len
        self._frames = []
        self._start_wall = time.monotonic()
        self._recording = True
        signal_bus.record_started.emit()
        signal_bus.connection_message.emit("info", "开始录制")

    def _on_finger_move(self, pose: List[int]):
        if not self._recording:
            return
        t_ms = int((time.monotonic() - self._start_wall) * 1000)
        self._frames.append({"t": t_ms, "pose": [int(v) for v in pose]})

    def stop_and_save(self, name: str) -> Optional[str]:
        if not self._recording:
            return None
        self._recording = False
        signal_bus.record_stopped.emit(name)
        name = (name or "").strip() or f"record_{int(time.time())}"
        if not self._frames:
            signal_bus.connection_message.emit("warning", "录制为空，未保存")
            return None
        path = os.path.join(RECORDINGS_DIR, f"{_safe(name)}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": name, "frames": self._frames}, f, ensure_ascii=False, indent=2)
        signal_bus.connection_message.emit("success", f"录制已保存：{name}")
        return path

    def discard(self):
        if not self._recording:
            return
        self._recording = False
        self._frames = []
        signal_bus.record_stopped.emit("")
        signal_bus.connection_message.emit("info", "已放弃录制")

    @property
    def recording(self) -> bool:
        return self._recording

    # —— 回放 ——
    def play(self, name: str, speed: float = 1.0):
        if self._recording:
            signal_bus.connection_message.emit("warning", "录制进行中，无法回放")
            return
        path = os.path.join(RECORDINGS_DIR, f"{_safe(name)}.json")
        if not os.path.exists(path):
            signal_bus.connection_message.emit("error", f"未找到录制：{name}")
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        frames = data.get("frames", [])
        if not frames:
            signal_bus.connection_message.emit("warning", "录制内容为空")
            return
        self._play_frames = frames
        self._play_index = 0
        self._play_speed = max(0.1, float(speed))
        self._playing = True
        signal_bus.playback_started.emit()
        signal_bus.connection_message.emit("info", f"开始回放：{name}")
        self._play_timer = QTimer()
        self._play_timer.setSingleShot(True)
        self._play_timer.timeout.connect(self._tick_play)
        self._tick_play()

    def _tick_play(self):
        if not self._playing or self._play_index >= len(self._play_frames):
            self.stop_playback()
            return
        frame = self._play_frames[self._play_index]
        signal_bus.finger_move_requested.emit([int(v) for v in frame["pose"]])
        signal_bus.playback_progress.emit(self._play_index + 1, len(self._play_frames))
        self._play_index += 1
        if self._play_index < len(self._play_frames):
            dt = self._play_frames[self._play_index]["t"] - frame["t"]
            dt = max(1, int(dt / self._play_speed))
        else:
            dt = 0
        if dt > 0:
            self._play_timer.start(dt)
        else:
            self.stop_playback()

    def stop_playback(self):
        if not self._playing and self._play_timer is None:
            return
        self._playing = False
        if self._play_timer:
            self._play_timer.stop()
            self._play_timer = None
        self._play_frames = []
        self._play_index = 0
        signal_bus.playback_stopped.emit()
        signal_bus.connection_message.emit("info", "回放已停止")

    @property
    def playing(self) -> bool:
        return self._playing

    # —— 录制列表 ——
    @staticmethod
    def list_recordings() -> List[str]:
        if not os.path.isdir(RECORDINGS_DIR):
            return []
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(RECORDINGS_DIR)
            if f.endswith(".json")
        )


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
