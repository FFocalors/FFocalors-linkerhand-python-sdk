#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom11_stream_reader.py

线程安全的 custom_11 最新帧缓存。

保存最近一帧；提供 get_latest_frame(max_age_sec) 按时间新鲜度返回帧。
不做硬件控制，不依赖 GUI，不修改任何 O6 参数。
"""
import time
import threading

from custom11_keypoints import validate_keypoints


class Custom11StreamReader:
    """
    线程安全的最新帧缓存。

    用法：
        reader = Custom11StreamReader()
        result = reader.update_frame(payload)
        frame = reader.get_latest_frame(max_age_sec=1.0)
        print(reader.has_fresh_frame(1.0))
    """

    def __init__(self, max_age_sec=1.0):
        self._lock = threading.Lock()
        self._max_age_sec = max_age_sec
        self._latest_raw = None       # 原始 payload（已校验通过）
        self._latest_timestamp = 0.0  # 帧到达时间（time.time()）
        self._total_frames = 0
        self._error_frames = 0

    # ------------------------------------------------------------------
    # 更新帧
    # ------------------------------------------------------------------
    def update_frame(self, payload):
        """
        校验并更新最新一帧。

        Args:
            payload: dict，包含 keypoints（必须）、source（可选）、
                     timestamp（可选）、hand（可选）。

        Returns:
            dict: {'ok': bool, 'message': str, 'timestamp': float,
                   'age_sec': float, 'keypoints_count': int}
        """
        with self._lock:
            self._total_frames += 1
            now = time.time()

            # 基本校验
            if not isinstance(payload, dict):
                self._error_frames += 1
                return {"ok": False, "message": "payload must be a dict",
                        "timestamp": now, "age_sec": 0.0, "keypoints_count": 0}

            kps = payload.get("keypoints")
            if kps is None:
                self._error_frames += 1
                return {"ok": False, "message": "missing 'keypoints' field",
                        "timestamp": now, "age_sec": 0.0, "keypoints_count": 0}

            if not isinstance(kps, list):
                self._error_frames += 1
                return {"ok": False, "message": "'keypoints' must be a list",
                        "timestamp": now, "age_sec": 0.0, "keypoints_count": 0}

            if len(kps) != 11:
                self._error_frames += 1
                return {"ok": False, "message":
                        f"'keypoints' must have exactly 11 points, got {len(kps)}",
                        "timestamp": now, "age_sec": 0.0, "keypoints_count": len(kps)}

            # 校验每个点至少包含 x 和 y
            try:
                validate_keypoints(kps)
            except Exception as exc:
                self._error_frames += 1
                return {"ok": False, "message": f"keypoint validation failed: {exc}",
                        "timestamp": now, "age_sec": 0.0, "keypoints_count": len(kps)}

            # 通过校验：存储
            timestamp = payload.get("timestamp", now)
            if not isinstance(timestamp, (int, float)):
                timestamp = now
            self._latest_raw = {
                "source": payload.get("source", "unknown"),
                "timestamp": timestamp,
                "hand": payload.get("hand", "left"),
                "keypoints": kps,
            }
            self._latest_timestamp = now

            return {
                "ok": True,
                "message": "frame updated",
                "timestamp": timestamp,
                "age_sec": round(now - self._latest_timestamp, 4),
                "keypoints_count": 11,
            }

    # ------------------------------------------------------------------
    # 读取最新帧
    # ------------------------------------------------------------------
    def get_latest_frame(self, max_age_sec=None):
        """
        返回最新帧，如果过期则返回 None。

        Returns:
            dict | None: 最新帧 payload，或 None（无帧/过期）。
        """
        age = max_age_sec if max_age_sec is not None else self._max_age_sec
        with self._lock:
            if self._latest_raw is None:
                return None
            now = time.time()
            if now - self._latest_timestamp > age:
                return None
            return dict(self._latest_raw)

    def has_fresh_frame(self, max_age_sec=None):
        """是否有新鲜帧。"""
        return self.get_latest_frame(max_age_sec) is not None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def get_status(self):
        """返回 reader 状态摘要。"""
        with self._lock:
            has = self._latest_raw is not None
            age = time.time() - self._latest_timestamp if has else -1
            return {
                "has_frame": has,
                "age_sec": round(age, 4) if has else None,
                "total_frames": self._total_frames,
                "error_frames": self._error_frames,
                "max_age_sec": self._max_age_sec,
            }
