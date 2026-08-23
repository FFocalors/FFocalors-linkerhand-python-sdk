#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时三维左手机械手姿态视图（基于 URDF STL 网格）。
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QMatrix4x4, QVector3D
from PyQt5.QtWidgets import QSizePolicy
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader

# ---------------------------------------------------------------------------
# 工业 shaded 着色器（保留方向光层次，暗面抬到 55%）
# ---------------------------------------------------------------------------
INDUSTRIAL_SHADER = "industrialShaded"
ShaderProgram(INDUSTRIAL_SHADER, [
    VertexShader("""
        varying vec3 normal;
        void main() {
            normal = normalize(gl_NormalMatrix * gl_Normal);
            gl_FrontColor = gl_Color;
            gl_BackColor = gl_Color;
            gl_Position = ftransform();
        }
    """),
    FragmentShader("""
        varying vec3 normal;
        void main() {
            float diffuse = dot(normal, normalize(vec3(1.0, -1.0, -1.0)));
            diffuse = diffuse < 0.0 ? 0.0 : diffuse * 0.35;
            vec4 color = gl_Color;
            color.rgb = color.rgb * (0.55 + diffuse);
            gl_FragColor = color;
        }
    """),
])

# ---------------------------------------------------------------------------
# 材质配色
# ---------------------------------------------------------------------------
C_PALM_DARK = (0.60, 0.62, 0.66, 1.0)          # 中灰色手掌装甲
C_FINGER_FRAME = (0.50, 0.52, 0.56, 1.0)       # 石墨灰指骨骨架与夹板
C_JOINT_DARK = (0.70, 0.72, 0.76, 1.0)         # 亮灰色销轴
C_PAD_LIGHT = (0.95, 0.96, 0.98, 1.0)          # 指腹与指尖的洁白软垫
C_PALM_PAD_LIGHT = (0.90, 0.91, 0.93, 1.0)     # 掌心白色防滑垫片

# 活动高亮配色
C_PAD_ACTIVE = (0.72, 0.87, 1.0, 1.0)          # 软垫激活冰蓝
C_JOINT_ACTIVE = (0.28, 0.52, 0.96, 1.0)        # 关节激活蓝

# ---------------------------------------------------------------------------
# 关节索引
# ---------------------------------------------------------------------------
IDX_THUMB_BEND = 0; IDX_THUMB_SWING = 1
IDX_INDEX = 2; IDX_MIDDLE = 3; IDX_RING = 4; IDX_LITTLE = 5

# URDF STL 缩放（URDF 为米，转 mm 适配 pyqtgraph 场景）
_STL_SCALE = 1000.0


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def bend_ratio(v):
    return (255.0 - max(0.0, min(255.0, v))) / 255.0


def spread_ratio(v):
    return max(0.0, min(255.0, v)) / 255.0


def sanitize_joint_values(values, mn=0.0, mx=255.0) -> Optional[List[float]]:
    if not isinstance(values, (list, tuple)) or len(values) < 6:
        return None
    out = []
    for v in values[:6]:
        try:
            n = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(n):
            return None
        out.append(max(mn, min(mx, n)))
    return out


class _FingerItem:
    """手指高亮包装：统一控制一组 GLMeshItem 的颜色。"""

    def __init__(self, items: List[gl.GLMeshItem]) -> None:
        self.items = items

    def set_active(self, active: bool) -> None:
        color = C_JOINT_ACTIVE if active else C_FINGER_FRAME
        for item in self.items:
            item.opts['color'] = color
            item.update()

    def reset_color(self) -> None:
        self.set_active(False)


