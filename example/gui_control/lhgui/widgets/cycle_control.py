#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循环动作控制器（紧凑卡片）。"""
from typing import List, Tuple
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
)
from PyQt5.QtCore import Qt, QTimer

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.utils.icon_helper import get_icon
from lhgui.widgets.status_badge import StatusBadge


class CycleControl(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("CycleControlCard")
        self._actions: List[Tuple[str, list]] = []
        self._index = 0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._run_next)
        self._build()
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel("循环动作")
        title.setObjectName("CardTitle")
        top.addWidget(title)
        self.badge = StatusBadge("空闲", level="disconnected")
        top.addWidget(self.badge)
        top.addStretch()
        layout.addLayout(top)

        self.current_lbl = QLabel("未运行")
        self.current_lbl.setObjectName("CycleCurrent")
        layout.addWidget(self.current_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.toggle_btn = QPushButton("开始循环")
        self.toggle_btn.setProperty("category", "primary")
        self.toggle_btn.setIcon(get_icon("play", 16))
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        btn_row.addWidget(self.toggle_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("category", "warning")
        self.stop_btn.setIcon(get_icon("stop", 16))
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_actions(self, actions: List[Tuple[str, list]]):
        self._actions = actions
        if self._active:
            self.stop()

    def _toggle(self):
        if self._active:
            self.stop()
        else:
            self.start()

    def start(self):
        if ui_state.snapshot.connection != ConnectionState.CONNECTED:
            signal_bus.connection_message.emit("warning", "设备未连接，无法循环")
            return
        if not self._actions:
            signal_bus.connection_message.emit("warning", "无预设动作可循环")
            return
        self._active = True
        ui_state.set_action_state(ActionState.CYCLE_RUNNING)
        self._index = 0
        self._run_next()
        self._timer.start()
        self._update_ui()

    def stop(self):
        self._active = False
        self._timer.stop()
        if ui_state.snapshot.action in (ActionState.CYCLE_RUNNING, ActionState.ACTION_RUNNING):
            ui_state.set_action_state(ActionState.IDLE)
        self._index = 0
        self._update_ui()
        signal_bus.connection_message.emit("info", "已停止循环")

    def _run_next(self):
        if not self._active:
            return
        if not self._actions:
            self.stop()
            return
        if self._index >= len(self._actions):
            self._index = 0
        name, positions = self._actions[self._index]
        self._index += 1
        self.current_lbl.setText(f"当前动作：{name}")
        signal_bus.preset_triggered.emit(name, list(positions))

    def _update_ui(self):
        if self._active:
            self.badge.set_level("running")
            self.badge.setText("循环中")
            self.toggle_btn.setText("停止循环")
            self.toggle_btn.setIcon(get_icon("stop", 16))
            self.toggle_btn.setProperty("category", "warning")
            self.stop_btn.setEnabled(True)
            if not self.current_lbl.text().startswith("当前动作"):
                self.current_lbl.setText("循环运行中")
        else:
            self.badge.set_level("disconnected")
            self.badge.setText("空闲")
            self.toggle_btn.setText("开始循环")
            self.toggle_btn.setIcon(get_icon("play", 16))
            self.toggle_btn.setProperty("category", "primary")
            self.stop_btn.setEnabled(False)
            self.current_lbl.setText("未运行")
        # repolish toggle button（category 动态属性变更）
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)

    def _on_ui_state(self, snapshot):
        self.toggle_btn.setEnabled(snapshot.connection == ConnectionState.CONNECTED)
        if snapshot.connection != ConnectionState.CONNECTED and self._active:
            self.stop()
            return
        if self._active:
            self._update_ui()
