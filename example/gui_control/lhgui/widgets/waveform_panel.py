#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时曲线面板（可复用 matplotlib 封装，统一 Fluent 卡片风格）。

开关使用紧凑彩色胶囊按钮；matplotlib 配色与 UI 统一。
"""
from collections import deque
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
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

    # 低饱和可分辨专业配色（柔和科技风，不再刺眼）
    COLORS = [
        "#5B8DEF",  # 拇弯 — 柔和蓝
        "#60A5C8",  # 拇摆 — 柔和青蓝
        "#5FAF8F",  # 食指 — 柔和青绿
        "#D6A25E",  # 中指 — 柔和橙金
        "#8B7FD1",  # 无名 — 柔和紫
        "#6D8AE6",  # 小指 — 柔和靛蓝
    ]

    def __init__(self, hand_joint: str = "O6", parent=None):
        super().__init__(parent)
        self.setObjectName("WaveformPanel")
        self.hand_joint = hand_joint
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

        from lhgui.config.constants import HAND_CONFIGS
        self.config = HAND_CONFIGS.get(hand_joint)
        self.joint_names = list(self.config.joint_names)[:6] if self.config else []
        self.joint_count = len(self.joint_names)

        from lhgui.widgets.hand_pose_card import SHORT_NAMES
        self.joint_names_short = [SHORT_NAMES.get(n, n[:2]) for n in self.joint_names]

        self._buf_joints = [deque(maxlen=self.MAX_POINTS) for _ in range(self.joint_count)]
        self._show = [True] * self.joint_count

        self._build()
        signal_bus.waveform_updated.connect(self._on_data)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("实时关节曲线")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch()

        # 紧凑胶囊开关按钮（低饱和 filter-chip 风格）
        self.toggles = []
        _JOINT_LABELS = ["拇弯", "拇摆", "食指", "中指", "无名", "小指"]
        for i in range(self.joint_count):
            name = _JOINT_LABELS[i] if i < len(_JOINT_LABELS) else self.joint_names_short[i]
            color = self.COLORS[i % len(self.COLORS)]
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"开关 {name} 曲线")
            btn.setFixedHeight(22)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid #E2E8F0;
                    border-radius: 11px;
                    padding: 1px 9px;
                    font-size: 11px;
                    font-weight: 500;
                    background: #F8FAFC;
                    color: #64748B;
                }}
                QPushButton:hover {{
                    border-color: #CBD5E1;
                    color: #1E293B;
                    background: #F1F5F9;
                }}
                QPushButton:checked {{
                    color: {color};
                    border-color: {color};
                    background: {color}12;
                    font-weight: 600;
                }}
                QPushButton:checked:hover {{
                    background: {color}1C;
                }}
            """)
            btn.toggled.connect(lambda checked, idx=i: self._toggle(idx, checked))
            self.toggles.append(btn)
            header.addWidget(btn)

        # 工具按钮
        self.collapse_btn = QPushButton()
        self.collapse_btn.setProperty("category", "tool")
        self.collapse_btn.setIcon(get_icon("collapse", size=16))
        self.collapse_btn.setToolTip("折叠")
        self.collapse_btn.setFlat(True)
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        header.addWidget(self.collapse_btn)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setProperty("category", "tool")
        self.fullscreen_btn.setIcon(get_icon("fullscreen", size=16))
        self.fullscreen_btn.setToolTip("全屏")
        self.fullscreen_btn.setFlat(True)
        self.fullscreen_btn.setFixedSize(28, 28)
        self.fullscreen_btn.clicked.connect(self._enter_fullscreen)
        header.addWidget(self.fullscreen_btn)

        layout.addLayout(header)

        # ── Matplotlib 图表 ──
        self.figure = Figure(figsize=(6, 3), tight_layout=True, facecolor="#FAFBFD")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(130)
        self.canvas.setMaximumHeight(210)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor("#FAFBFD")
        self.ax.set_ylim(0, 260)
        self.ax.set_xlim(0, self.MAX_POINTS)
        self.ax.set_xlabel("采样点", color="#94A3B8", fontsize=8)
        self.ax.set_ylabel("反馈值", color="#94A3B8", fontsize=8)
        self.ax.tick_params(colors="#94A3B8", labelsize=7)
        self.ax.grid(True, color="#E8EDF3", linewidth=0.5, alpha=0.7)

        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['left'].set_color("#DCE3EC")
        self.ax.spines['bottom'].set_color("#DCE3EC")

        self.lines = []
        for i in range(self.joint_count):
            color = self.COLORS[i % len(self.COLORS)]
            name = self.joint_names_short[i]
            line, = self.ax.plot([], [], color=color, label=name, linewidth=1.6, alpha=0.85)
            self.lines.append(line)

        layout.addWidget(self.canvas, stretch=1)

    def _toggle(self, idx: int, on: bool):
        if idx < len(self._show):
            self._show[idx] = on
            self.lines[idx].set_visible(on)
            if not self._collapsed:
                self.canvas.draw_idle()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.canvas.setVisible(not self._collapsed)
        for btn in self.toggles:
            btn.setVisible(not self._collapsed)
        icon = "expand" if self._collapsed else "collapse"
        self.collapse_btn.setIcon(get_icon(icon, size=16))
        self.collapse_btn.setToolTip("展开" if self._collapsed else "折叠")
        self.collapse_changed.emit(self._collapsed)
        if not self._collapsed:
            self.canvas.draw_idle()

    def _on_data(self, data: dict):
        state = data.get("state")
        if not isinstance(state, (list, tuple)) or len(state) < self.joint_count:
            return

        for i in range(self.joint_count):
            self._buf_joints[i].append(float(state[i]))
            self.lines[i].set_data(range(len(self._buf_joints[i])), list(self._buf_joints[i]))

        max_len = max(len(buf) for buf in self._buf_joints) if self._buf_joints else 0
        self.ax.set_xlim(0, max(self.MAX_POINTS, max_len))

        all_vals = []
        for i in range(self.joint_count):
            if self._show[i]:
                all_vals.extend(list(self._buf_joints[i]))

        if all_vals:
            ymin = min(all_vals)
            ymax = max(all_vals)
            margin = (ymax - ymin) * 0.15 if ymax != ymin else 15.0
            self.ax.set_ylim(ymin - margin, ymax + margin)
        else:
            self.ax.set_ylim(0, 260)

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
        self.canvas.setMaximumHeight(16777215)

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
        self._dialog.setWindowTitle("实时关节数据曲线 - 全屏监控")
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

        self.canvas.setMaximumHeight(210)
        self.set_collapsed(self._prev_collapsed)
        self.show()
        self.raise_()
        self.canvas.draw_idle()

        self._dialog = None
