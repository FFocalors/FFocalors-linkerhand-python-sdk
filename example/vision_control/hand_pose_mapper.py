#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hand_pose_mapper.py - custom_11 -> O6 6-dim pose 动态映射器（连续姿态版）。

O6 输出固定 6 维: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]
第二维 thumb_swing 是大拇指横摆，不是手腕。

特性:
- 连续 curl score 0~1，不再只识别离散手势
- 多特征融合（base-tip距离、tip-to-palm、bbox归一化）
- thumb_swing 独立优化
- 关键点异常保护（NaN、重合、bbox过小）
- 三种实时预设：fast_realtime / balanced_realtime / stable_precise
- explain_mapping 输出完整映射链
"""
import math
import time
from o6_gui_params_adapter import O6GuiParamsAdapter
from custom11_keypoints import (validate_keypoints, virtual_palm_center,
                                distance, clamp, normalize_keypoints, compute_bbox)

# ---- 预设参数 ----
PRESETS = {
    "fast_realtime": {
        "smoothing_alpha": 0.45, "max_delta": 10, "min_interval": 0.05, "deadzone": 1,
    },
    "balanced_realtime": {
        "smoothing_alpha": 0.35, "max_delta": 8, "min_interval": 0.08, "deadzone": 2,
    },
    "stable_precise": {
        "smoothing_alpha": 0.25, "max_delta": 5, "min_interval": 0.12, "deadzone": 3,
    },
}


class Custom11ToO6PoseMapper:
    # 内部阈值（受控于异常保护）
    MIN_BBOX_AREA = 1e-8
    MAX_DUPLICATE_RATIO = 0.6       # 最多允许 60% 点重合
    FINGER_LENGTH_RATIO_MIN = 0.1   # 手指长度/手掌尺度最小比例
    FINGER_LENGTH_RATIO_MAX = 5.0   # 手指长度/手掌尺度最大比例

    def __init__(self, smoothing_alpha=0.35, max_delta=8, min_interval=0.08, deadzone=2.0,
                 mirror_mode="same", preset=None):
        if preset and preset in PRESETS:
            p = PRESETS[preset]
            smoothing_alpha, max_delta, min_interval, deadzone = (
                p["smoothing_alpha"], p["max_delta"], p["min_interval"], p["deadzone"])

        self.gui = O6GuiParamsAdapter()
        self.open_pose = self.gui.get_pose_by_action("张开")
        self.fist_pose = self.gui.get_pose_by_action("握拳")
        self.ok_pose = self.gui.get_pose_by_action("OK")
        self.two_pose = self.gui.get_pose_by_action("贰")

        self.smoothing_alpha = clamp(smoothing_alpha, 0.0, 1.0)
        self.max_delta = max_delta
        self.min_interval = min_interval
        self.deadzone = deadzone
        self.mirror_mode = mirror_mode  # 固定 same，不 flip_x

        self._smoothed_pose = None
        self._last_time = 0.0
        self._last_pose = None
        self._last_debug = None
        self._frame_count = 0

    # ================================================================
    # 主映射
    # ================================================================
    def map_keypoints(self, points):
        self._frame_count += 1
        now = time.time()

        # ---- 关键点异常保护 ----
        valid, reason, pts, palm, scale, bbox = self._validate_input(points)
        if not valid:
            return self._invalid_result(reason)

        # ---- 计算各分数 ----
        curl = self._curl_scores(pts, palm, scale)
        tb_raw, tb = self._thumb_bend_score(pts, palm, scale)
        ts_raw, ts = self._thumb_swing_score(pts, palm, scale)

        inserted = False  # thumb_swing 是否被反转（当前不反转）
        raw = self._build_raw(curl, tb, ts)

        # ---- 平滑 ----
        throttled = (now - self._last_time < self.min_interval and
                     self._smoothed_pose is not None)
        if throttled:
            smoothed = self._smoothed_pose
        else:
            self._last_time = now
            raw_before = list(self._smoothed_pose) if self._smoothed_pose else list(raw)
            smoothed = self._smooth_with_deadzone(raw)
            smoothed_info = {
                "before_smooth": [round(v, 2) for v in raw_before],
                "after_smooth": [round(v, 2) for v in smoothed],
                "max_delta_applied": any(
                    abs(r - s) >= self.max_delta - 1e-6 for r, s in zip(raw, raw_before)),
                "deadzone_skipped": [round(abs(a - b), 2) <= self.deadzone
                                     for a, b in zip(smoothed, raw)],
            }
        if not throttled:
            self._smoothed_pose = smoothed

        final = [int(clamp(v, 0, 255)) for v in smoothed]
        self._last_pose = final

        self._last_debug = {
            "valid": True, "frame_id": self._frame_count,
            "curl_scores": {k: round(v, 3) for k, v in curl.items()},
            "raw_pose": [round(v, 2) for v in raw],
            "smoothed_pose": [round(v, 2) for v in smoothed],
            "final_pose": final,
            "thumb_swing_score": round(ts, 3),
            "thumb_swing_raw": round(ts_raw, 3),
            "thumb_swing_source": "thumb_tip lateral offset from palm, NOT wrist",
            "thumb_swing_inverted": inserted,
            "thumb_bend_score": round(tb, 3),
            "thumb_bend_raw": round(tb_raw, 3),
            "mirror_mode": self.mirror_mode,
            "throttled": throttled,
            "smooth_info": smoothed_info if not throttled else None,
            "bbox": bbox,
            "hand_scale": round(scale, 4),
            "param_source": self.gui.source_path,
        }

        return {"valid": True, "reason": "ok", "pose": final, "debug": self._last_debug}

    # ================================================================
    # 输入校验
    # ================================================================
    def _validate_input(self, points):
        try:
            pts = validate_keypoints(points)
        except Exception as exc:
            return False, f"validation failed: {exc}", None, None, None, None

        # NaN / None 检查
        for i, p in enumerate(pts):
            if any(math.isnan(v) for v in p):
                return False, f"point[{i}] contains NaN", None, None, None, None

        bbox = compute_bbox(pts)
        w = bbox.get("xmax", 0) - bbox.get("xmin", 0) if isinstance(bbox, dict) else 0
        h = bbox.get("ymax", 0) - bbox.get("ymin", 0) if isinstance(bbox, dict) else 0
        area = w * h
        if area < self.MIN_BBOX_AREA:
            return False, f"bbox area too small ({area:.2e})", None, None, None, None

        # 重合点检查
        unique = len({(round(p[0], 4), round(p[1], 4)) for p in pts})
        if unique / len(pts) < (1.0 - self.MAX_DUPLICATE_RATIO):
            return False, f"too many duplicate points ({unique}/{len(pts)} unique)", None, None, None, None

        palm = virtual_palm_center(pts)
        _, scale = normalize_keypoints(pts)

        # 手指长度异常检查（warning，不拒绝）
        finger_defs = {"thumb": (0, 2), "index": (3, 4), "middle": (5, 6),
                       "ring": (7, 8), "little": (9, 10)}
        for fname, (bi, ti) in finger_defs.items():
            fl = distance(pts[bi], pts[ti])
            ratio = fl / max(scale, 1e-6)
            if ratio < self.FINGER_LENGTH_RATIO_MIN or ratio > self.FINGER_LENGTH_RATIO_MAX:
                # warning only，仍继续
                pass

        return True, "ok", pts, palm, scale, bbox

    # ================================================================
    # 连续 curl score
    # ================================================================
    def _curl_scores(self, pts, palm, scale):
        cfg = {"index": (3, 4), "middle": (5, 6), "ring": (7, 8), "little": (9, 10)}
        scores = {}
        for f, (bi, ti) in cfg.items():
            base, tip = pts[bi], pts[ti]
            dbt = distance(base, tip)         # base-tip 距离
            dtp = distance(tip, palm)          # tip-to-palm
            dbp = distance(base, palm)         # base-to-palm
            ratio = dtp / max(dbp, 1e-6)

            # 方向因子：tip 指向离开 palm 为正（用于判断伸直程度）
            dot = ((tip[0] - base[0]) * (base[0] - palm[0]) +
                   (tip[1] - base[1]) * (base[1] - palm[1]))
            direction_factor = 1.0 + 0.2 * clamp(dot / max(dbt * dbp, 1e-6), -1, 1)

            # 综合距离比 + 方向
            adj_ratio = ratio * max(0.8, min(1.2, direction_factor))
            s = clamp((1.8 - adj_ratio) / (1.8 - 0.7), 0.0, 1.0)
            scores[f] = s
        return scores

    def _thumb_bend_score(self, pts, palm, scale):
        raw = distance(pts[2], palm) / max(distance(pts[0], palm), 1e-6)
        score = clamp((1.35 - raw) / (1.35 - 0.85), 0.0, 1.0)
        return raw, score

    def _thumb_swing_score(self, pts, palm, scale):
        # 多特征融合
        thumb_tip, idx_base = pts[2], pts[3]

        # 1. 横向偏移（相对 palm center）
        lateral = abs(thumb_tip[0] - palm[0]) / max(scale, 1e-6)

        # 2. thumb_tip 与 index_base 横向距离
        idx_lateral = abs(thumb_tip[0] - idx_base[0]) / max(scale, 1e-6)

        # 3. thumb_tip 与 index_tip 距离（判断是否靠近）
        idx_tip = pts[4]
        d_to_idx = distance(thumb_tip, idx_tip) / max(scale, 1e-6)

        # 加权融合
        raw = 0.4 * lateral + 0.35 * idx_lateral + 0.25 * max(0, 1.0 - d_to_idx)
        score = clamp(raw / 0.45, 0.0, 1.0)
        return raw, score

    # ================================================================
    # pose 构建
    # ================================================================
    @staticmethod
    def _lerp(f, a, b):
        return a + f * (b - a)

    def _build_raw(self, curl, tb, ts):
        raw = [0.0] * 6
        raw[0] = self._lerp(tb, self.open_pose[0], self.fist_pose[0])
        raw[1] = self._lerp(ts, self.fist_pose[1], self.open_pose[1])  # score=1 -> thumb 外摆
        raw[2] = self._lerp(curl["index"], self.open_pose[2], self.fist_pose[2])
        raw[3] = self._lerp(curl["middle"], self.open_pose[3], self.fist_pose[3])
        raw[4] = self._lerp(curl["ring"], self.open_pose[4], self.fist_pose[4])
        raw[5] = self._lerp(curl["little"], self.open_pose[5], self.fist_pose[5])
        return raw

    def _smooth_with_deadzone(self, raw):
        if self._smoothed_pose is None:
            self._smoothed_pose = list(raw)
            return self._smoothed_pose
        smooth = [p + self.smoothing_alpha * (c - p)
                  for p, c in zip(self._smoothed_pose, raw)]
        clamped = []
        for prev, curr in zip(self._smoothed_pose, smooth):
            delta = curr - prev
            if abs(delta) <= self.deadzone:
                delta = 0.0
            elif abs(delta) > self.max_delta:
                delta = self.max_delta if delta > 0 else -self.max_delta
            clamped.append(prev + delta)
        self._smoothed_pose = clamped
        return clamped

    def _invalid_result(self, reason):
        return {"valid": False, "reason": reason, "pose": self._last_pose or [250]*6,
                "debug": {"valid": False, "reason": reason}}

    # ================================================================
    # 说明
    # ================================================================
    def explain_mapping(self, points):
        pts = validate_keypoints(points)
        res = self.map_keypoints(pts)
        dbg = res.get("debug", {})
        return {
            "valid": res["valid"],
            "pose_6dim": res["pose"],
            "o6_dimensions": [
                {"dim": 0, "name": "thumb_bend", "中文": "大拇指弯曲",
                 "keypoints": "[0]thumb_base, [1]thumb_mid, [2]thumb_tip",
                 "curl_score": dbg.get("thumb_bend_score"),
                 "open_val": self.open_pose[0], "fist_val": self.fist_pose[0],
                 "lerp_factor": dbg.get("thumb_bend_score"),
                 "final_value": res["pose"][0] if res["pose"] else None,
                 "smoothing_applied": dbg.get("smooth_info", {}).get("max_delta_applied", False),
                 "deadzone_skipped": "N/A"},
                {"dim": 1, "name": "thumb_swing", "中文": "大拇指横摆（非手腕）",
                 "keypoints": "[2]thumb_tip lateral offset from palm",
                 "curl_score": dbg.get("thumb_swing_score"),
                 "open_val": self.open_pose[1], "fist_val": self.fist_pose[1],
                 "lerp_factor": dbg.get("thumb_swing_score"),
                 "final_value": res["pose"][1] if res["pose"] else None,
                 "inverted": False,
                 "note": "NOT wrist"},
                {"dim": 2, "name": "index_bend", "中文": "食指弯曲",
                 "keypoints": "[3]index_base, [4]index_tip",
                 "curl_score": dbg.get("curl_scores", {}).get("index"),
                 "open_val": self.open_pose[2], "fist_val": self.fist_pose[2],
                 "final_value": res["pose"][2] if res["pose"] else None},
                {"dim": 3, "name": "middle_bend", "中文": "中指弯曲",
                 "keypoints": "[5]middle_base, [6]middle_tip",
                 "curl_score": dbg.get("curl_scores", {}).get("middle"),
                 "open_val": self.open_pose[3], "fist_val": self.fist_pose[3],
                 "final_value": res["pose"][3] if res["pose"] else None},
                {"dim": 4, "name": "ring_bend", "中文": "无名指弯曲",
                 "keypoints": "[7]ring_base, [8]ring_tip",
                 "curl_score": dbg.get("curl_scores", {}).get("ring"),
                 "open_val": self.open_pose[4], "fist_val": self.fist_pose[4],
                 "final_value": res["pose"][4] if res["pose"] else None},
                {"dim": 5, "name": "little_bend", "中文": "小拇指弯曲",
                 "keypoints": "[9]little_base, [10]little_tip",
                 "curl_score": dbg.get("curl_scores", {}).get("little"),
                 "open_val": self.open_pose[5], "fist_val": self.fist_pose[5],
                 "final_value": res["pose"][5] if res["pose"] else None},
            ],
            "endpoints": {"open": self.open_pose, "fist": self.fist_pose,
                          "ok": self.ok_pose, "two (scissors temp)": self.two_pose},
            "smooth_params": {"smoothing_alpha": self.smoothing_alpha,
                              "max_delta": self.max_delta, "deadzone": self.deadzone},
            "param_source": self.gui.source_path,
        }

    # ---- 辅助 ----
    def get_last_pose(self):
        return self._last_pose
    def should_emit_now(self):
        return time.time() - self._last_time >= self.min_interval
    def reset_smoothing(self):
        self._smoothed_pose = None
        self._last_time = 0.0
