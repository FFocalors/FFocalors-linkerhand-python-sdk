#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recorder 适配层。

在不动 `recorder.py` 的前提下，为 UI 提供时长、删除等辅助能力。
"""
import json
import os
import time
from typing import List, Optional

from lhgui.core.recorder import Recorder, RECORDINGS_DIR


class RecorderAdapter:
    def __init__(self, recorder: Recorder):
        self._recorder = recorder

    @property
    def recording(self) -> bool:
        return self._recorder.recording

    @property
    def playing(self) -> bool:
        return self._recorder.playing

    def list(self) -> List[dict]:
        """返回录制元数据列表，含计算出的时长。"""
        out = []
        if not os.path.isdir(RECORDINGS_DIR):
            return out
        for fname in sorted(os.listdir(RECORDINGS_DIR)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(RECORDINGS_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                frames = data.get("frames", [])
                duration_ms = 0
                if len(frames) >= 2:
                    duration_ms = frames[-1].get("t", 0) - frames[0].get("t", 0)
                out.append({
                    "name": data.get("name", os.path.splitext(fname)[0]),
                    "file": fname,
                    "frames": len(frames),
                    "duration_ms": duration_ms,
                    "mtime": os.path.getmtime(path),
                })
            except Exception:
                continue
        return out

    def duration_text(self, name: str) -> str:
        for item in self.list():
            if item["name"] == name or item["file"] == name:
                ms = item["duration_ms"]
                return f"{ms // 1000}.{ms % 1000 // 100:01d}s"
        return "0.0s"

    def delete(self, name: str) -> bool:
        """删除录制文件。"""
        path = os.path.join(RECORDINGS_DIR, name if name.endswith(".json") else f"{name}.json")
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            return False

    # 透传已有方法
    def start_recording(self, joint_len: int):
        return self._recorder.start_recording(joint_len)

    def stop_and_save(self, name: str) -> Optional[str]:
        return self._recorder.stop_and_save(name)

    def discard(self):
        return self._recorder.discard()

    def play(self, name: str, speed: float = 1.0):
        return self._recorder.play(name, speed)

    def stop_playback(self):
        return self._recorder.stop_playback()
