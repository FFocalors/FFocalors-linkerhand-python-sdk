#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时二维机械手姿态图（重写数字孪生版）。

机械结构设计：模块化机械指节，装配感连杆，带发光销轴关节点。
完全去除廉价线框感，利用父子层级变换保证弯曲时决不脱节。
数据映射明确，不伪造真实传感器。
"""
import math
from typing import List, Optional

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QTransform
)
from PyQt5.QtWidgets import QGraphicsPathItem, QGraphicsEllipseItem


# 低饱和科技感配色
C_PALM_FILL = QColor("#f1f5f9")
C_PALM_BORDER = QColor("#cbd5e1")
C_FINGER_FILL = QColor("#e2e8f0")
C_FINGER_BORDER = QColor("#94a3b8")
C_JOINT = QColor("#64748b")
C_ACTIVE = QColor("#4f8cff")
C_ACTIVE_BG = QColor("#dbeafe")

# 关节索引
IDX_THUMB_BEND = 0; IDX_THUMB_SWING = 1
IDX_INDEX = 2; IDX_MIDDLE = 3; IDX_RING = 4; IDX_LITTLE = 5

# 弯曲映射: 255=张开(0 bend), 0=握拳(1 bend)
def bend_ratio(v): return (255.0 - max(0.0, min(255.0, v))) / 255.0
def spread_ratio(v): return max(0.0, min(255.0, v)) / 255.0


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


class _MechanicalFinger:
    """一组机械指节，带销轴关节点，且内部自带装饰刻线以增强装配感。"""
    def __init__(self, parent_item: QGraphicsPathItem, base_x: float, base_y: float,
                 lengths: List[float], widths: List[float]):
        self.items: List[QGraphicsPathItem] = []
        self.joints: List[QGraphicsEllipseItem] = []
        self.decorations: List[QGraphicsPathItem] = []
        self.lengths = lengths

        # 构建指节
        for i, (L, W) in enumerate(zip(lengths, widths)):
            # 外部骨架
            path = QPainterPath()
            tip_w = W * 0.8
            # 带轻微斜角与内收的机械倒角结构
            path.moveTo(-W / 2, 0)
            path.lineTo(-W / 2, -L * 0.7)
            path.lineTo(-tip_w / 2, -L)
            path.lineTo(tip_w / 2, -L)
            path.lineTo(W / 2, -L * 0.7)
            path.lineTo(W / 2, 0)
            path.closeSubpath()

            item = QGraphicsPathItem(path)
            item.setPen(QPen(C_FINGER_BORDER, 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            item.setBrush(QBrush(C_FINGER_FILL))
            
            # 父子层级变换——这是旋转不脱节的关键
            item.setTransformOriginPoint(0.0, 0.0)
            if i == 0:
                item.setPos(base_x, base_y)
                item.setParentItem(parent_item)
            else:
                item.setParentItem(self.items[i - 1])
                item.setPos(0.0, -lengths[i - 1])
            self.items.append(item)

            # 内饰雕刻线（增加数字孪生质感）
            dec_path = QPainterPath()
            dec_path.moveTo(0, -L * 0.15)
            dec_path.lineTo(0, -L * 0.8)
            dec_item = QGraphicsPathItem(dec_path, item)
            dec_item.setPen(QPen(QColor("#cbd5e1"), 1.0, Qt.DashLine))
            self.decorations.append(dec_item)

        # 铰链连接点
        for i in range(1, len(self.items)):
            # 铰链销轴应位于当前指节的基部 (0.0, 0.0)，即相邻指节的转动连接中心
            joint = QGraphicsEllipseItem(-4.0, -4.0, 8.0, 8.0, self.items[i])
            joint.setPos(0.0, 0.0)
            joint.setBrush(QBrush(C_JOINT))
            joint.setPen(QPen(Qt.transparent))
            self.joints.append(joint)

        # 指根销轴
        root_joint = QGraphicsEllipseItem(-4.5, -4.5, 9.0, 9.0, self.items[0])
        root_joint.setPos(0.0, 0.0)
        root_joint.setBrush(QBrush(C_JOINT))
        root_joint.setPen(QPen(Qt.transparent))
        self.joints.insert(0, root_joint)

    def set_parts_rotation(self, start: int, ratios: List[float], max_deg: float = 75.0):
        """为特定节设置旋转角度。"""
        for i, r in enumerate(ratios):
            idx = start + i
            if idx < len(self.items):
                r = max(0.0, min(1.0, r))
                self.items[idx].setRotation(r * max_deg)

    def reset_color(self):
        for it in self.items:
            it.setBrush(QBrush(C_FINGER_FILL))
            it.setPen(QPen(C_FINGER_BORDER, 1.2))
        for dec in self.decorations:
            dec.setPen(QPen(QColor("#cbd5e1"), 1.0, Qt.DashLine))
        for j in self.joints:
            j.setBrush(QBrush(C_JOINT))

    def set_active(self, active: bool):
        if active:
            for it in self.items:
                it.setBrush(QBrush(C_ACTIVE_BG))
                it.setPen(QPen(C_ACTIVE, 1.6))
            for dec in self.decorations:
                dec.setPen(QPen(QColor("#93c5fd"), 1.0, Qt.SolidLine))
            for j in self.joints:
                j.setBrush(QBrush(C_ACTIVE))


class HandPoseView(QGraphicsView):
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

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background:transparent;border:none;")
        self.setFrameShape(self.NoFrame)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        # 场景边界：留足空间容纳3D透视变换后的手掌及弯曲指尖
        self.setSceneRect(-30, -30, 340, 420)

        self._current = [0.0] * 6
        self._target = [0.0] * 6
        self._last_valid: Optional[List[float]] = None
        self._fingers = {}

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(20)
        self._anim_timer.timeout.connect(self._animate_step)

        if self._is_six:
            self._build_hand()
            self._init_from_config()

        from lhgui.utils.signal_bus import signal_bus
        signal_bus.joint_state_updated.connect(self.update_joint_values)

    def _build_hand(self):
        # 1. 机械掌骨外形——比原来单调的梯形大方块更符合自然解剖学与机械拼装美感
        palm = QPainterPath()
        # 掌骨外缘折线 (X轴平移+40px)
        palm.moveTo(120, 160)
        palm.lineTo(108, 240)
        palm.lineTo(100, 275)
        palm.quadTo(100, 310, 125, 315)
        palm.lineTo(245, 315)
        palm.quadTo(265, 310, 265, 275)
        palm.lineTo(265, 170)
        # 上边缘有拱起，用来容纳指根圆弧分布
        palm.quadTo(190, 142, 120, 160)
        palm.closeSubpath()

        self._palm_item = QGraphicsPathItem(palm)
        self._palm_item.setBrush(QBrush(C_PALM_FILL))
        self._palm_item.setPen(QPen(C_PALM_BORDER, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self._scene.addItem(self._palm_item)

        # 掌心装饰槽
        core_decor = QPainterPath()
        core_decor.moveTo(150, 200)
        core_decor.lineTo(220, 200)
        core_decor.lineTo(235, 260)
        core_decor.lineTo(135, 260)
        core_decor.closeSubpath()
        self._core_item = QGraphicsPathItem(core_decor, self._palm_item)
        self._core_item.setPen(QPen(QColor("#cbd5e1"), 1.0, Qt.DashLine))
        self._core_item.setBrush(QBrush(QColor("#f8fafc")))

        # 2. 拇指——位于手掌左下侧边，角度斜向上
        self._thumb_base_x = 104
        self._thumb_base_y = 238
        # 适当调整大拇指长度与宽度，使其大小更自然、比例更协调
        thumb = _MechanicalFinger(
            self._palm_item, self._thumb_base_x, self._thumb_base_y,
            lengths=[42, 30, 22],
            widths=[16, 14, 11]
        )
        # 初始倾斜
        thumb.items[0].setRotation(-35)
        self._fingers[IDX_THUMB_BEND] = thumb
        self._thumb = thumb

        # 3. 四指——在掌顶部边缘圆弧分布
        # 索引，指根X (平移+40px)，指根Y，各指节长度，各指节宽度
        finger_defs = [
            (IDX_INDEX, 140, 154, [62, 38, 25], [16, 14, 11]),
            (IDX_MIDDLE, 176, 148, [70, 42, 28], [17, 15, 12]),
            (IDX_RING, 212, 152, [62, 36, 24], [16, 14, 11]),
            (IDX_LITTLE, 244, 162, [48, 28, 20], [13, 11, 9]),
        ]
        for idx, x, y, L, W in finger_defs:
            f = _MechanicalFinger(self._palm_item, x, y, L, W)
            # 各指稍微向外呈扇形发散
            f.items[0].setRotation((idx - 3.5) * 5.0) 
            self._fingers[idx] = f

        # 模拟手掌绕竖直轴(Y轴)旋转 45 度的 3D 透视效果
        # X缩放 cos(45) 实现水平透视缩短
        # 垂直剪切(shear) 使近侧(小指/右侧)偏低、远侧(拇指/左侧)偏高
        # 两者叠加产生可信的 3D 深度错觉
        cos45 = math.cos(math.radians(45))
        t = QTransform()
        cx = 182.5
        t.translate(cx, 0)
        t.scale(cos45, 1.0)
        t.shear(0, 0.20)
        t.translate(-cx, 0)
        self._palm_item.setTransform(t)

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
        # 视觉弯曲分配比例：根节40%，中节35%，末节25%
        alloc = [0.40, 0.35, 0.25]
        
        # 1. 渲染四指弯曲（各指只有一个弯曲数据）
        for idx in (IDX_INDEX, IDX_MIDDLE, IDX_RING, IDX_LITTLE):
            finger = self._fingers.get(idx)
            if finger is None:
                continue
            r = bend_ratio(v[idx])
            # 基本倾斜加弯曲角度叠加
            base_rot = (idx - 3.5) * 5.0
            # 纵向卷曲: 135°总旋转使手指真正卷曲至朝下
            # 经 X缩放+剪切 后视觉上呈现向掌心自然收拢
            finger.items[0].setRotation(base_rot + r * 135.0 * alloc[0])
            finger.items[1].setRotation(r * 135.0 * alloc[1])
            finger.items[2].setRotation(r * 135.0 * alloc[2])

        # 2. 渲染大拇指（横摆 + 弯曲）
        thumb = self._fingers.get(IDX_THUMB_BEND)
        if thumb is not None:
            bend = bend_ratio(v[IDX_THUMB_BEND])
            spread = spread_ratio(v[IDX_THUMB_SWING])
            # swing 横摆: 根部平面倾斜度从 -30° 到 -70° 变化
            swing_rot = -30.0 - spread * 40.0
            thumb.items[0].setRotation(swing_rot)
            # 根据横摆微调指根位置以避免穿模
            thumb.items[0].setX(self._thumb_base_x - spread * 6.0)
            thumb.items[0].setY(self._thumb_base_y + spread * 3.0)
            # 拇指剩余两节按弯曲度分配旋转(增大至90°匹配四指卷曲幅度)
            thumb.items[1].setRotation(bend * 90.0 * 0.45)
            thumb.items[2].setRotation(bend * 90.0 * 0.55)

        self._highlight(v)

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
        map_idx = {IDX_INDEX: IDX_INDEX, IDX_MIDDLE: IDX_MIDDLE,
                   IDX_RING: IDX_RING, IDX_LITTLE: IDX_LITTLE,
                   IDX_THUMB_BEND: IDX_THUMB_BEND, IDX_THUMB_SWING: IDX_THUMB_BEND}
        target = map_idx.get(idx)
        if target is None:
            return
        for f in self._fingers.values():
            f.reset_color()
        f = self._fingers.get(target)
        if f is not None:
            f.set_active(True)
            QTimer.singleShot(450, lambda: f.reset_color() if hasattr(f, 'reset_color') else None)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
