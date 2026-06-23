#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gesture_recognizer.py - custom_11 手势识别：rock/paper/scissors/unknown。

增加稳定帧机制（stable_frames），单帧 sample 测试不受影响（stable_frames=1）。
"""
from custom11_keypoints import validate_keypoints, virtual_palm_center, distance


class Custom11GestureRecognizer:
    # ---- 阈值（集中在类参数中） ----
    EXTEND_THRESHOLD = 1.55   # tip_to_palm / base_to_palm >= 此值 -> 伸直
    CURL_THRESHOLD = 1.05     # tip_to_palm / base_to_palm <= 此值 -> 弯曲
    CONFIDENCE_SCALE = 5.0    # 置信度缩放

    FINGER_ORDER = ["index", "middle", "ring", "little"]
    FINGER_INDICES = {
        "index":  {"base": 3, "tip": 4},
        "middle": {"base": 5, "tip": 6},
        "ring":   {"base": 7, "tip": 8},
        "little": {"base": 9, "tip": 10},
    }

    # ---- 构造 ----
    def __init__(self, extend_threshold=None, curl_threshold=None, stable_frames=1):
        self.extend_threshold = extend_threshold or self.EXTEND_THRESHOLD
        self.curl_threshold = curl_threshold or self.CURL_THRESHOLD
        self.stable_frames = max(1, int(stable_frames))

        # 稳定帧状态
        self._last_raw = None
        self._same_count = 0
        self._stable_gesture = "unknown"

    # ---- 主识别 ----
    def recognize(self, points):
        """返回完整识别结果。"""
        pts = validate_keypoints(points)
        palm = virtual_palm_center(pts)

        # 四指状态
        scores = {}
        states = {}
        for f in self.FINGER_ORDER:
            idx = self.FINGER_INDICES[f]
            b, t = pts[idx["base"]], pts[idx["tip"]]
            db = distance(b, palm)
            dt = distance(t, palm)
            bt = distance(b, t)
            ratio = dt / max(db, 1e-6)

            if ratio >= self.extend_threshold:
                state = "extended"
            elif ratio <= self.curl_threshold:
                state = "curled"
            else:
                state = "neutral"

            scores[f] = {
                "base_to_palm": round(db, 4),
                "tip_to_palm": round(dt, 4),
                "base_to_tip": round(bt, 4),
                "ratio": round(ratio, 4),
                "state": state,
                "curl_score": round(self._curl_score(ratio), 3),
            }
            states[f] = state

        # 大拇指状态（仅 debug）
        ts, tsc = self._thumb_state(pts, palm)

        # 分类
        raw_g, conf = self._classify(states, scores)

        # 稳定帧更新
        stable_g = self._update_stable(raw_g)

        debug = {
            "palm_center": (round(palm[0], 4), round(palm[1], 4)),
            "finger_details": scores,
            "thumb": {"state": ts, "score": round(tsc, 3)},
        }

        return {
            "raw_gesture": raw_g,
            "stable_gesture": stable_g,
            "gesture": stable_g if self.stable_frames > 1 else raw_g,
            "confidence": round(conf, 3),
            "finger_states": states,
            "debug": debug,
        }

    # ---- 内部 ----
    def _curl_score(self, ratio):
        """ratio -> 0(伸直)~1(弯曲) 线性映射。"""
        s = (1.8 - ratio) / (1.8 - 0.7)
        return max(0.0, min(1.0, s))

    def _thumb_state(self, pts, palm):
        r = distance(pts[2], palm) / max(distance(pts[0], palm), 1e-6)
        return ("extended", r) if r > 1.2 else ("curled", r)

    def _classify(self, states, scores):
        ext = {f: states[f] == "extended" for f in self.FINGER_ORDER}
        cur = {f: states[f] == "curled" for f in self.FINGER_ORDER}
        neu = {f: states[f] == "neutral" for f in self.FINGER_ORDER}

        # paper: 四指全部或大多伸直（允许 neutral）
        if (ext["index"] and ext["middle"] and
            (ext["ring"] or neu["ring"]) and (ext["little"] or neu["little"]) and
            sum(ext.values()) >= 3):
            return "paper", self._conf(scores, "extended")

        # rock: 四指全部或大多弯曲
        if (cur["index"] and cur["middle"] and
            (cur["ring"] or neu["ring"]) and (cur["little"] or neu["little"]) and
            sum(cur.values()) >= 3):
            return "rock", self._conf(scores, "curled")

        # scissors: index+middle 伸直，ring+little 弯曲
        if (ext["index"] and ext["middle"] and cur["ring"] and cur["little"]):
            return "scissors", self._conf(scores, "mixed")

        return "unknown", 0.0

    def _conf(self, scores, target):
        margins = []
        for f, sc in scores.items():
            r = sc["ratio"]
            if target == "extended":
                m = (r - self.extend_threshold) * self.CONFIDENCE_SCALE
            elif target == "curled":
                m = (self.curl_threshold - r) * self.CONFIDENCE_SCALE
            else:  # mixed
                if f in ("index", "middle"):
                    m = (r - self.extend_threshold) * self.CONFIDENCE_SCALE
                else:
                    m = (self.curl_threshold - r) * self.CONFIDENCE_SCALE
            margins.append(max(0.0, min(1.0, m)))
        return sum(margins) / len(margins) if margins else 0.0

    def _update_stable(self, raw_gesture):
        if raw_gesture == self._last_raw:
            self._same_count += 1
        else:
            self._same_count = 1
            self._last_raw = raw_gesture
        if self._same_count >= self.stable_frames:
            self._stable_gesture = raw_gesture
        return self._stable_gesture

    def reset(self):
        self._last_raw = None
        self._same_count = 0
        self._stable_gesture = "unknown"
