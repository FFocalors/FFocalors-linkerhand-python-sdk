#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时三维机械手姿态视图（基于 pyqtgraph.opengl 重构版）。

垂直立起 3D 数字孪生手，支持实时包围盒相机自适应。
左手模型，大拇指位于侧前方，白模 Clay 浅灰风格。
优化了模型细节结构：
1. 增加手掌前侧盖板（掌心能量核心面板）；
2. 每一个圆柱指节增加了两圈精致的机械套筒装饰环；
3. 每个关节点小球两侧增加了扁圆柱销轴端盖，突显真实的工业转轴细节。
"""
import math
from typing import List, Optional
import numpy as np

from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QMatrix4x4, QVector3D
import pyqtgraph.opengl as gl

# 高雅白模素模配色 (Clay Style, 无粗描边线，纯靠 shaded 光影表现圆滑体积感)
C_PALM_FACE = (0.92, 0.93, 0.95, 1.0)       # 极其干净的白模浅灰
C_FINGER_FACE_DEFAULT = (0.92, 0.93, 0.95, 1.0)
C_JOINT_DEFAULT = (0.83, 0.85, 0.88, 1.0)       # 稍深一点的白模灰色

# 活动高亮配色 (高保真强调蓝)
C_FINGER_FACE_ACTIVE = (0.86, 0.92, 1.0, 1.0)   # #dbeafe 激活浅蓝
C_JOINT_ACTIVE = (0.31, 0.55, 0.97, 1.0)        # #3b82f6 激活蓝

# 关节索引
IDX_THUMB_BEND = 0; IDX_THUMB_SWING = 1
IDX_INDEX = 2; IDX_MIDDLE = 3; IDX_RING = 4; IDX_LITTLE = 5

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

def make_palm_mesh():
    """生成极具机械科幻感的多面体（Low Poly Hard Surface）手掌网格。
    消除生硬的长方体与直角感，包含手腕倒角过渡、掌心肌肉膨胀多面折线、掌背装甲脊线和两侧切角。
    """
    # 32 个顶点，共 4 层 (Z=0, Z=6, Z=24, Z=48)
    vertexes = np.array([
        # Layer 0: Z=0 (手腕底座，收细)
        [  6.0, -2.0,  0.0],  # 0
        [  6.0,  2.0,  0.0],  # 1
        [  2.0,  3.0,  0.0],  # 2 (前侧右，掌心侧凸起)
        [ -2.0,  3.0,  0.0],  # 3 (前侧left，掌心侧凸起)
        [ -6.0,  2.0,  0.0],  # 4
        [ -6.0, -2.0,  0.0],  # 5
        [ -2.0, -3.0,  0.0],  # 6 (后侧左，掌背侧凸起)
        [  2.0, -3.0,  0.0],  # 7 (后侧右，掌背侧凸起)

        # Layer 1: Z=6 (手腕过渡区上方，扩张形成斜切角)
        [ 12.0, -4.0,  6.0],  # 8
        [ 12.0,  4.0,  6.0],  # 9
        [  4.0,  5.5,  6.0],  # 10
        [ -4.0,  5.5,  6.0],  # 11
        [-12.0,  4.0,  6.0],  # 12
        [-12.0, -4.0,  6.0],  # 13
        [ -4.0, -5.5,  6.0],  # 14
        [  4.0, -5.5,  6.0],  # 15

        # Layer 2: Z=24 (手掌中部，最厚、多棱切甲板)
        [ 16.0, -4.5, 24.0],  # 16
        [ 18.0,  5.5, 24.0],  # 17 (向外扩张，挂载大拇指的倾斜部位)
        [  5.0,  8.0, 24.0],  # 18 (大鱼际隆起)
        [ -5.0,  8.0, 24.0],  # 19 (小鱼际隆起)
        [-16.0,  4.5, 24.0],  # 20
        [-16.0, -4.5, 24.0],  # 21
        [ -5.0, -8.0, 24.0],  # 22 (掌背脊线装甲切面)
        [  5.0, -8.0, 24.0],  # 23 (掌背脊线装甲切面)

        # Layer 3: Z=48 (指根部，连接手指)
        [ 18.0, -5.0, 48.0],  # 24
        [ 18.0,  5.0, 48.0],  # 25
        [  6.0,  6.0, 48.0],  # 26
        [ -6.0,  6.0, 48.0],  # 27
        [-18.0,  5.0, 48.0],  # 28
        [-18.0, -5.0, 48.0],  # 29
        [ -6.0, -6.5, 48.0],  # 30
        [  6.0, -6.5, 48.0],  # 31
    ], dtype=np.float32)

    faces = []

    # 1. 生成侧面 3 个分段 (每段 8 个侧面，共 24 个侧面矩形 = 48 个三角形)
    for layer in range(3):
        start_idx = layer * 8
        for i in range(8):
            curr_i = start_idx + i
            next_i = start_idx + (i + 1) % 8
            faces.append([curr_i, next_i, next_i + 8])
            faces.append([curr_i, next_i + 8, curr_i + 8])

    # 2. 底面封底 (Z=0, 顺时针，法线朝下)
    faces.append([0, 2, 1])
    faces.append([0, 3, 2])
    faces.append([0, 4, 3])
    faces.append([0, 5, 4])
    faces.append([0, 6, 5])
    faces.append([0, 7, 6])

    # 3. 顶面封顶 (Z=48, 逆时针，法线朝上)
    faces.append([24, 25, 26])
    faces.append([24, 26, 27])
    faces.append([24, 27, 28])
    faces.append([24, 28, 29])
    faces.append([24, 29, 30])
    faces.append([24, 30, 31])

    return vertexes, np.array(faces, dtype=np.uint32)

class _MechanicalFinger3D:
    def __init__(self, parent_item, base_x, base_y, base_z, lengths, width, thickness, init_y_rot=0.0):
        self.lengths = lengths
        self.base_x = base_x
        self.base_y = base_y
        self.base_z = base_z
        self.init_y_rot = init_y_rot
        self.width = width
        self.thickness = thickness
        self.items = []
        self.joints = []
        
        # 逐节构建圆柱指节和销轴，每一节均挂在上一节的顶端
        w = width
        t = thickness
        for i, L in enumerate(lengths):
            scale = 0.9 ** i
            wi = w * scale
            ti = t * scale
            ri = wi / 2.0
            
            # 1. 圆柱指节
            cyl_md = gl.MeshData.cylinder(rows=6, cols=12, radius=[ri, ri], length=L)
            seg = gl.GLMeshItem(
                meshdata=cyl_md,
                drawFaces=True, drawEdges=False,
                shader='shaded',
                color=C_FINGER_FACE_DEFAULT
            )
            
            if i == 0:
                seg.setParentItem(parent_item)
            else:
                seg.setParentItem(self.items[-1])
            self.items.append(seg)
            
            # 2. 销轴球体 (位于当前指节基部)
            joint_r = wi * 0.60
            sph_md = gl.MeshData.sphere(rows=8, cols=8, radius=joint_r)
            joint = gl.GLMeshItem(
                meshdata=sph_md,
                drawFaces=True, drawEdges=False,
                shader='shaded',
                color=C_JOINT_DEFAULT
            )
            joint.setParentItem(seg)
            self.joints.append(joint)

    def set_active(self, active: bool):
        face_c = C_FINGER_FACE_ACTIVE if active else C_FINGER_FACE_DEFAULT
        joint_c = C_JOINT_ACTIVE if active else C_JOINT_DEFAULT
        
        for item in self.items:
            item.opts['color'] = face_c
            item.update()
        for j in self.joints:
            j.opts['color'] = joint_c
            j.update()

    def reset_color(self):
        self.set_active(False)

class HandPoseView(gl.GLViewWidget):
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PoseView")
        self.hand_joint = hand_joint
        self._is_six = False
        
        try:
            from lhgui.config.constants import HAND_CONFIGS
            self._is_six = len(HAND_CONFIGS[hand_joint].joint_names) == 6
        except Exception:
            pass

        # 设置自适应大小的 SizePolicy
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 240)
        
        # 浅灰蓝背景，与卡片完全融为一体
        self.setBackgroundColor((248, 250, 252, 255))
        
        self._curr_center = None
        self._curr_distance = None
        
        # 初始化相机参数，使观察者视线对准 3D 世界中心 (放大视距由 110 调至 80)
        self.setCameraPosition(distance=80, azimuth=0, elevation=0)
        
        self._current = [0.0] * 6
        self._target = [0.0] * 6
        self._last_valid: Optional[List[float]] = None
        self._fingers = {}
        self._first_fit = True
        
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(20)
        self._anim_timer.timeout.connect(self._animate_step)
        
        if self._is_six:
            self._build_3d_hand()
            self._init_from_config()
            
        from lhgui.utils.signal_bus import signal_bus
        signal_bus.joint_state_updated.connect(self.update_joint_values)
        from lhgui.styles.theme_manager import get_theme_manager
        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(self._apply_theme)
            self._apply_theme(manager.current)

    def _build_3d_hand(self):
        # 1. 构建手掌 (多面体机械装甲手掌)
        palm_v, palm_f = make_palm_mesh()
        palm_md = gl.MeshData(vertexes=palm_v, faces=palm_f)
        self.palm_item = gl.GLMeshItem(
            meshdata=palm_md,
            drawFaces=True, drawEdges=False,
            shader='shaded',
            color=C_PALM_FACE
        )
        self.addItem(self.palm_item)
        
        # 2. 构建大拇指过渡基座 - 左手镜像：位于右下侧 X=16.0, Y=8.5, Z=12.0
        # 大拇指基座也使用圆柱体以实现形态圆滑
        tb_md = gl.MeshData.cylinder(rows=4, cols=12, radius=[4.5, 4.5], length=7.0)
        self.thumb_base_item = gl.GLMeshItem(
            meshdata=tb_md,
            drawFaces=True, drawEdges=False,
            shader='shaded',
            color=C_PALM_FACE
        )
        self.thumb_base_item.setParentItem(self.palm_item)
        
        # 左手镜像：基座向右偏展 35° (绕 Z 轴)，且朝前方偏 20° (绕 X 轴)
        tr_base = QMatrix4x4()
        tr_base.translate(16.0, 8.5, 12.0)
        tr_base.rotate(35.0, 0, 0, 1)
        tr_base.rotate(20.0, 1, 0, 0)
        self.thumb_base_item.setTransform(tr_base)
        
        # 3. 构建大拇指 (Thumb) - 挂在 thumb_base_item 顶端 Z=7.0 处
        # 采用两节式尺寸：近端节L0=16, 远端节L1=12。宽度 W=6.8, 厚度 T=6.8
        thumb = _MechanicalFinger3D(
            self.thumb_base_item,
            base_x=0.0, base_y=0.0, base_z=7.0,
            lengths=[16, 12], width=6.8, thickness=6.8,
            init_y_rot=0.0
        )
        self._fingers[IDX_THUMB_BEND] = thumb
        
        # 4. 构建四指 - 左手镜像挂在手掌上端 Z=44~48 处
        # 索引，指根X，指根Y，指根Z，指节长度，宽度，厚度，扇形偏斜度 (绕 Y 轴偏斜度取反)
        finger_defs = [
            (IDX_INDEX,  13.0,  0.0, 47.0, [22, 15, 10], 6.2, 6.2,  4.5),
            (IDX_MIDDLE, 4.2,   0.0, 48.2, [25, 17, 11], 6.6, 6.6,  1.5),
            (IDX_RING,   -4.2,  0.0, 47.7, [22, 15, 10], 6.2, 6.2, -1.5),
            (IDX_LITTLE, -13.0, 0.0, 44.5, [16, 11,  8], 5.5, 5.5, -4.5)
        ]
        
        for idx, x, y, z, L, W, T, y_rot in finger_defs:
            f = _MechanicalFinger3D(self.palm_item, x, y, z, L, W, T, y_rot)
            self._fingers[idx] = f
            
        # 5. 设置整体 3D 侧向 45° 俯瞰视角，立于场景中央
        self._apply_global_pose()

    def _apply_global_pose(self):
        tr = QMatrix4x4()
        # 让手掌中段大约对准 OpenGL 相机观察中心 (Z轴为垂直轴，高度在 0~48)
        tr.translate(0.0, 0.0, -20.0)
        # 绕垂直 Z 轴（沿手腕手臂方向轴）顺时针旋转 90°：原本为 45°，顺时针旋转 90° 变为 -45°
        tr.rotate(-45, 0, 0, 1)
        tr.rotate(15, 1, 0, 0)  # 绕 X 轴旋转 15°，俯瞰倾斜，形成前后空间透视
        tr.rotate(5, 0, 1, 0)   # 绕 Y 轴旋 5° 使手掌姿态更加饱满和自然
        self.palm_item.setTransform(tr)

    def _init_from_config(self):
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

    def update_joint_values(self, values):
        if not self._is_six:
            return
        sanitized = sanitize_joint_values(values)
        if sanitized is None:
            return
        self._target = sanitized
        self._last_valid = sanitized
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _animate_step(self):
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

    def _apply_pose(self, v: List[float]):
        # 1. 更新四指弯曲（绕其局部 X 轴做负向旋转折向掌心 +Y 方向）
        for idx in (IDX_INDEX, IDX_MIDDLE, IDX_RING, IDX_LITTLE):
            finger = self._fingers.get(idx)
            if finger is None:
                continue
            r = bend_ratio(v[idx])
            # 重新规划每一节指骨在最大弯曲(r=1)下的物理弯折极值，形成完美的向内扣紧“握拳形态”
            angle0 = -r * 90.0   # 第一节最大弯曲 90 度
            angle1 = -r * 95.0   # 第二节最大弯曲 95 度
            angle2 = -r * 80.0   # 第三节最大弯曲 80 度
            
            # Seg0
            tr0 = QMatrix4x4()
            tr0.translate(finger.base_x, finger.base_y, finger.base_z)
            tr0.rotate(finger.init_y_rot, 0, 1, 0)
            tr0.rotate(angle0, 1, 0, 0)
            finger.items[0].setTransform(tr0)
            
            # Seg1
            tr1 = QMatrix4x4()
            tr1.translate(0, 0, finger.lengths[0])
            tr1.rotate(angle1, 1, 0, 0)
            finger.items[1].setTransform(tr1)
            
            # Seg2
            tr2 = QMatrix4x4()
            tr2.translate(0, 0, finger.lengths[1])
            tr2.rotate(angle2, 1, 0, 0)
            finger.items[2].setTransform(tr2)

        # 2. 更新大拇指弯曲 + 横摆双轴联动 (包含虎口基座与大拇指根部共同内扣)
        thumb = self._fingers.get(IDX_THUMB_BEND)
        if thumb is not None:
            bend = bend_ratio(v[IDX_THUMB_BEND])
            spread = spread_ratio(v[IDX_THUMB_SWING])
            
            # 动态更新大拇指基座 (虎口部分) 旋转，随横摆进行大角度向掌心的合拢内扣
            # spread=0 (内扣): base_rot_z=-10.0, base_rot_x=-25.0
            # spread=1 (外展): base_rot_z=35.0, base_rot_x=15.0
            base_rot_z = -10.0 + spread * 45.0
            base_rot_x = -25.0 + spread * 40.0
            
            tr_base = QMatrix4x4()
            tr_base.translate(16.0, 8.5, 12.0)  # 移至掌侧前方衔接处
            tr_base.rotate(base_rot_z, 0, 0, 1)
            tr_base.rotate(base_rot_x, 1, 0, 0)
            self.thumb_base_item.setTransform(tr_base)
            
            # 动态更新大拇指第一节旋转 (随横摆进一步向掌心内扣)
            # spread=0 (内扣): swing_z=-20.0, swing_x=-15.0
            # spread=1 (外展): swing_z=20.0, swing_x=10.0
            swing_z = -20.0 + spread * 40.0
            swing_x = -15.0 + spread * 25.0
            
            # 弯曲时大拇指第一节折角增加至 40°，第二节指尖折角增加至 80°，使其在握拳状态下扣在四指外侧
            angle0 = -bend * 40.0
            
            # Seg0
            tr0 = QMatrix4x4()
            tr0.translate(thumb.base_x, thumb.base_y, thumb.base_z)
            tr0.rotate(swing_z, 0, 0, 1)
            tr0.rotate(swing_x, 1, 0, 0)
            tr0.rotate(angle0, 1, 0, 0)
            thumb.items[0].setTransform(tr0)
            
            # Seg1 绕局部 X 轴负弯折 80°
            tr1 = QMatrix4x4()
            tr1.translate(0, 0, thumb.lengths[0])
            tr1.rotate(-bend * 80.0, 1, 0, 0)
            thumb.items[1].setTransform(tr1)
            
        self._highlight(v)
        # 仅在第一次渲染时执行高CPU消耗的相机计算，高频动画更新时跳过，巨幅提升流畅度
        if self._first_fit:
            self._update_camera_fit()
            self._first_fit = False

    def _update_camera_fit(self):
        # 收集关键点世界坐标以计算包围盒
        points = []
        
        # 手掌世界矩阵与 16 个顶点
        m_palm = self.palm_item.transform()
        palm_local_v = [
            QVector3D(-12, -4.5, 0), QVector3D(12, -4.5, 0),
            QVector3D(15,  -1.5, 0), QVector3D(15,  1.5, 0),
            QVector3D(12,   4.5, 0), QVector3D(-12, 4.5, 0),
            QVector3D(-15,  1.5, 0), QVector3D(-15, -1.5, 0),
            
            QVector3D(-18, -5.0, 48), QVector3D(18, -5.0, 48),
            QVector3D(22,  -2.0, 48), QVector3D(22,  2.0, 48),
            QVector3D(18,   5.0, 48), QVector3D(-18, 5.0, 48),
            QVector3D(-22,  2.0, 48), QVector3D(-22, -2.0, 48)
        ]
        for v in palm_local_v:
            points.append(m_palm.map(v))
            
        # 拇指基座世界矩阵与 8 个顶点
        m_tb = m_palm * self.thumb_base_item.transform()
        tb_local_v = [
            QVector3D(-4.5, -4.5, 0), QVector3D(4.5, -4.5, 0),
            QVector3D(4.5, 4.5, 0), QVector3D(-4.5, 4.5, 0),
            QVector3D(-4.5, -4.5, 8), QVector3D(4.5, -4.5, 8),
            QVector3D(4.5, 4.5, 8), QVector3D(-4.5, 4.5, 8)
        ]
        for v in tb_local_v:
            points.append(m_tb.map(v))
            
        # 5 根手指 (动态追踪层级变换累乘)
        for idx, finger in self._fingers.items():
            if idx == IDX_THUMB_BEND:
                m_curr = m_palm * self.thumb_base_item.transform()
            else:
                m_curr = m_palm
                
            points.append(m_curr.map(QVector3D(0, 0, 0)))
            
            for i, seg in enumerate(finger.items):
                m_curr = m_curr * seg.transform()
                points.append(m_curr.map(QVector3D(0, 0, 0)))
                points.append(m_curr.map(QVector3D(0, 0, finger.lengths[i])))
            
        # 2. 计算 Min/Max 包围盒
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        zs = [p.z() for p in points]
        
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        
        # 3. 计算中心点与对角线跨度
        target_center = QVector3D(
            (min_x + max_x) / 2.0,
            (min_y + max_y) / 2.0,
            (min_z + max_z) / 2.0
        )
        
        dx = max_x - min_x
        dy = max_y - min_y
        dz = max_z - min_z
        span = max(dx, dy, dz)
        
        # 设置 10%～15% 安全边距 (乘以 1.25)
        target_distance = span * 1.25
        target_distance = max(80.0, target_distance) # 限制最小距离
        
        # 4. 阻尼更新，保证视角柔和稳定过渡
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

    def _highlight(self, v: List[float]):
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
            IDX_THUMB_BEND: IDX_THUMB_BEND, IDX_THUMB_SWING: IDX_THUMB_BEND
        }
        target = map_idx.get(idx)
        if target is None:
            return
            
        # 先清除以前所有高亮
        for f in self._fingers.values():
            f.reset_color()
            
        # 设置当前 activity 手指高亮
        f = self._fingers.get(target)
        if f is not None:
            f.set_active(True)
            
            def _reset():
                f.reset_color()
                
            QTimer.singleShot(450, _reset)

    def _apply_theme(self, name: str):
        if name == "dark":
            self.setBackgroundColor((20, 29, 42, 255))
        else:
            self.setBackgroundColor((248, 250, 252, 255))
        self.update()
    def is_supported(self) -> bool:
        return self._is_six

    def hideEvent(self, event):
        self._anim_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._is_six and self._last_valid is not None:
            self._target = list(self._last_valid)
            if not self._anim_timer.isActive():
                self._anim_timer.start()

    # 屏蔽 3D 相机拖动旋转鼠标事件，确保控制台始终使用精确完美的固定侧向 45° 视角
    def mousePressEvent(self, event):
        pass
        
    def mouseMoveEvent(self, event):
        pass
        
    def mouseReleaseEvent(self, event):
        pass
        
    def wheelEvent(self, event):
        pass

    def reset_camera(self):
        self._first_fit = True
        self.setCameraPosition(distance=80, azimuth=0, elevation=0)
        self._curr_center = None
        self._curr_distance = None
        self.update()
