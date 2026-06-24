#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示页面：大号预设动作按钮。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState


_DEMO_PRIORITY = ["张开", "握拳", "OK", "点赞"]


class DemoPage(QWidget):
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("DemoPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hand_joint = hand_joint
        self.config = HAND_CONFIGS[hand_joint]
        self._buttons = []
        self._build()
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 32)
        outer.setSpacing(20)

        title = QLabel(f"Linker Hand 演示 · {self.hand_joint}")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        sub = QLabel("点击下方按钮执行预设动作（将真实下发到设备）")
        sub.setStyleSheet("color:#6b7280;")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)

        outer.addStretch()

        actions = self.config.preset_actions or {}
        ordered = [n for n in _DEMO_PRIORITY if n in actions]
        ordered += [n for n in actions.keys() if n not in ordered]

        grid = QGridLayout()
        grid.setSpacing(16)
        cols = 3
        for i, name in enumerate(ordered[:12]):
            btn = QPushButton(name)
            btn.setProperty("category", "demo")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(90)
            btn.setMinimumWidth(140)
            btn.clicked.connect(lambda _, n=name, p=actions[name]: self._fire(n, p))
            grid.addWidget(btn, i // cols, i % cols)
            self._buttons.append(btn)
        outer.addLayout(grid)

        outer.addStretch()

        exit_row = QHBoxLayout()
        exit_row.addStretch()
        exit_btn = QPushButton("退出演示模式")
        exit_btn.setProperty("category", "warning")
        exit_btn.setMinimumWidth(160)
        exit_btn.setCursor(Qt.PointingHandCursor)
        exit_btn.clicked.connect(lambda: signal_bus.demo_mode_toggled.emit(False))
        exit_row.addWidget(exit_btn)
        exit_row.addStretch()
        outer.addLayout(exit_row)

    def _fire(self, name: str, positions: list):
        signal_bus.preset_triggered.emit(name, list(positions))
        signal_bus.connection_message.emit("info", f"演示动作：{name}")

    def _on_ui_state(self, snapshot):
        enabled = snapshot.connection == ConnectionState.CONNECTED
        for btn in self._buttons:
            btn.setEnabled(enabled)

    def set_compact_mode(self, compact: bool):
        pass
