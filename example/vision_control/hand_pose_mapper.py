#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hand_pose_mapper.py - custom_11 -> O6 6-dim pose 动态映射。"""
import time
from o6_gui_params_adapter import O6GuiParamsAdapter
from custom11_keypoints import validate_keypoints, virtual_palm_center, distance, clamp, normalize_keypoints

class Custom11ToO6PoseMapper:
    THUMB_BEND_OPEN_RATIO = 1.35
    THUMB_BEND_CLOSE_RATIO = 0.85
    THUMB_SWING_REF_X_RATIO = 0.45

    def __init__(self, smoothing_alpha=0.3, max_delta=50, min_interval=0.05):
        self.gui = O6GuiParamsAdapter()
        self.open_pose = self.gui.get_pose_by_action("张开")
        self.fist_pose = self.gui.get_pose_by_action("握拳")
        self.ok_pose = self.gui.get_pose_by_action("OK")
        self.smoothing_alpha = clamp(smoothing_alpha, 0.0, 1.0)
        self.max_delta = max_delta
        self.min_interval = min_interval
        self._smoothed_pose = None
        self._last_time = 0.0

    def map(self, points):
        pts = validate_keypoints(points)
        palm = virtual_palm_center(pts)
        _, scale = normalize_keypoints(points)
        curl = self._curl_scores(pts, palm)
        tb = self._thumb_bend_score(pts, palm)
        ts = self._thumb_swing_score(pts, scale)

        def lerp(f, a, b): return a + f*(b - a)
        raw = [0.0]*6
        raw[0] = lerp(tb, self.open_pose[0], self.fist_pose[0])
        raw[1] = lerp(ts, self.fist_pose[1], self.open_pose[1])  # score=1 -> open
        raw[2] = lerp(curl["index"], self.open_pose[2], self.fist_pose[2])
        raw[3] = lerp(curl["middle"], self.open_pose[3], self.fist_pose[3])
        raw[4] = lerp(curl["ring"], self.open_pose[4], self.fist_pose[4])
        raw[5] = lerp(curl["little"], self.open_pose[5], self.fist_pose[5])

        now = time.time()
        throttled = False
        if now - self._last_time < self.min_interval and self._smoothed_pose is not None:
            throttled = True
            smoothed = self._smoothed_pose
        else:
            self._last_time = now
            smoothed = self._smooth(raw)
        final = [int(clamp(v, 0, 255)) for v in smoothed]
        return {"final_pose":final, "smoothed_pose":[round(v,2) for v in smoothed],
                "raw_pose":[round(v,2) for v in raw],
                "curl_scores":{k:round(v,3) for k,v in curl.items()},
                "thumb_swing_score":round(ts,3),
                "thumb_bend_score":round(tb,3),
                "dry_run_info":{"throttled":throttled,"smoothing_alpha":self.smoothing_alpha,
                                "max_delta":self.max_delta,"min_interval":self.min_interval,
                                "source":"O6GuiParamsAdapter: open=张开, fist=握拳"}}

    def _curl_scores(self, pts, palm):
        cfg = {"index":{"b":3,"t":4},"middle":{"b":5,"t":6},"ring":{"b":7,"t":8},"little":{"b":9,"t":10}}
        scores = {}
        for f, c in cfg.items():
            r = distance(pts[c["t"]], palm) / max(distance(pts[c["b"]], palm), 1e-6)
            s = (1.8 - r) / (1.8 - 0.7)
            scores[f] = clamp(s, 0.0, 1.0)
        return scores

    def _thumb_bend_score(self, pts, palm):
        r = distance(pts[2], palm) / max(distance(pts[0], palm), 1e-6)
        s = (self.THUMB_BEND_OPEN_RATIO - r) / (self.THUMB_BEND_OPEN_RATIO - self.THUMB_BEND_CLOSE_RATIO)
        return clamp(s, 0.0, 1.0)

    def _thumb_swing_score(self, pts, scale):
        palm = virtual_palm_center(pts)
        offset = abs(pts[2][0] - palm[0])
        s = offset / max(scale, 1e-6) / self.THUMB_SWING_REF_X_RATIO
        return clamp(s, 0.0, 1.0)

    def _smooth(self, raw):
        if self._smoothed_pose is None:
            self._smoothed_pose = list(raw)
            return self._smoothed_pose
        smooth = [p + self.smoothing_alpha*(c-p) for p,c in zip(self._smoothed_pose, raw)]
        clamped = []
        for p,c in zip(self._smoothed_pose, smooth):
            d = c - p
            if abs(d) > self.max_delta:
                d = self.max_delta if d>0 else -self.max_delta
            clamped.append(p + d)
        self._smoothed_pose = clamped
        return clamped

    def reset(self):
        self._smoothed_pose = None; self._last_time = 0.0
