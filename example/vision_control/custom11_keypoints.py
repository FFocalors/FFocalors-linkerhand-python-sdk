#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""custom11_keypoints.py - custom_11 视觉关键点格式（无 wrist）。"""
import math

CUSTOM11_ORDER = ["thumb_base","thumb_mid_or_swing_ref","thumb_tip","index_base","index_tip",
                  "middle_base","middle_tip","ring_base","ring_tip","little_base","little_tip"]
CUSTOM11_COUNT = 11

def _as_point(point):
    if isinstance(point, (list, tuple)):
        return (float(point[0]), float(point[1]), float(point[2]) if len(point)>2 else 0.0)
    if isinstance(point, dict):
        return (float(point.get("x",point.get("X",0.0))), float(point.get("y",point.get("Y",0.0))),
                float(point.get("z",point.get("Z",0.0))))
    raise ValueError(f"Unsupported point format: {point}")

def validate_keypoints(points, name="keypoints"):
    if points is None: raise ValueError(f"{name} is None")
    pts = list(points)
    if len(pts) != CUSTOM11_COUNT:
        raise ValueError(f"{name} must have {CUSTOM11_COUNT} pts, got {len(pts)}")
    return [_as_point(p) for p in pts]

def normalize_keypoints(points):
    pts = validate_keypoints(points)
    c = virtual_palm_center(pts)
    s = _hand_scale(pts)
    if s < 1e-6: s = 1.0
    return [(x-c[0],y-c[1],z-c[2]) for x,y,z in pts], s

def distance(p1, p2):
    a, b = _as_point(p1), _as_point(p2)
    return math.sqrt((a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2)

def clamp(value, low, high): return max(low, min(high, value))

def virtual_palm_center(points):
    pts = validate_keypoints(points)
    idxs = [3,5,7,9]
    xs = [pts[i][0] for i in idxs]; ys = [pts[i][1] for i in idxs]; zs = [pts[i][2] for i in idxs]
    return (sum(xs)/4.0, sum(ys)/4.0, sum(zs)/4.0)

def _hand_scale(points):
    pts = validate_keypoints(points)
    return distance(pts[3], pts[9])
