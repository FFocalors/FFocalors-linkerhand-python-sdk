#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时曲线面板（可复用 matplotlib 封装）。"""
from collections import deque
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton
)
from PyQt5.QtCore import Qt, pyqtSignal

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.icon_helper import get_icon

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib import rcParams
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

rcParams["font.family"] = ["Microsoft YaHei", "sans-serif"]
rcParams["axes.unicode_minus"] = False


class WaveformPanel(QWidget):
    MAX_POINTS = 200
    fullscreen_requested = pyqtSignal()
    collapse_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._buf_state = deque(maxlen=self.MAX_POINTS)
        self._buf_current = deque(maxlen=self.MAX_POINTS)
        self._buf_speed = deque(maxlen=self.MAX_POINTS)
        self._show = {"state": True, "current": True, "speed": True}
        self._build()
        signal_bus.waveform_updated.connect(self._on_data)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 标题栏
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("实时数据曲线")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch()

        self.checks = {}
        for key, text, color in [
            ("state", "位置", "#4f8cff"),
            ("current", "电流", "#da3633"),
            ("speed", "速度", "#2ea043"),
        ]:
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.setProperty("color", color)
            cb.toggled.connect(lambda v, k=key: self._toggle(k, v))
            self.checks[key] = cb
            header.addWidget(cb)

        self.collapse_btn = QPushButton()
        self.collapse_btn.setProperty("category", "tool")
        self.collapse_btn.setIcon(get_icon("collapse", size=16))
        self.collapse_btn.setToolTip("折叠")
        self.collapse_btn.setFlat(True)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self.collapse_btn)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setProperty("category", "tool")
        self.fullscreen_btn.setIcon(get_icon("fullscreen", size=16))
        self.fullscreen_btn.setToolTip("全屏")
        self.fullscreen_btn.setFlat(True)
        self.fullscreen_btn.clicked.connect(self.fullscreen_requested.emit)
        header.addWidget(self.fullscreen_btn)

        layout.addLayout(header)

        self.figure = Figure(figsize=(6, 3), tight_layout=True, facecolor="white")
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor("white")
        self.ax.set_ylim(0, 260)
        self.ax.set_xlim(0, self.MAX_POINTS)
        self.ax.set_xlabel("采样点", color="#6b7280", fontsize=10)
        self.ax.set_ylabel("值", color="#6b7280", fontsize=10)
        self.ax.tick_params(colors="#6b7280", labelsize=9)
        self.ax.grid(True, color="#f3f4f6", linewidth=0.8)
        for spine in self.ax.spines.values():
            spine.set_color("#e5e7eb")

        self.line_state, = self.ax.plot([], [], color="#4f8cff", label="位置", linewidth=1.5)
        self.line_current, = self.ax.plot([], [], color="#da3633", label="电流", linewidth=1.5)
        self.line_speed, = self.ax.plot([], [], color="#2ea043", label="速度", linewidth=1.5)
        self.ax.legend(loc="upper left", fontsize=9, frameon=False)
        layout.addWidget(self.canvas, stretch=1)

    def _toggle(self, key: str, on: bool):
        self._show[key] = on
        self.line_state.set_visible(self._show["state"])
        self.line_current.set_visible(self._show["current"])
        self.line_speed.set_visible(self._show["speed"])
        if not self._collapsed:
            self.canvas.draw_idle()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.canvas.setVisible(not self._collapsed)
        for cb in self.checks.values():
            cb.setVisible(not self._collapsed)
        icon = "expand" if self._collapsed else "collapse"
        self.collapse_btn.setIcon(get_icon(icon, size=16))
        self.collapse_btn.setToolTip("展开" if self._collapsed else "折叠")
        self.collapse_changed.emit(self._collapsed)
        if not self._collapsed:
            self.canvas.draw_idle()

    def _on_data(self, data: dict):
        self._buf_state.append(_mean(data.get("state")))
        self._buf_current.append(_mean(data.get("current")))
        self._buf_speed.append(_mean(data.get("speed")))
        self.line_state.set_data(range(len(self._buf_state)), list(self._buf_state))
        self.line_current.set_data(range(len(self._buf_current)), list(self._buf_current))
        self.line_speed.set_data(range(len(self._buf_speed)), list(self._buf_speed))
        self.ax.set_xlim(0, max(self.MAX_POINTS, len(self._buf_state)))
        if not self._collapsed:
            self.canvas.draw_idle()

    def set_collapsed(self, collapsed: bool):
        if collapsed != self._collapsed:
            self._toggle_collapse()

    @property
    def collapsed(self) -> bool:
        return self._collapsed


def _mean(seq) -> float:
    if not seq:
        return 0.0
    try:
        vals = [float(v) for v in seq if v is not None and v >= 0]
    except Exception:
        return 0.0
    return sum(vals) / len(vals) if vals else 0.0
