#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示模式：大按钮触发常用预设，隐藏调试细节。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus

_DEMO_KEYS = ["张开", "握拳", "OK", "点赞"]


class DemoPanel(QWidget):
    def __init__(self, hand_joint: str):
        super().__init__()
        self.hand_joint = hand_joint
        self.config = HAND_CONFIGS[hand_joint]
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)

        title = QLabel(f"Linker Hand 演示 · {self.hand_joint}")
        title.setStyleSheet("font-size:26px;font-weight:600;color:#1664ff;")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        sub = QLabel("点击下方按钮执行预设动作")
        sub.setStyleSheet("font-size:14px;color:#86909c;")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)

        outer.addStretch()

        actions = self.config.preset_actions or {}
        # 优先展示常用，再补齐其余
        ordered = [k for k in _DEMO_KEYS if k in actions]
        ordered += [k for k in actions.keys() if k not in ordered]
        grid = QGridLayout()
        grid.setSpacing(16)
        cols = 3
        for i, name in enumerate(ordered[:12]):
            btn = QPushButton(name)
            btn.setProperty("category", "demo")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(80)
            btn.clicked.connect(lambda _, n=name, p=actions[name]: self._fire(n, p))
            row, col = divmod(i, cols)
            grid.addWidget(btn, row, col)
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

    def _fire(self, name, positions):
        signal_bus.preset_triggered.emit(name, list(positions))
        signal_bus.connection_message.emit("info", f"演示动作：{name}")
