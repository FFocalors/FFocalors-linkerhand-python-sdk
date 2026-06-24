#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关节控制面板（现代产品级扁平列表容器）。

每行仅保留关节名称、目标值和一条高质量滑动条，不再显示冗余反馈值。
"""
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState, PlaybackState
from lhgui.widgets.joint_row import JointRow


class JointPanel(QWidget):
    values_changed = pyqtSignal(list)   # 当前所有目标值

    def __init__(self, hand_joint: str):
        super().__init__()
        self.setObjectName("JointControlCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hand_joint = hand_joint
        self.config = HAND_CONFIGS[hand_joint]
        self.rows: List[JointRow] = []
        self._build()
        signal_bus.joint_state_updated.connect(self._on_feedback)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 6)
        layout.setSpacing(0)

        # ── 标题 ──
        title = QLabel("关节控制")
        title.setObjectName("CardTitle")
        title.setStyleSheet("padding-left: 12px; padding-right: 12px;")
        layout.addWidget(title)

        # 标题与列表间距
        spacer = QWidget()
        spacer.setFixedHeight(8)
        spacer.setStyleSheet("background: transparent;")
        layout.addWidget(spacer)

        # ── 滚动区域 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none; padding: 0 12px;")

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        vbox = QVBoxLayout(content)
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)

        for i, (name, init) in enumerate(zip(self.config.joint_names, self.config.init_pos)):
            row = JointRow(i, name, 0, 255, init)
            row.value_changed.connect(self._on_row_changed)
            vbox.addWidget(row)
            self.rows.append(row)

        vbox.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # 极轻卡片阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self, blur=16, offset=1)

    def _on_row_changed(self, _):
        values = self.get_values()
        self.values_changed.emit(values)
        signal_bus.finger_move_requested.emit(values)

    def _on_feedback(self, state: list):
        if not state:
            return
        for i, row in enumerate(self.rows):
            if i < len(state):
                row.set_feedback(state[i])

    def _on_ui_state(self, snapshot):
        enabled = (snapshot.connection in (ConnectionState.CONNECTED, ConnectionState.OFFLINE)
                   and snapshot.playback == PlaybackState.IDLE)
        for row in self.rows:
            row.set_enabled(enabled)

    def get_values(self) -> List[int]:
        return [r.value() for r in self.rows]

    def set_values(self, values: List[int], emit: bool = False):
        for i, v in enumerate(values):
            if i < len(self.rows):
                self.rows[i].set_value(int(v), emit=False)
        if emit:
            signal_bus.finger_move_requested.emit(self.get_values())
