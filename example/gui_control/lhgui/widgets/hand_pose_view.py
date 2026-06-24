#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时三维左手机械手姿态视图（基于 pyqtgraph.opengl）。

采用镜像手掌拓扑、左侧原生拇指以及槽型工业指节；每节指骨由碳黑
中轴、双侧金属夹板、横向轴销和嵌合式白色硅胶软垫组成。
"""
import math
from typing import List, Optional
import numpy as np

from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QMatrix4x4, QVector3D
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader
# 碳黑金属与白色硅胶软垫配色
C_PALM_DARK = (0.60, 0.62, 0.66, 1.0)          # 中灰色手掌装甲
C_FINGER_FRAME = (0.50, 0.52, 0.56, 1.0)       # 石墨灰指骨骨架与夹板
C_JOINT_DARK = (0.70, 0.72, 0.76, 1.0)         # 亮灰色销轴
C_PAD_LIGHT = (0.95, 0.96, 0.98, 1.0)          # 指腹与指尖的洁白软垫
C_PALM_PAD_LIGHT = (0.90, 0.91, 0.93, 1.0)     # 掌心白色防滑垫片

# 活动高亮配色 (高保真强调蓝)
C_PAD_ACTIVE = (0.72, 0.87, 1.0, 1.0)          # 软垫激活冰蓝
C_JOINT_ACTIVE = (0.28, 0.52, 0.96, 1.0)        # 关节激活蓝

# 内置 shaded 仅保留 20% 环境光，会把中灰材质压成近黑色。
# 此着色器保留方向光层次，同时将暗面抬到 55%，适配浅色控制台背景。
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

def make_palm_pad_mesh():
    """生成手掌正面的白色防滑防撞保护垫片网格。
    轻量化的 12 顶点，12 三角面单面结构，向 Y+ 方向偏移并稍微收缩边缘以呈现完美的拼装边缘与立体厚度感。
    """
    vertexes = np.array([
        # Layer 1: Z=8 (底部)
        [  9.0,  4.5,  8.0],  # 0
        [  3.0,  5.8,  8.0],  # 1
        [ -3.0,  5.8,  8.0],  # 2
        [ -9.0,  4.5,  8.0],  # 3

        # Layer 2: Z=24 (中部)
        [ 14.0,  5.8, 24.0],  # 4
        [  4.0,  8.3, 24.0],  # 5
        [ -4.0,  8.3, 24.0],  # 6
        [-12.0,  4.8, 24.0],  # 7

        # Layer 3: Z=45 (顶部)
        [ 14.0,  5.3, 45.0],  # 8
        [  4.5,  6.3, 45.0],  # 9
        [ -4.5,  6.3, 45.0],  # 10
        [-14.0,  5.3, 45.0],  # 11
    ], dtype=np.float32)

    # 向 Y+ 方向稍微推出（手心前侧），比原手掌正面稍微更厚更有层叠立体感
    vertexes[:, 1] += 0.35

    faces = []
    # 下层 3 个四边形 = 6 个三角面
    faces.append([0, 1, 5])
    faces.append([0, 5, 4])

    faces.append([1, 2, 6])
    faces.append([1, 6, 5])

    faces.append([2, 3, 7])
    faces.append([2, 7, 6])

    # 上层 3 个四边形 = 6 个三角面
    faces.append([4, 5, 9])
    faces.append([4, 9, 8])

    faces.append([5, 6, 10])
    faces.append([5, 10, 9])

    faces.append([6, 7, 11])
    faces.append([6, 11, 10])

    return vertexes, np.array(faces, dtype=np.uint32)

def _make_box_mesh(lx, ly, lz):
    """生成以原点为起始点 (0,0,0) 的长方体网格，沿 +Z 方向延伸 lz。
    顶点排列从底面 (Z=0) 到顶面 (Z=lz)，共 8 个顶点，12 个三角面。
    """
    hx, hy = lx / 2.0, ly / 2.0
    verts = np.array([
        [-hx, -hy, 0.0],  # 0 底左后
        [ hx, -hy, 0.0],  # 1 底右后
        [ hx,  hy, 0.0],  # 2 底右前
        [-hx,  hy, 0.0],  # 3 底左前
        [-hx, -hy, lz ],  # 4 顶左后
        [ hx, -hy, lz ],  # 5 顶右后
        [ hx,  hy, lz ],  # 6 顶右前
        [-hx,  hy, lz ],  # 7 顶左前
    ], dtype=np.float32)
    faces = np.array([
        [0,2,1],[0,3,2],   # 底面
        [4,5,6],[4,6,7],   # 顶面
        [0,5,4],[0,1,5],   # 后面
        [3,6,2],[3,7,6],   # 前面
        [0,7,3],[0,4,7],   # 左面
        [1,6,5],[1,2,6],   # 右面
    ], dtype=np.uint32)
    return verts, faces


class _MechanicalFinger3D:
    """工字槽型指节：中轴枢架、双侧夹板和嵌合式白色软垫。"""

    def __init__(self, parent_item, base_x, base_y, base_z, lengths, width, thickness, init_y_rot=0.0):
        self.lengths = lengths
        self.base_x = base_x
        self.base_y = base_y
        self.base_z = base_z
        self.init_y_rot = init_y_rot
        self.width = width
        self.thickness = thickness

        self.items = []     # 黑色中轴骨架，同时作为每节的旋转枢轴
        self.frames = []    # 所有黑色骨架、侧夹板与指尖卡箍
        self.joints = []    # 横卧圆柱销轴
        self.caps = []      # 保留以兼容旧调用
        self.pads = []      # 中间白色软垫
        self.tips = []      # 指尖白色圆头

        for i, L in enumerate(lengths):
            scale = 0.90 ** i
            wi = width * scale
            ti = thickness * scale
            is_tip_segment = i == len(lengths) - 1

            # 中轴作为层级枢轴，姿态更新不会覆盖子零件的装配偏移。
            cv, cf = _make_box_mesh(wi * 0.60, ti * 0.40, L)
            core = gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=cv, faces=cf),
                drawFaces=True, drawEdges=False,
                shader=INDUSTRIAL_SHADER, color=C_FINGER_FRAME
            )
            core.setParentItem(parent_item if i == 0 else self.items[-1])
            self.items.append(core)
            self.frames.append(core)

            # 双立碳黑金属侧夹板。
            for side in (-1.0, 1.0):
                pv, pf = _make_box_mesh(wi * 0.22, ti * 0.78, L)
                plate = gl.GLMeshItem(
                    meshdata=gl.MeshData(vertexes=pv, faces=pf),
                    drawFaces=True, drawEdges=False,
                    shader=INDUSTRIAL_SHADER, color=C_FINGER_FRAME
                )
                plate_tr = QMatrix4x4()
                plate_tr.translate(side * wi * 0.40, 0.0, 0.0)
                plate.setTransform(plate_tr)
                plate.setParentItem(core)
                self.frames.append(plate)

            # 横卧 X 轴销贯穿整个指节。
            axle_r = ti * 0.24
            axle_l = wi * 1.35
            axle_md = gl.MeshData.cylinder(
                rows=4, cols=10, radius=[axle_r, axle_r], length=axle_l
            )
            axle = gl.GLMeshItem(
                meshdata=axle_md, drawFaces=True, drawEdges=False,
                shader=INDUSTRIAL_SHADER, color=C_JOINT_DARK
            )
            axle_tr = QMatrix4x4()
            axle_tr.translate(-axle_l / 2.0, 0.0, axle_r)
            axle_tr.rotate(90.0, 0, 1, 0)
            axle.setTransform(axle_tr)
            axle.setParentItem(core)
            self.joints.append(axle)

            # 嵌合式白色硅胶软垫，向掌心正面凸出。
            sv, sf = _make_box_mesh(wi * 0.64, ti * 0.42, L * 0.86)
            pad = gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=sv, faces=sf),
                drawFaces=True, drawEdges=False,
                shader=INDUSTRIAL_SHADER, color=C_PAD_LIGHT
            )
            pad_tr = QMatrix4x4()
            pad_tr.translate(0.0, ti * 0.24, L * 0.07)
            pad.setTransform(pad_tr)
            pad.setParentItem(core)
            self.pads.append(pad)

            if is_tip_segment:
                # 指尖黑色卡箍压住软垫，强化工件装配线。
                kv, kf = _make_box_mesh(wi * 1.08, ti * 0.82, L * 0.28)
                clamp = gl.GLMeshItem(
                    meshdata=gl.MeshData(vertexes=kv, faces=kf),
                    drawFaces=True, drawEdges=False,
                    shader=INDUSTRIAL_SHADER, color=C_FINGER_FRAME
                )
                clamp.setParentItem(core)
                self.frames.append(clamp)

                tip_r = wi * 0.40
                tip_md = gl.MeshData.sphere(rows=8, cols=10, radius=tip_r)
                tip = gl.GLMeshItem(
                    meshdata=tip_md, drawFaces=True, drawEdges=False,
                    shader=INDUSTRIAL_SHADER, color=C_PAD_LIGHT
                )
                tip_tr = QMatrix4x4()
                tip_tr.translate(0.0, ti * 0.24, L + tip_r * 0.5)
                tip.setTransform(tip_tr)
                tip.setParentItem(core)
                self.tips.append(tip)

    def set_active(self, active: bool):
        pad_c = C_PAD_ACTIVE if active else C_PAD_LIGHT
        frame_c = C_JOINT_ACTIVE if active else C_FINGER_FRAME
        joint_c = C_JOINT_ACTIVE if active else C_JOINT_DARK

        for item in self.pads + self.tips:
            item.opts['color'] = pad_c
            item.update()
        for item in self.joints:
            item.opts['color'] = joint_c
            item.update()
        for item in self.frames:
            item.opts['color'] = frame_c
            item.update()

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
            shader=INDUSTRIAL_SHADER,
            color=C_PALM_DARK
        )
        self.addItem(self.palm_item)

        # 1.1 构建手掌前侧白色防滑垫片
        palm_pad_v, palm_pad_f = make_palm_pad_mesh()
        palm_pad_md = gl.MeshData(vertexes=palm_pad_v, faces=palm_pad_f)
        self.palm_pad_item = gl.GLMeshItem(
            meshdata=palm_pad_md,
            drawFaces=True, drawEdges=False,
            shader=INDUSTRIAL_SHADER,
            color=C_PALM_PAD_LIGHT
        )
        self.palm_pad_item.setParentItem(self.palm_item)

        # 2. 左手拇指过渡基座：在当前正面相机下位于屏幕左侧。
        tb_v, tb_f = _make_box_mesh(8.0, 8.0, 8.0)
        tb_md = gl.MeshData(vertexes=tb_v, faces=tb_f)
        self.thumb_base_item = gl.GLMeshItem(
            meshdata=tb_md,
            drawFaces=True, drawEdges=False,
            shader=INDUSTRIAL_SHADER,
            color=C_PALM_DARK
        )
        self.thumb_base_item.setParentItem(self.palm_item)

        # 默认按完全外展姿态建立；配置载入后由 _apply_pose 接管。
        tr_base = QMatrix4x4()
        tr_base.translate(16.0, 8.5, 12.0)
        tr_base.rotate(85.0, 0, 0, 1)
        tr_base.rotate(35.0, 1, 0, 0)
        self.thumb_base_item.setTransform(tr_base)

        # 两节式拇指，挂在虎口基座顶端。
        thumb = _MechanicalFinger3D(
            self.thumb_base_item,
            base_x=0.0, base_y=0.0, base_z=8.0,
            lengths=[17, 13], width=7.0, thickness=7.0,
            init_y_rot=0.0
        )
        self._fingers[IDX_THUMB_BEND] = thumb
        # 4. 构建四指 - 左手镜像挂在手掌上端 Z=44~48 处
        # 索引，指根X，指根Y，指根Z，指节长度，宽度，厚度，扇形偏斜度 (绕 Y 轴偏斜度取反)
        finger_defs = [
            (IDX_INDEX,   13.0, 0.0, 47.0, [22, 15, 10], 6.2, 6.2,  4.5),
            (IDX_MIDDLE,   4.2, 0.0, 48.2, [25, 17, 11], 6.6, 6.6,  1.5),
            (IDX_RING,    -4.2, 0.0, 47.7, [22, 15, 10], 6.2, 6.2, -1.5),
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

        # 2. 左手拇指弯曲 + 横摆联动
        thumb = self._fingers.get(IDX_THUMB_BEND)
        if thumb is not None:
            bend = bend_ratio(v[IDX_THUMB_BEND])
            spread = 1.0 - spread_ratio(v[IDX_THUMB_SWING])

            # 实际机械手：0 为最内扣，255 为最外摆。
            base_rot_z = 85.0 + spread * 95.0
            tr_base = QMatrix4x4()
            tr_base.translate(16.0, 8.5, 12.0)
            tr_base.rotate(base_rot_z, 0, 0, 1)
            # 固定镜像倾角让 Z 向指骨真正伸向左前，而非仅绕自身轴旋转。
            tr_base.rotate(35.0, 1, 0, 0)
            self.thumb_base_item.setTransform(tr_base)

            # 第一节继续向左前横摆；弯曲则朝掌心负向收拢。
            swing_z = 40.0 + spread * 60.0
            angle0 = -bend * 40.0
            tr0 = QMatrix4x4()
            tr0.translate(thumb.base_x, thumb.base_y, thumb.base_z)
            tr0.rotate(swing_z, 0, 0, 1)
            tr0.rotate(15.0, 1, 0, 0)
            tr0.rotate(angle0, 1, 0, 0)
            thumb.items[0].setTransform(tr0)

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
            QVector3D(-4.0, -4.0, 0), QVector3D(4.0, -4.0, 0),
            QVector3D(4.0, 4.0, 0), QVector3D(-4.0, 4.0, 0),
            QVector3D(-4.0, -4.0, 8), QVector3D(4.0, -4.0, 8),
            QVector3D(4.0, 4.0, 8), QVector3D(-4.0, 4.0, 8)
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
