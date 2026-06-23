#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom11_stream_reader.py

线程安全的 custom_11 最新帧缓存，增加统计信息。

不做硬件控制，不依赖 GUI。
"""
import time
import threading

from custom11_keypoints import validate_keypoints


class Custom11StreamReader:
    def __init__(self, max_age_sec=1.0):
        self._lock = threading.Lock()
        self._max_age_sec = max_age_sec
        self._latest_raw = None
        self._latest_timestamp = 0.0
        self._total_frames = 0
        self._valid_frames = 0
        self._invalid_frames = 0
        self._last_error = None
        self._last_update_time = 0.0

    # ------------------------------------------------------------------
    # 更新帧
    # ------------------------------------------------------------------
    def update_frame(self, payload):
        with self._lock:
            self._total_frames += 1
            now = time.time()
            base = {"ok": False, "timestamp": now, "age_sec": 0.0, "keypoints_count": 0, "message": ""}

            if not isinstance(payload, dict):
                self._invalid_frames += 1
                self._last_error = "payload must be a dict"
                base["message"] = self._last_error
                return base

            kps = payload.get("keypoints")
            if kps is None:
                self._invalid_frames += 1
                self._last_error = "missing 'keypoints' field"
                base["message"] = self._last_error
                return base
            if not isinstance(kps, list):
                self._invalid_frames += 1
                self._last_error = "'keypoints' must be a list"
                base["message"] = self._last_error
                return base
            if len(kps) != 11:
                self._invalid_frames += 1
                self._last_error = f"keypoints must have 11 points, got {len(kps)}"
                base["message"] = self._last_error
                return base

            try:
                validate_keypoints(kps)
            except Exception as exc:
                self._invalid_frames += 1
                self._last_error = f"keypoint validation failed: {exc}"
                base["message"] = self._last_error
                return base

            # 通过
            ts = payload.get("timestamp", now)
            if not isinstance(ts, (int, float)):
                ts = now
            self._latest_raw = {
                "source": payload.get("source", "unknown"),
                "timestamp": ts,
                "hand": payload.get("hand", "left"),
                "keypoints": kps,
            }
            self._latest_timestamp = now
            self._valid_frames += 1
            self._last_update_time = now
            self._last_error = None

            return {
                "ok": True,
                "message": "frame updated",
                "timestamp": ts,
                "age_sec": round(now - self._latest_timestamp, 4),
                "keypoints_count": 11,
            }

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get_latest_frame(self, max_age_sec=None):
        age = max_age_sec if max_age_sec is not None else self._max_age_sec
        with self._lock:
            if self._latest_raw is None:
                return None
            if time.time() - self._latest_timestamp > age:
                return None
            return dict(self._latest_raw)

    def has_fresh_frame(self, max_age_sec=None):
        return self.get_latest_frame(max_age_sec) is not None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def get_status(self):
        with self._lock:
            has = self._latest_raw is not None
            age = time.time() - self._latest_timestamp if has else -1
            fresh = has and (age <= self._max_age_sec) if has else False
            return {
                "has_frame": has,
                "fresh": fresh,
                "age_sec": round(age, 4) if has else None,
                "total_frames": self._total_frames,
                "valid_frames": self._valid_frames,
                "invalid_frames": self._invalid_frames,
                "last_error": self._last_error,
                "last_update_time": round(self._last_update_time, 3) if self._last_update_time else None,
                "max_age_sec": self._max_age_sec,
            }
