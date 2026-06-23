#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gesture_recognizer.py - custom_11 手势识别：rock/paper/scissors/unknown。"""
from custom11_keypoints import validate_keypoints, virtual_palm_center, distance

class Custom11GestureRecognizer:
    EXTEND_THRESHOLD = 1.55
    CURL_THRESHOLD = 1.05
    CONFIDENCE_SCALE = 5.0
    FINGER_ORDER = ["index","middle","ring","little"]
    FINGER_INDICES = {"index":{"base":3,"tip":4},"middle":{"base":5,"tip":6},
                       "ring":{"base":7,"tip":8},"little":{"base":9,"tip":10}}

    def __init__(self, extend_threshold=None, curl_threshold=None):
        self.extend_threshold = extend_threshold or self.EXTEND_THRESHOLD
        self.curl_threshold = curl_threshold or self.CURL_THRESHOLD

    def recognize(self, points):
        pts = validate_keypoints(points)
        palm = virtual_palm_center(pts)
        scores, states = {}, {}
        for f in self.FINGER_ORDER:
            idx = self.FINGER_INDICES[f]
            b, t = pts[idx["base"]], pts[idx["tip"]]
            db = distance(b, palm); dt = distance(t, palm)
            ratio = dt / max(db, 1e-6)
            state = "extended" if ratio >= self.extend_threshold else ("curled" if ratio <= self.curl_threshold else "neutral")
            scores[f] = {"base_to_palm":db,"tip_to_palm":dt,"base_to_tip":distance(b,t),"ratio":ratio}
            states[f] = state
        ts, tsc = self._thumb_state(pts, palm)
        g, conf = self._classify(states, scores)
        return {"gesture":g,"finger_states":states,"confidence":conf,
                "debug":{"palm_center":palm,"finger_scores":scores,"finger_states":states,"thumb":{"state":ts,"score":tsc}}}

    def _thumb_state(self, pts, palm):
        r = distance(pts[2], palm) / max(distance(pts[0], palm), 1e-6)
        return ("extended", r) if r > 1.2 else ("curled", r)

    def _classify(self, states, scores):
        ext = {f: states[f]=="extended" for f in self.FINGER_ORDER}
        cur = {f: states[f]=="curled" for f in self.FINGER_ORDER}
        if all(ext.values()): return "paper", self._conf(scores, "extended")
        if all(cur.values()): return "rock", self._conf(scores, "curled")
        if ext["index"] and ext["middle"] and cur["ring"] and cur["little"]:
            return "scissors", self._conf(scores, "mixed")
        return "unknown", 0.0

    def _conf(self, scores, target):
        margins = []
        for f, sc in scores.items():
            r = sc["ratio"]
            if target == "extended": m = (r - self.extend_threshold) * self.CONFIDENCE_SCALE
            elif target == "curled": m = (self.curl_threshold - r) * self.CONFIDENCE_SCALE
            else: m = (r - self.extend_threshold)*self.CONFIDENCE_SCALE if f in ("index","middle") else (self.curl_threshold - r)*self.CONFIDENCE_SCALE
            margins.append(max(0.0, min(1.0, m)))
        return sum(margins)/len(margins) if margins else 0.0