class HandPoseView(gl.GLViewWidget):
    def __init__(self, hand_joint: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PoseView")
        self.hand_joint = hand_joint

        # 自适应大小
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 240)
        self.setBackgroundColor((248, 250, 252, 255))

        self._curr_center = None
        self._curr_distance = None
        self.setCameraPosition(distance=80, azimuth=0, elevation=0)

        self._current = [0.0] * 6
        self._target = [0.0] * 6
        self._last_valid: Optional[List[float]] = None
        self._fingers: Dict[int, _FingerItem] = {}
        self._first_fit = True

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(20)
        self._anim_timer.timeout.connect(self._animate_step)

        self._build_3d_hand()
        self._init_from_config()

        from lhgui.styles.theme_manager import get_theme_manager
        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(self._apply_theme)
            self._apply_theme(manager.current)

    # ---------------------------------------------------------------------------
    # STL / URDF 加载
    # ---------------------------------------------------------------------------
    def _load_stl_hand(self) -> Optional[gl.GLMeshItem]:
        from lhgui.utils.stl_loader import load_stl_meshdata
        from lhgui.utils.urdf_parser import parse_urdf, get_urdf_path
        from lhgui.utils.joint_mapper import get_urdf_model_for_hand

        hand_type = "left"
        urdf_model = get_urdf_model_for_hand(self.hand_joint)
        urdf_path = get_urdf_path(hand_type, urdf_model)
        urdf_data = parse_urdf(urdf_path)

        self._urdf_joints: Dict[str, Any] = urdf_data["joints"]
        self._urdf_links: Dict[str, Any] = urdf_data["links"]
        self._stl_items: Dict[str, gl.GLMeshItem] = {}

        # 从 links 收集视觉网格
        for link_name, link_info in self._urdf_links.items():
            mesh_path = link_info.get("mesh_path")
            if not mesh_path:
                continue
            try:
                md = load_stl_meshdata(mesh_path)
            except Exception:
                continue
            verts = np.asarray(md.vertexes(), dtype=np.float32) * _STL_SCALE
            faces = np.asarray(md.faces(), dtype=np.int32)
            scaled_md = gl.MeshData(vertexes=verts, faces=faces)
            color = C_PALM_DARK if link_name == "base_link" else C_FINGER_FRAME
            item = gl.GLMeshItem(
                meshdata=scaled_md,
                drawFaces=True,
                drawEdges=False,
                shader=INDUSTRIAL_SHADER,
                color=color,
            )
            self._stl_items[link_name] = item

        # 从 joints 收集子链接网格（兼容仅有 joint mesh 的定义）
        for joint_name, joint_info in self._urdf_joints.items():
            mesh_path = joint_info.get("mesh_path")
            child_link = joint_info.get("child_link")
            if not mesh_path or not child_link:
                continue
            if child_link in self._stl_items:
                continue
            try:
                md = load_stl_meshdata(mesh_path)
            except Exception:
                continue
            verts = np.asarray(md.vertexes(), dtype=np.float32) * _STL_SCALE
            faces = np.asarray(md.faces(), dtype=np.int32)
            scaled_md = gl.MeshData(vertexes=verts, faces=faces)
            color = C_PALM_DARK if child_link == "base_link" else C_FINGER_FRAME
            item = gl.GLMeshItem(
                meshdata=scaled_md,
                drawFaces=True,
                drawEdges=False,
                shader=INDUSTRIAL_SHADER,
                color=color,
            )
            self._stl_items[child_link] = item

        # 建立层级父子关系
        for joint_name, joint_info in self._urdf_joints.items():
            parent_link = joint_info.get("parent_link")
            child_link = joint_info.get("child_link")
            if child_link in self._stl_items and parent_link in self._stl_items:
                self._stl_items[child_link].setParentItem(self._stl_items[parent_link])

        return self._stl_items.get("base_link")

    # ---------------------------------------------------------------------------
    # 构建手部
    # ---------------------------------------------------------------------------
    def _build_3d_hand(self) -> None:
        palm_item = self._load_stl_hand()
        if palm_item is None:
            return
        self.palm_item = palm_item
        self.addItem(self.palm_item)
        self._apply_global_pose()

        finger_groups: Dict[int, List[str]] = {
            IDX_THUMB_BEND: ["thumb_joint0", "thumb_joint2", "thumb_joint3"],
            IDX_INDEX: ["index_joint1", "index_joint2", "index_joint3"],
            IDX_MIDDLE: ["middle_joint1", "middle_joint2", "middle_joint3"],
            IDX_RING: ["ring_joint1", "ring_joint2", "ring_joint3"],
            IDX_LITTLE: ["little_joint1", "little_joint2", "little_joint3"],
        }
        for idx, joint_names in finger_groups.items():
            items: List[gl.GLMeshItem] = []
            for jname in joint_names:
                jinfo = self._urdf_joints.get(jname)
                if jinfo is None:
                    continue
                child_link = jinfo.get("child_link")
                if child_link and child_link in self._stl_items:
                    items.append(self._stl_items[child_link])
            if items:
                self._fingers[idx] = _FingerItem(items)

    # ---------------------------------------------------------------------------
    # 全局姿态
    # ---------------------------------------------------------------------------
    def _apply_global_pose(self) -> None:
        tr = QMatrix4x4()
        # URDF STL 转 mm 后高度约 80-150，向下平移约一半高度使手位于视图中央
        tr.translate(0.0, 0.0, -60.0)
        # 左手 palm 面朝相机
        tr.rotate(-45, 0, 0, 1)
        tr.rotate(15, 1, 0, 0)
        tr.rotate(5, 0, 1, 0)
        self.palm_item.setTransform(tr)

    # ---------------------------------------------------------------------------
    # 初始配置
    # ---------------------------------------------------------------------------
    def _init_from_config(self) -> None:
        try:
            from lhgui.config.constants import HAND_CONFIGS
            init = list(HAND_CONFIGS[self.hand_joint].init_pos)[:6]
            sanitized = sanitize_joint_values(init)
            if sanitized:
                self._target = list(sanitized)
                self._current = list(sanitized)
                self._last_valid = list(sanitized)
                self._apply_pose(self._current)
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # 动画与姿态更新
    # ---------------------------------------------------------------------------
    def update_joint_values(self, values: List[float]) -> None:
        sanitized = sanitize_joint_values(values)
        if sanitized is None:
            return
        self._target = sanitized
        self._last_valid = sanitized
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _animate_step(self) -> None:
        alpha = 0.25
        changed = False
        for i in range(6):
            d = self._target[i] - self._current[i]
            if abs(d) < 0.05:
                self._current[i] = self._target[i]
                continue
            self._current[i] += d * alpha
            changed = True
        if changed:
            self._apply_pose(self._current)
        else:
            self._anim_timer.stop()

    def _apply_pose(self, v: List[float]) -> None:
        from lhgui.utils.joint_mapper import sdk_range_to_urdf_angles

        urdf_angles = sdk_range_to_urdf_angles(v, self.hand_joint, self._urdf_joints)

        for joint_name, joint_info in self._urdf_joints.items():
            if joint_info.get("joint_type") == "fixed":
                continue
            child_link = joint_info.get("child_link")
            if child_link not in self._stl_items:
                continue

            origin_xyz = joint_info.get("origin_xyz", np.zeros(3))
            origin_rpy = joint_info.get("origin_rpy", np.zeros(3))
            axis_xyz = joint_info.get("axis_xyz", np.zeros(3))
            angle = urdf_angles.get(joint_name, 0.0)

            tr = QMatrix4x4()
            tr.translate(
                origin_xyz[0] * _STL_SCALE,
                origin_xyz[1] * _STL_SCALE,
                origin_xyz[2] * _STL_SCALE,
            )
            tr.rotate(math.degrees(origin_rpy[0]), 1, 0, 0)
            tr.rotate(math.degrees(origin_rpy[1]), 0, 1, 0)
            tr.rotate(math.degrees(origin_rpy[2]), 0, 0, 1)
            tr.rotate(math.degrees(angle), axis_xyz[0], axis_xyz[1], axis_xyz[2])
            self._stl_items[child_link].setTransform(tr)

        self._highlight(v)
        # 仅在第一次渲染时执行高 CPU 消耗的包围盒计算
        if self._first_fit:
            self._update_camera_fit()
            self._first_fit = False

    # ---------------------------------------------------------------------------
    # 相机适配
    # ---------------------------------------------------------------------------
    @staticmethod
    def _world_transform(item: gl.GLMeshItem) -> QMatrix4x4:
        tr = item.transform()
        parent = item.parentItem()
        while parent is not None:
            tr = parent.transform() * tr
            parent = parent.parentItem()
        return tr

    def _update_camera_fit(self) -> None:
        points = []
        for name, item in self._stl_items.items():
            md = item.opts.get('meshdata')
            if md is None:
                continue
            verts = md.vertexes()
            if verts is None or len(verts) == 0:
                continue
            world_tr = self._world_transform(item)
            for v in verts:
                p = world_tr.map(QVector3D(v[0], v[1], v[2]))
                points.append(p)

        if not points:
            return

        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        zs = [p.z() for p in points]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)

        target_center = QVector3D(
            (min_x + max_x) / 2.0,
            (min_y + max_y) / 2.0,
            (min_z + max_z) / 2.0,
        )

        dx = max_x - min_x
        dy = max_y - min_y
        dz = max_z - min_z
        span = max(dx, dy, dz)

        # 10%~15% 安全边距
        target_distance = max(80.0, span * 1.25)

        if self._curr_center is None:
            self._curr_center = target_center
            self._curr_distance = target_distance
        else:
            factor = 0.15
            self._curr_center = self._curr_center * (1.0 - factor) + target_center * factor
            self._curr_distance = self._curr_distance * (1.0 - factor) + target_distance * factor

        self.opts['center'] = self._curr_center
        self.opts['distance'] = self._curr_distance
        self.update()

    # ---------------------------------------------------------------------------
    # 高亮
    # ---------------------------------------------------------------------------
    def _highlight(self, v: List[float]) -> None:
        if not hasattr(self, "_prev"):
            self._prev = list(v)
            return

        max_d, idx = 0.0, -1
        for i in range(6):
            d = abs(v[i] - self._prev[i])
            if d > max_d:
                max_d, idx = d, i
        self._prev = list(v)
        if max_d < 1.5:
            return

        map_idx = {
            IDX_INDEX: IDX_INDEX, IDX_MIDDLE: IDX_MIDDLE,
            IDX_RING: IDX_RING, IDX_LITTLE: IDX_LITTLE,
            IDX_THUMB_BEND: IDX_THUMB_BEND, IDX_THUMB_SWING: IDX_THUMB_BEND,
        }
        target = map_idx.get(idx)
        if target is None:
            return

        for f in self._fingers.values():
            f.reset_color()

        f = self._fingers.get(target)
        if f is not None:
            f.set_active(True)

            def _reset() -> None:
                f.reset_color()

            QTimer.singleShot(450, _reset)

    # ---------------------------------------------------------------------------
    # 主题与生命周期
    # ---------------------------------------------------------------------------
    def _apply_theme(self, name: str) -> None:
        if name == "dark":
            self.setBackgroundColor((20, 29, 42, 255))
        else:
            self.setBackgroundColor((248, 250, 252, 255))
        self.update()

    def is_supported(self) -> bool:
        return True

    def hideEvent(self, event) -> None:
        self._anim_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._last_valid is not None:
            self._target = list(self._last_valid)
            if not self._anim_timer.isActive():
                self._anim_timer.start()

    # ---------------------------------------------------------------------------
    # 轨道相机（保持原逻辑）
    # ---------------------------------------------------------------------------
    def reset_camera(self) -> None:
        self._first_fit = True
        self.setCameraPosition(distance=80, azimuth=0, elevation=0)
        self.opts['center'] = QVector3D(0, 0, 0)
        self._curr_center = None
        self._curr_distance = None
        for attr in ('_orbit_start', '_pan_start'):
            if hasattr(self, attr):
                delattr(self, attr)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._orbit_start = event.pos()
            self._orbit_start_azimuth = self.opts['azimuth']
            self._orbit_start_elevation = self.opts['elevation']
        elif event.button() == Qt.RightButton:
            self._pan_start = event.pos()
        else:
            super().mousePressEvent(event)
            return
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton and hasattr(self, '_orbit_start'):
            delta = event.pos() - self._orbit_start
            self.opts['azimuth'] = self._orbit_start_azimuth - delta.x() * 0.3
            self.opts['elevation'] = max(
                -90.0, min(90.0, self._orbit_start_elevation + delta.y() * 0.3)
            )
            self.update()
        elif event.buttons() & Qt.RightButton and hasattr(self, '_pan_start'):
            delta = event.pos() - self._pan_start
            self.pan(delta.x(), delta.y(), 0, relative='view')
        else:
            super().mouseMoveEvent(event)
            return
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if hasattr(self, '_orbit_start'):
                delattr(self, '_orbit_start')
        elif event.button() == Qt.RightButton:
            if hasattr(self, '_pan_start'):
                delattr(self, '_pan_start')
        else:
            super().mouseReleaseEvent(event)
            return
        event.accept()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta == 0:
            super().wheelEvent(event)
            return

        notches = delta / 120.0
        if notches >= 0:
            factor = 0.95 ** notches
        else:
            factor = 1.05 ** (-notches)
        new_dist = self.opts['distance'] * factor
        new_dist = max(20.0, min(400.0, new_dist))
        self.opts['distance'] = new_dist
        self.update()
        event.accept()
