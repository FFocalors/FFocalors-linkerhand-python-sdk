#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设动作面板：网格按钮 + 循环播放。"""
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QPushButton, QScrollArea, QLabel
)
from PyQt5.QtCore import Qt, QTimer

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus

LOOP_MS = 1000


class PresetPanel(QWidget):
    def __init__(self, hand_joint: str):
        super().__init__()
        self.hand_joint = hand_joint
        self.config = HAND_CONFIGS[hand_joint]
        self.preset_buttons: List[QPushButton] = []
        self.cycle_timer: QTimer = None
        self.cycle_index = -1
        self._build()
        signal_bus.preset_triggered.connect(self._apply)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("预设动作")
        title.setStyleSheet("font-weight:600;color:#1f2329;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setSpacing(8)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setAlignment(Qt.AlignTop)

        actions = self.config.preset_actions or {}
        for i, name in enumerate(actions.keys()):
            btn = QPushButton(name)
            btn.setProperty("category", "preset")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name, p=actions[name]: self._click(n, p))
            row, col = divmod(i, 2)
            grid.addWidget(btn, row, col)
            self.preset_buttons.append(btn)

        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        self.cycle_btn = QPushButton("循环预设动作")
        self.cycle_btn.setProperty("category", "primary")
        self.cycle_btn.setCursor(Qt.PointingHandCursor)
        self.cycle_btn.clicked.connect(self._toggle_cycle)
        layout.addWidget(self.cycle_btn)

    def _click(self, name: str, positions: List[int]):
        signal_bus.preset_triggered.emit(name, list(positions))
        signal_bus.connection_message.emit("info", f"预设动作：{name}")

    def _apply(self, name: str, positions: List[int]):
        # 高亮当前按钮
        self._clear_highlight()
        actions = self.config.preset_actions or {}
        names = list(actions.keys())
        if name in names:
            idx = names.index(name)
            if 0 <= idx < len(self.preset_buttons):
                btn = self.preset_buttons[idx]
                btn.setProperty("current", "true")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    def _toggle_cycle(self):
        if self.cycle_timer and self.cycle_timer.isActive():
            self.cycle_timer.stop()
            self.cycle_timer = None
            self.cycle_btn.setText("循环预设动作")
            self._clear_highlight()
            signal_bus.connection_message.emit("info", "已停止循环")
        else:
            actions = self.config.preset_actions or {}
            if not actions:
                signal_bus.connection_message.emit("warning", "当前型号无预设动作")
                return
            self.cycle_index = -1
            self.cycle_timer = QTimer(self)
            self.cycle_timer.timeout.connect(self._run_next)
            self.cycle_timer.start(LOOP_MS)
            self.cycle_btn.setText("停止循环")
            self._run_next()

    def _run_next(self):
        actions = self.config.preset_actions or {}
        names = list(actions.keys())
        if not names:
            return
        self.cycle_index = (self.cycle_index + 1) % len(names)
        name = names[self.cycle_index]
        self._click(name, actions[name])

    def _clear_highlight(self):
        for btn in self.preset_buttons:
            btn.setProperty("current", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def stop_cycle(self):
        if self.cycle_timer and self.cycle_timer.isActive():
            self.cycle_timer.stop()
            self.cycle_timer = None
            self.cycle_btn.setText("循环预设动作")
            self._clear_highlight()
