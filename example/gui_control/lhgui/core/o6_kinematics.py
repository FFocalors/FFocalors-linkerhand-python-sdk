#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LinkerHand O6 运动学模块。

从 o6_left_runtime.json 加载关节树，计算每个 link 的世界变换矩阵。
"""
import json
import math
import os
from typing import Dict, List, Optional

import numpy as np


def _rotation_matrix_rpy(roll, pitch, yaw):
    """从 RPY (roll, pitch, yaw) 构造 4x4 旋转矩阵。

    URDF/Xacro 语义: 固定轴 XYZ 欧拉角 (先绕 X, 再 Y, 再 Z)。
    """
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    return np.array([
        [cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr, 0],
        [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr, 0],
        [-sp,   cp*sr,             cp*cr,             0],
        [0,     0,                 0,                 1]
    ], dtype=np.float64)


def _rotation_matrix_axis_angle(axis, angle):
    """绕任意轴旋转的 4x4 矩阵。"""
    ax = np.array(axis, dtype=np.float64)
    norm = np.linalg.norm(ax)
    if norm < 1e-10:
        return np.eye(4)
    ax = ax / norm

    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    x, y, z = ax

    return np.array([
        [t*x*x + c,    t*x*y - s*z,  t*x*z + s*y,  0],
        [t*x*y + s*z,  t*y*y + c,    t*y*z - s*x,  0],
        [t*x*z - s*y,  t*y*z + s*x,  t*z*z + c,    0],
        [0,            0,            0,              1]
    ], dtype=np.float64)


def _translation_matrix(xyz):
    """构造平移矩阵。"""
    m = np.eye(4)
    m[0, 3] = xyz[0]
    m[1, 3] = xyz[1]
    m[2, 3] = xyz[2]
    return m


def _scale_matrix(scale):
    """构造缩放矩阵。"""
    m = np.eye(4)
    m[0, 0] = scale[0]
    m[1, 1] = scale[1]
    m[2, 2] = scale[2]
    return m


class O6Kinematics:
    """LinkerHand O6 运动学求解器。"""

    def __init__(self, runtime_json_path: str):
        with open(runtime_json_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        self._links = self._data["links"]
        self._joints = self._data["joints"]

        # 关节角存储 (主关节)
        self._joint_angles: Dict[str, float] = {}
        for jname, jdef in self._joints.items():
            if "mimic" not in jdef:
                self._joint_angles[jname] = 0.0

        # 构建 parent -> children 映射
        self._children: Dict[str, List[str]] = {}
        for jname, jdef in self._joints.items():
            parent = jdef["parent"]
            if parent not in self._children:
                self._children[parent] = []
            self._children[parent].append(jname)

        # 计算拓扑排序
        self._sorted_joints = self._topo_sort()

    def _topo_sort(self) -> List[str]:
        """拓扑排序关节。"""
        visited = set()
        order = []

        def visit(link):
            if link in visited:
                return
            visited.add(link)
            for jname in self._children.get(link, []):
                jdef = self._joints[jname]
                child = jdef["child"]
                order.append(jname)
                visit(child)

        visit(self._data["root_link"])
        return order

    def set_joint_angle(self, joint_name: str, angle: float):
        """设置主关节角度 (弧度)。"""
        if joint_name in self._joint_angles:
            # 按 limit 裁剪
            jdef = self._joints[joint_name]
            lo, hi = jdef["limit"]
            self._joint_angles[joint_name] = max(lo, min(hi, angle))

    def set_joint_angles_from_values(self, values: List[float]):
        """从 6 路输入值设置所有关节角。

        映射:
        values[0] -> thumb_joint1 (bend)
        values[1] -> thumb_joint2 (swing)
        values[2] -> index_joint
        values[3] -> middle_joint
        values[4] -> ring_joint
        values[5] -> pinky_joint
        """
        if len(values) < 6:
            return

        # 映射关系 (基于 Xacro 关节定义)
        mapping = [
            ("thumb_joint1", values[0]),
            ("thumb_joint2", values[1]),
            ("index_joint", values[2]),
            ("middle_joint", values[3]),
            ("ring_joint", values[4]),
            ("pinky_joint", values[5]),
        ]

        for jname, val in mapping:
            # 值 0-255 映射到关节限位范围
            # 值 255 = 伸直 (lower=0), 值 0 = 完全弯曲 (upper)
            # bend_ratio: (255 - v) / 255, v=255 -> 0, v=0 -> 1
            ratio = max(0.0, min(1.0, (255.0 - val) / 255.0))

            jdef = self._joints[jname]
            lo, hi = jdef["limit"]
            angle = lo + ratio * (hi - lo)
            self.set_joint_angle(jname, angle)

    def get_link_transforms(self) -> Dict[str, np.ndarray]:
        """计算所有 link 的世界变换矩阵。返回 4x4 矩阵字典。"""
        transforms: Dict[str, np.ndarray] = {}

        # 根节点
        root = self._data["root_link"]
        transforms[root] = np.eye(4)

        for jname in self._sorted_joints:
            jdef = self._joints[jname]
            parent = jdef["parent"]
            child = jdef["child"]

            parent_world = transforms.get(parent, np.eye(4))

            # 1. joint origin translation
            T_origin = _translation_matrix(jdef["origin_xyz"])

            # 2. joint origin rotation (RPY)
            R_origin = _rotation_matrix_rpy(*jdef["origin_rpy"])

            # 3. joint axis rotation
            angle = self._get_joint_angle(jname)
            R_axis = _rotation_matrix_axis_angle(jdef["axis"], angle)

            # 合成: parent_world * T_origin * R_origin * R_axis
            child_world = parent_world @ T_origin @ R_origin @ R_axis
            transforms[child] = child_world

        return transforms

    def _get_joint_angle(self, jname: str) -> float:
        """获取关节角度 (处理 mimic)。"""
        jdef = self._joints[jname]
        mimic = jdef.get("mimic")
        if mimic:
            base_angle = self._joint_angles.get(mimic["joint"], 0.0)
            return base_angle * mimic["multiplier"] + mimic["offset"]
        return self._joint_angles.get(jname, 0.0)

    def get_link_mesh_info(self) -> Dict[str, dict]:
        """获取每个 link 的网格信息 (路径、缩放)。"""
        info = {}
        for link_name, link_def in self._links.items():
            info[link_name] = {
                "mesh": link_def["mesh"],
                "scale": link_def.get("scale", [1, 1, 1]),
            }
        return info
