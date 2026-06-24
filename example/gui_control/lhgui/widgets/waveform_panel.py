#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时曲线面板（可复用 matplotlib 封装，统一 Fluent 数据面板风格）。

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

    # 同时定义折线、选中底色与边框色，避免依赖透明十六进制颜色。
    PALETTE = [
        ("#5B7FC7", "#EDF3FC", "#B8C9EA"),  # 拇弯 — 雾蓝
        ("#558EAA", "#EDF6F8", "#B8D5E0"),  # 拇摆 — 灰青
        ("#568F78", "#EEF7F3", "#B7D8CA"),  # 食指 — 鼠尾草绿
        ("#B78345", "#FBF4E9", "#E4C9A3"),  # 中指 — 沙金
        ("#756AA8", "#F3F0FA", "#CAC3E1"),  # 无名 — 灰紫
        ("#6279B7", "#EFF2FA", "#BEC9E5"),  # 小指 — 柔靛
    ]
    COLORS = [entry[0] for entry in PALETTE]
    DARK_PALETTE = [
        ("#86A8E6", "#1C2B45", "#415C86"),
        ("#75B2CC", "#18313D", "#3C6677"),
        ("#76B99D", "#19352F", "#3D6B5B"),
        ("#D5A665", "#382B19", "#745A34"),
        ("#A194D8", "#2A2540", "#5C527F"),
        ("#879DDB", "#202D49", "#465D8D"),
    ]
    def __init__(self, hand_joint: str = "O6", parent=None):
        super().__init__(parent)
        self.setObjectName("WaveformPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
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
        self._latest_targets = list(self.config.init_pos) if self.config else [250] * self.joint_count
        if len(self._latest_targets) < self.joint_count:
            self._latest_targets.extend([250] * (self.joint_count - len(self._latest_targets)))
        self._buf_targets = [deque(maxlen=self.MAX_POINTS) for _ in range(self.joint_count)]
        self._curve_markers = []
        self._show = [True] * self.joint_count

        self._build()
        signal_bus.waveform_updated.connect(self._on_data)
        signal_bus.finger_move_requested.connect(self._on_finger_move_requested)
        signal_bus.grasp_curve_event.connect(self._on_grasp_curve_event)
        signal_bus.grasp_state_changed.connect(self._on_grasp_state_changed)
        from lhgui.styles.theme_manager import get_theme_manager
        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(self._apply_theme)
            self._apply_theme(manager.current)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        # ── Header：标题与筛选器分层，避免图例和工具按钮挤在一行 ──
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel("实时关节曲线")
        title.setObjectName("CardTitle")
        title_row.addWidget(title)

        subtitle = QLabel("最近 200 个采样点")
        subtitle.setObjectName("WaveformMeta")
        title_row.addWidget(subtitle)
        title_row.addStretch()

        self.collapse_btn = QPushButton()
        self.collapse_btn.setProperty("category", "tool")
        self.collapse_btn.setIcon(get_icon("collapse", size=16))
        self.collapse_btn.setToolTip("折叠")
        self.collapse_btn.setFlat(True)
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        title_row.addWidget(self.collapse_btn)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setProperty("category", "tool")
        self.fullscreen_btn.setIcon(get_icon("fullscreen", size=16))
        self.fullscreen_btn.setToolTip("全屏")
        self.fullscreen_btn.setFlat(True)
        self.fullscreen_btn.setFixedSize(28, 28)
        self.fullscreen_btn.clicked.connect(self._enter_fullscreen)
        title_row.addWidget(self.fullscreen_btn)
        layout.addLayout(title_row)

        self.filter_bar = QWidget()
        self.filter_bar.setObjectName("WaveformFilterBar")
        filter_row = QHBoxLayout(self.filter_bar)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)

        filter_label = QLabel("显示曲线")
        filter_label.setObjectName("WaveformFilterLabel")
        filter_row.addWidget(filter_label)

        self.toggles = []
        joint_labels = ["拇弯", "拇摆", "食指", "中指", "无名", "小指"]
        for i in range(self.joint_count):
            name = joint_labels[i] if i < len(joint_labels) else self.joint_names_short[i]
            btn = QPushButton(f"●  {name}")
            btn.setObjectName("WaveformToggle")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"显示或隐藏{name}曲线")
            btn.setFixedHeight(24)
            btn.setProperty("_lh_theme_native", True)
            self._style_toggle(btn, i)
            btn.toggled.connect(lambda checked, idx=i: self._toggle(idx, checked))
            self.toggles.append(btn)
            filter_row.addWidget(btn)
        filter_row.addStretch()
        layout.addWidget(self.filter_bar)

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
        self.target_lines = []
        for i in range(self.joint_count):
            color = self.COLORS[i % len(self.COLORS)]
            name = self.joint_names_short[i]
            line, = self.ax.plot([], [], color=color, label=name, linewidth=1.6, alpha=0.85)
            # 加绘目标同色虚线
            t_line, = self.ax.plot([], [], color=color, linestyle="--", linewidth=1.2, alpha=0.6)
            self.lines.append(line)
            self.target_lines.append(t_line)

        layout.addWidget(self.canvas, stretch=1)

    def _style_toggle(self, button, index: int):
        from lhgui.styles.theme_manager import is_dark_theme
        dark = is_dark_theme()
        palette = self.DARK_PALETTE if dark else self.PALETTE
        color, tint, border = palette[index % len(palette)]
        base = "#1D2837" if dark else "#F8FAFC"
        hover = "#243143" if dark else "#F1F5F9"
        muted = "#8FA0B5" if dark else "#94A3B8"
        selected_hover = "#26364D" if dark else "#FFFFFF"
        button.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {"#334258" if dark else "#E2E8F0"};
                border-radius: 12px;
                padding: 1px 9px;
                background: {base};
                color: {muted};
                font-size: 10px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {hover};
                border-color: {border};
                color: {color};
            }}
            QPushButton:checked {{
                background: {tint};
                border-color: {border};
                color: {color};
                font-weight: 600;
            }}
            QPushButton:checked:hover {{
                background: {selected_hover};
                border-color: {color};
            }}
        """)

    def _apply_theme(self, name: str):
        dark = name == "dark"
        palette = self.DARK_PALETTE if dark else self.PALETTE
        for index, button in enumerate(self.toggles):
            self._style_toggle(button, index)
        for index, line in enumerate(self.lines):
            line.set_color(palette[index % len(palette)][0])
        for index, line in enumerate(self.target_lines):
            line.set_color(palette[index % len(palette)][0])

        face = "#182230" if dark else "#FAFBFD"
        text = "#98A8BC" if dark else "#94A3B8"
        grid = "#334258" if dark else "#E8EDF3"
        spine = "#40516A" if dark else "#DCE3EC"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.xaxis.label.set_color(text)
        self.ax.yaxis.label.set_color(text)
        self.ax.tick_params(colors=text)
        self.ax.grid(True, color=grid, linewidth=0.5, alpha=0.75)
        self.ax.spines["left"].set_color(spine)
        self.ax.spines["bottom"].set_color(spine)
        self.canvas.draw_idle()
    def _toggle(self, idx: int, on: bool):
        if idx < len(self._show):
            self._show[idx] = on
            self.lines[idx].set_visible(on)
            self.target_lines[idx].set_visible(on)
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
            
            # 目标虚线数据更新
            t_val = self._latest_targets[i] if i < len(self._latest_targets) else 250
            self._buf_targets[i].append(float(t_val))
            self.target_lines[i].set_data(range(len(self._buf_targets[i])), list(self._buf_targets[i]))

        max_len = max(len(buf) for buf in self._buf_joints) if self._buf_joints else 0
        self.ax.set_xlim(0, max(self.MAX_POINTS, max_len))

        # 绘制并更新自适应事件标记 Scatter
        active_markers = []
        for m in self._curve_markers:
            m["x"] -= 1
            if m["x"] < 0:
                if m["plot_obj"]:
                    try:
                        m["plot_obj"].remove()
                    except Exception:
                        pass
                continue

            j_idx = m["joint_index"]
            visible = self._show[j_idx]
            
            if not visible:
                if m["plot_obj"]:
                    m["plot_obj"].set_visible(False)
                active_markers.append(m)
                continue

            e_type = m["event_type"]
            if e_type == "contact_candidate":
                color, marker, size = "#EAB308", "^", 8
            elif e_type == "contact_confirmed":
                color, marker, size = "#10B981", "*", 11
            elif e_type == "limit_reached":
                color, marker, size = "#F97316", "s", 7
            else:  # aborted
                color, marker, size = "#EF4444", "x", 8

            if m["plot_obj"] is None:
                # 绘制 scatter 并加入 ax
                plot_obj, = self.ax.plot(
                    [m["x"]], [m["y"]], color=color, marker=marker,
                    markersize=size, linestyle="None", markeredgewidth=1.5, zorder=5
                )
                m["plot_obj"] = plot_obj
            else:
                m["plot_obj"].set_visible(True)
                m["plot_obj"].set_data([m["x"]], [m["y"]])

            active_markers.append(m)

        self._curve_markers = active_markers

        all_vals = []
        for i in range(self.joint_count):
            if self._show[i]:
                all_vals.extend(list(self._buf_joints[i]))
                all_vals.extend(list(self._buf_targets[i]))

        if all_vals:
            ymin = min(all_vals)
            ymax = max(all_vals)
            margin = (ymax - ymin) * 0.15 if ymax != ymin else 15.0
            self.ax.set_ylim(ymin - margin, ymax + margin)
        else:
            self.ax.set_ylim(0, 260)

        if not self._collapsed:
            self.canvas.draw_idle()

    def _on_finger_move_requested(self, targets: list):
        if targets:
            self._latest_targets = list(targets)

    def _on_grasp_state_changed(self, state):
        from lhgui.core.grasp_state import GraspState
        if state == GraspState.IDLE:
            self._clear_markers()

    def _clear_markers(self):
        for m in self._curve_markers:
            if m["plot_obj"]:
                try:
                    m["plot_obj"].remove()
                except Exception:
                    pass
        self._curve_markers.clear()

    def _on_grasp_curve_event(self, event: dict):
        if self._collapsed:
            return
        
        joint_idx = event.get("joint_index", 0)
        if joint_idx >= self.joint_count or not self._show[joint_idx]:
            return
        
        # X 轴坐标位置，代表当前缓冲折线的最新右边缘
        x_pos = len(self._buf_joints[joint_idx]) - 1
        if x_pos < 0:
            x_pos = 0

        val = event.get("value", 0.0)
        e_type = event.get("event_type", "contact_confirmed")

        # 过滤同一关节过于密集的候选标记
        if e_type == "contact_candidate":
            recent = [m for m in self._curve_markers if m["joint_index"] == joint_idx and m["event_type"] == e_type]
            if recent and (x_pos - recent[-1]["x"]) < 5:
                return

        self._curve_markers.append({
            "x": x_pos,
            "y": float(val),
            "joint_index": joint_idx,
            "event_type": e_type,
            "plot_obj": None
        })

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
