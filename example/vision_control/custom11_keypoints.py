#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom11_keypoints.py - custom_11 视觉关键点格式（无 wrist）。

支持多种输入格式：dict {"x","y","z"?}, list [x,y], [x,y,z], tuple (x,y), (x,y,z)
所有对外函数统一进行格式校验和标准化。
"""
import math
import json

CUSTOM11_ORDER = [
    "thumb_base", "thumb_mid_or_swing_ref", "thumb_tip",
    "index_base", "index_tip", "middle_base", "middle_tip",
    "ring_base", "ring_tip", "little_base", "little_tip",
]
CUSTOM11_COUNT = 11


# ----------------------------------------------------------------
# 内部：点格式统一
# ----------------------------------------------------------------
def _as_point(point):
    """将任意点格式统一为 (x, y, z_or_0)。"""
    if isinstance(point, (list, tuple)):
        if len(point) < 2:
            raise ValueError(f"Point must have >= 2 coords, got {point}")
        return (float(point[0]), float(point[1]), float(point[2]) if len(point) > 2 else 0.0)
    if isinstance(point, dict):
        x = float(point.get("x", point.get("X", None)))
        y = float(point.get("y", point.get("Y", None)))
        z = point.get("z", point.get("Z", None))
        return (x, y, float(z) if z is not None else 0.0)
    raise ValueError(f"Unsupported point format: {type(point).__name__}")


def normalize_keypoint(point):
    """将单个点统一为 {'x':float, 'y':float, 'z':float|None}。"""
    px, py, pz = _as_point(point)
    has_z = None
    if isinstance(point, dict) and ("z" in point or "Z" in point):
        has_z = pz
    elif isinstance(point, (list, tuple)) and len(point) >= 3:
        has_z = float(point[2])
    return {"x": px, "y": py, "z": has_z}


# ----------------------------------------------------------------
# 校验与归一化
# ----------------------------------------------------------------
def validate_keypoints(points, name="keypoints"):
    """
    校验 custom_11 格式。成功返回 [(x,y,z),...]。

    检查：
      - 非 None
      - 长度正好 11
      - 每个点可解析 x、y（必须数字）
      - z 可选，若有则必须数字
    """
    if points is None:
        raise ValueError(f"{name} is None")
    pts = list(points)
    if len(pts) != CUSTOM11_COUNT:
        raise ValueError(f"{name} must have exactly {CUSTOM11_COUNT} points, got {len(pts)}")
    result = []
    for i, p in enumerate(pts):
        try:
            result.append(_as_point(p))
        except Exception as exc:
            raise ValueError(f"{name}[{i}] invalid ({type(p).__name__}): {exc}") from exc
    return result


def normalize_keypoints(points):
    """
    将 11 点平移/缩放到以 virtual_palm_center 为原点。
    返回 (normalized_list, scale)。
    """
    pts = validate_keypoints(points)
    c = virtual_palm_center(pts)
    s = _hand_scale(pts)
    if s < 1e-6:
        s = 1.0
    return ([(x - c[0], y - c[1], z - c[2]) for x, y, z in pts], s)


# ----------------------------------------------------------------
# BBOX
# ----------------------------------------------------------------
def compute_bbox(points):
    """计算 11 点的最小包围盒。返回 {xmin,xmax,ymin,ymax,zmin,zmax,w,h}。"""
    pts = validate_keypoints(points)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return {
        "xmin": min(xs), "xmax": max(xs),
        "ymin": min(ys), "ymax": max(ys),
        "zmin": min(zs), "zmax": max(zs),
    }


def normalize_by_bbox(points):
    """按 bbox 归一化：平移至中心，等比例缩放到 bbox 最大边长为 1。"""
    pts = validate_keypoints(points)
    b = compute_bbox(pts)
    cx = (b["xmax"] + b["xmin"]) / 2.0
    cy = (b["ymax"] + b["ymin"]) / 2.0
    cz = (b["zmax"] + b["zmin"]) / 2.0
    w = b["xmax"] - b["xmin"]
    h = b["ymax"] - b["ymin"]
    d = b["zmax"] - b["zmin"]
    scale = max(w, h, d, 1e-6)
    return ([(round((x - cx) / scale, 6), round((y - cy) / scale, 6), round((z - cz) / scale, 6)) for x, y, z in pts], scale)


# ----------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------
def distance(p1, p2):
    a, b = _as_point(p1), _as_point(p2)
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def clamp(value, low, high):
    return max(low, min(high, value))


def virtual_palm_center(points):
    """用 index/middle/ring/little base 平均位置作为虚拟掌心。不是 O6 控制量。"""
    pts = validate_keypoints(points)
    idxs = [3, 5, 7, 9]
    xs = [pts[i][0] for i in idxs]
    ys = [pts[i][1] for i in idxs]
    zs = [pts[i][2] for i in idxs]
    return (sum(xs) / 4.0, sum(ys) / 4.0, sum(zs) / 4.0)


def _hand_scale(points):
    pts = validate_keypoints(points)
    return distance(pts[3], pts[9])


# ----------------------------------------------------------------
# Schema 与文档
# ----------------------------------------------------------------
def keypoint_schema():
    """返回 custom_11 的 JSON schema 说明。"""
    return {
        "format": "custom_11",
        "point_count": CUSTOM11_COUNT,
        "order": CUSTOM11_ORDER,
        "point_format": '{"x": float, "y": float, "z": float?}',
        "also_supports": ["[x,y]", "[x,y,z]", "(x,y)", "(x,y,z)"],
        "notes": [
            "No wrist point.",
            "virtual_palm_center is derived from index/middle/ring/little bases (internal only).",
            "custom_11 is visual input only, NOT an O6 control vector.",
        ],
        "example_payload": {
            "source": "camera",
            "timestamp": 1234567890.0,
            "hand": "left",
            "keypoints": [{"x": 0.0, "y": 0.0} for _ in range(11)],
        },
    }


def describe_custom11_order():
    """返回点位顺序的可读描述。"""
    return "\n".join(f"  {i:2d}: {name}" for i, name in enumerate(CUSTOM11_ORDER))
