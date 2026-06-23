#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时曲线面板（可复用 matplotlib 封装）。"""
from collections import deque
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QDialog, QShortcut
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence

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
        self.setObjectName("WaveformPanel")
        self._collapsed = False
        self._is_fullscreen = False
        self._placeholder = QWidget()
        self._placeholder.setMinimumHeight(150)
        self._dialog = None
        self._orig_parent = None
        self._orig_layout = None
        self._orig_index = -1
        self._orig_stretch = 0
        self._prev_collapsed = False

        self._buf_state = deque(maxlen=self.MAX_POINTS)
        self._buf_current = deque(maxlen=self.MAX_POINTS)
        self._buf_speed = deque(maxlen=self.MAX_POINTS)
        self._show = {"state": True, "current": True, "speed": True}
        self._build()
        signal_bus.waveform_updated.connect(self._on_data)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

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
        self.fullscreen_btn.clicked.connect(self._enter_fullscreen)
        header.addWidget(self.fullscreen_btn)

        layout.addLayout(header)

        self.figure = Figure(figsize=(6, 3), tight_layout=True, facecolor="white")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(120)
        self.canvas.setMaximumHeight(220)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor("white")
        self.ax.set_ylim(0, 260)
        self.ax.set_xlim(0, self.MAX_POINTS)
        self.ax.set_xlabel("采样点", color="#64748b", fontsize=9)
        self.ax.set_ylabel("值", color="#64748b", fontsize=9)
        self.ax.tick_params(colors="#64748b", labelsize=8)
        self.ax.grid(True, color="#f1f5f9", linewidth=0.6)
        
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['left'].set_color("#cbd5e1")
        self.ax.spines['bottom'].set_color("#cbd5e1")

        self.line_state, = self.ax.plot([], [], color="#4f82ff", label="位置", linewidth=1.5)
        self.line_current, = self.ax.plot([], [], color="#e14c4c", label="电流", linewidth=1.5)
        self.line_speed, = self.ax.plot([], [], color="#22a06b", label="速度", linewidth=1.5)
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

    def _enter_fullscreen(self):
        if self._is_fullscreen:
            return
        self._is_fullscreen = True
        self._prev_collapsed = self._collapsed
        self.set_collapsed(False)
        self.canvas.setMaximumHeight(16777215)  # 解除高度限制

        self._orig_parent = self.parentWidget()
        if not self._orig_parent:
            return
        self._orig_layout = self._orig_parent.layout()
        if not self._orig_layout:
            return
        self._orig_index = self._orig_layout.indexOf(self)
        self._orig_stretch = self._orig_layout.stretch(self._orig_index)

        self._orig_layout.insertWidget(self._orig_index, self._placeholder)
        self._orig_layout.setStretch(self._orig_layout.indexOf(self._placeholder), self._orig_stretch)

        self._orig_layout.removeWidget(self)
        self.hide()

        self._dialog = QDialog(self.window())
        self._dialog.setWindowTitle("实时数据曲线 - 全屏监控")
        self._dialog.setWindowState(Qt.WindowMaximized)
        dlg_layout = QVBoxLayout(self._dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(0)
        dlg_layout.addWidget(self)

        self._dialog.finished.connect(self._exit_fullscreen)
        QShortcut(QKeySequence("Esc"), self._dialog, activated=self._exit_fullscreen)

        self.show()
        self._dialog.showMaximized()

    def exit_fullscreen(self):
        self._exit_fullscreen()

    def _exit_fullscreen(self):
        if not self._is_fullscreen:
            return
        self._is_fullscreen = False

        if self._dialog:
            try:
                self._dialog.finished.disconnect(self._exit_fullscreen)
            except Exception:
                pass
            self._dialog.close()

        self.hide()
        dlg_layout = self._dialog.layout()
        if dlg_layout:
            dlg_layout.removeWidget(self)

        self.setParent(self._orig_parent)

        if self._orig_layout:
            idx = self._orig_layout.indexOf(self._placeholder)
            self._orig_layout.removeWidget(self._placeholder)
            self._placeholder.setParent(None)
            if 0 <= self._orig_index <= self._orig_layout.count():
                self._orig_layout.insertWidget(self._orig_index, self)
            else:
                self._orig_layout.addWidget(self)
            self._orig_layout.setStretch(self._orig_layout.indexOf(self), self._orig_stretch)

        self.canvas.setMaximumHeight(220)  # 还原高度限制
        self.set_collapsed(self._prev_collapsed)
        self.show()
        self.raise_()
        self.canvas.draw_idle()

        self._dialog = None


def _mean(seq) -> float:
    if not seq:
        return 0.0
    try:
        vals = [float(v) for v in seq if v is not None and v >= 0]
    except Exception:
        return 0.0
    return sum(vals) / len(vals) if vals else 0.0
