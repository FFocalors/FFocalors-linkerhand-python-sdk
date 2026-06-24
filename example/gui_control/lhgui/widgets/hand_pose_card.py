#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手部姿态卡片：HandPoseView + 精美摘要指标卡片。

外层圆角白卡，内层灰色 Viewport 容器 + 6 个统一 JointSummary 小卡片。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.icon_helper import get_icon
from lhgui.widgets.hand_pose_view import HandPoseView

SHORT_NAMES = {
    "大拇指弯曲": "拇弯",
    "大拇指横摆": "拇摆",
    "食指弯曲": "食指",
    "中指弯曲": "中指",
    "无名指弯曲": "无名",
    "小拇指弯曲": "小指"
}


class HandPoseCard(QWidget):
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("HandPoseCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hand_joint = hand_joint

        full_names = list(HAND_CONFIGS[hand_joint].joint_names)[:6]
        self.joint_names_short = [SHORT_NAMES.get(n, n[:2]) for n in full_names]
        self._build()
        signal_bus.joint_state_updated.connect(self._on_state)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # ── Header ──
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_container = QWidget()
        title_container.setStyleSheet("background:transparent;")
        tc_layout = QVBoxLayout(title_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(2)

        self.title_lbl = QLabel("实时姿态监控")
        self.title_lbl.setObjectName("CardTitle")
        tc_layout.addWidget(self.title_lbl)

        device_info = f"模型: {self.hand_joint} · 离线"
        self.subtitle_lbl = QLabel(device_info)
        self.subtitle_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        tc_layout.addWidget(self.subtitle_lbl)
        header.addWidget(title_container)

        header.addStretch()

        # 重置视角 → 统一的 IconActionButton
        self.reset_cam_btn = QPushButton("重置视角")
        self.reset_cam_btn.setProperty("category", "tool")
        self.reset_cam_btn.setCursor(Qt.PointingHandCursor)
        self.reset_cam_btn.setToolTip("将 3D 相机重置为默认视角")
        self.reset_cam_btn.clicked.connect(self._reset_camera)
        header.addWidget(self.reset_cam_btn)

        layout.addLayout(header)

        # ── Viewport 浅灰圆角容器 ──
        viewport = QFrame()
        viewport.setObjectName("HandViewport")
        vp_layout = QVBoxLayout(viewport)
        vp_layout.setContentsMargins(6, 6, 6, 6)
        vp_layout.setSpacing(0)

        self.pose_view = HandPoseView(self.hand_joint)
        vp_layout.addWidget(self.pose_view, stretch=1)
        layout.addWidget(viewport, stretch=1)

        # ── JointSummary Grid (2行×3列统一小卡片) ──
        summary_grid = QGridLayout()
        summary_grid.setSpacing(8)
        summary_grid.setContentsMargins(0, 0, 0, 0)

        self.summary_cards = []
        self.summary_labels = []
        self.summary_values = []

        for i, name in enumerate(self.joint_names_short):
            item = QFrame()
            item.setObjectName("JointSummaryItem")
            il = QVBoxLayout(item)
            il.setContentsMargins(8, 6, 8, 6)
            il.setSpacing(2)

            lbl = QLabel(name)
            lbl.setObjectName("JointSummaryLabel")
            lbl.setAlignment(Qt.AlignCenter)
            il.addWidget(lbl)

            val = QLabel("000")
            val.setObjectName("JointSummaryValue")
            val.setAlignment(Qt.AlignCenter)
            il.addWidget(val)

            self.summary_cards.append(item)
            self.summary_labels.append(lbl)
            self.summary_values.append(val)
            summary_grid.addWidget(item, i // 3, i % 3)

        layout.addLayout(summary_grid)

        # 极轻阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self, blur=16, offset=1)

        if not self.pose_view.is_supported():
            for item in self.summary_cards:
                item.hide()
            err_lbl = QLabel("当前型号不支持实时姿态图")
            err_lbl.setStyleSheet("color:#E5484D; font-weight:600; font-size:12px;")
            err_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(err_lbl)

    def _on_state(self, state: list):
        if not state or not self.pose_view.is_supported():
            return
        vals = list(state)[:6]

        self.pose_view.update_joint_values(vals)

        for i, v in enumerate(vals):
            if i < len(self.summary_values):
                self.summary_values[i].setText(f"{int(v):03d}")

    def _reset_camera(self):
        if hasattr(self.pose_view, "reset_camera"):
            self.pose_view.reset_camera()

    def _on_ui_state(self, snapshot):
        from lhgui.utils.ui_state import ConnectionState
        conn = snapshot.connection

        if conn == ConnectionState.CONNECTED:
            device_info = f"模型: {self.hand_joint} · 在线"
        elif conn == ConnectionState.OFFLINE:
            device_info = f"模型: {self.hand_joint} · 离线调试"
        elif conn == ConnectionState.CONNECTING:
            device_info = f"模型: {self.hand_joint} · 连接中…"
        else:
            device_info = f"模型: {self.hand_joint} · 未连接"

        self.subtitle_lbl.setText(device_info)
