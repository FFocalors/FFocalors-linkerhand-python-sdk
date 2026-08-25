#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real-time waveform panel with decoupled sampling and rendering."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QShortcut
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
import numpy as np
import pyqtgraph as pg

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.icon_helper import get_icon


class WaveformPanel(QWidget):
    """Keep the existing visual controls while making updates bounded and cheap.

    ``_on_data`` only writes a fixed-size ring buffer.  ``_render_timer`` is the
    sole owner of PlotDataItem updates and runs at most 13 FPS while visible.
    """
    MAX_POINTS = 200
    RENDER_INTERVAL_MS = 75
    fullscreen_requested = pyqtSignal()
    collapse_changed = pyqtSignal(bool)
    PALETTE = [
        ("#5B7FC7", "#EDF3FC", "#B8C9EA"), ("#558EAA", "#EDF6F8", "#B8D5E0"),
        ("#568F78", "#EEF7F3", "#B7D8CA"), ("#B78345", "#FBF4E9", "#E4C9A3"),
        ("#756AA8", "#F3F0FA", "#CAC3E1"), ("#6279B7", "#EFF2FA", "#BEC9E5"),
    ]
    COLORS = [entry[0] for entry in PALETTE]
    DARK_PALETTE = [
        ("#86A8E6", "#1C2B45", "#415C86"), ("#75B2CC", "#18313D", "#3C6677"),
        ("#76B99D", "#19352F", "#3D6B5B"), ("#D5A665", "#382B19", "#745A34"),
        ("#A194D8", "#2A2540", "#5C527F"), ("#879DDB", "#202D49", "#465D8D"),
    ]

    def __init__(self, hand_joint: str = "O6", parent=None):
        super().__init__(parent)
        self.setObjectName("WaveformPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hand_joint = hand_joint
        self._collapsed = False
        self._is_fullscreen = False
        self._dialog = None
        self._placeholder = QWidget()
        self._placeholder.setMinimumHeight(150)
        self._orig_parent = self._orig_layout = None
        self._orig_index = self._orig_stretch = 0
        self._prev_collapsed = False

        from lhgui.config.constants import HAND_CONFIGS
        self.config = HAND_CONFIGS.get(hand_joint)
        self.joint_names = list(self.config.joint_names)[:6] if self.config else []
        self.joint_count = len(self.joint_names)
        from lhgui.widgets.hand_pose_card import SHORT_NAMES
        self.joint_names_short = [SHORT_NAMES.get(n, n[:2]) for n in self.joint_names]

        self._joint_buffer = np.zeros((self.joint_count, self.MAX_POINTS), dtype=np.float32)
        self._target_buffer = np.zeros_like(self._joint_buffer)
        self._write_index = 0
        self._sample_count = 0
        self._latest_state = None
        self._latest_targets = np.asarray(
            list(self.config.init_pos)[:self.joint_count] if self.config else [250] * self.joint_count,
            dtype=np.float32,
        )
        if self._latest_targets.size < self.joint_count:
            self._latest_targets = np.pad(self._latest_targets, (0, self.joint_count - self._latest_targets.size), constant_values=250)
        self._show = [True] * self.joint_count
        self._curve_markers = []

        self._build()
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(self.RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_frame)
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

        self.canvas = pg.PlotWidget(background="#FAFBFD")
        self.canvas.setMinimumHeight(130)
        self.canvas.setMaximumHeight(210)
        self.plot_item = self.canvas.getPlotItem()
        self.plot_item.setLabel("bottom", "采样点")
        self.plot_item.setLabel("left", "反馈值")
        self.plot_item.setYRange(0, 260)
        self.plot_item.setXRange(0, self.MAX_POINTS, padding=0)
        self.plot_item.showGrid(x=True, y=True, alpha=0.22)
        self.plot_item.hideButtons()
        self.lines = []
        self.target_lines = []
        for i in range(self.joint_count):
            color = self.COLORS[i % len(self.COLORS)]
            self.lines.append(self.plot_item.plot([], [], pen=pg.mkPen(color=color, width=2), name=self.joint_names_short[i]))
            self.target_lines.append(self.plot_item.plot([], [], pen=pg.mkPen(color=color, width=1, style=Qt.DashLine)))
        layout.addWidget(self.canvas, stretch=1)

    def _style_toggle(self, button, index: int):
        from lhgui.styles.theme_manager import is_dark_theme
        dark = is_dark_theme()
        color, tint, border = (self.DARK_PALETTE if dark else self.PALETTE)[index % len(self.PALETTE)]
        base = "#1D2837" if dark else "#F8FAFC"
        hover = "#243143" if dark else "#F1F5F9"
        muted = "#8FA0B5" if dark else "#94A3B8"
        selected_hover = "#26364D" if dark else "#FFFFFF"
        button.setStyleSheet(f"""QPushButton {{ border: 1px solid {('#334258' if dark else '#E2E8F0')}; border-radius: 12px; padding: 1px 9px; background: {base}; color: {muted}; font-size: 10px; font-weight: 500; }} QPushButton:hover {{ background: {hover}; border-color: {border}; color: {color}; }} QPushButton:checked {{ background: {tint}; border-color: {border}; color: {color}; font-weight: 600; }} QPushButton:checked:hover {{ background: {selected_hover}; border-color: {color}; }}""")

    def _apply_theme(self, name: str):
        dark = name == "dark"
        palette = self.DARK_PALETTE if dark else self.PALETTE
        for index, button in enumerate(self.toggles):
            self._style_toggle(button, index)
        for index in range(self.joint_count):
            color = palette[index % len(palette)][0]
            self.lines[index].setPen(pg.mkPen(color=color, width=2))
            self.target_lines[index].setPen(pg.mkPen(color=color, width=1, style=Qt.DashLine))
        face = "#182230" if dark else "#FAFBFD"
        self.canvas.setBackground(face)
        axis = "#40516A" if dark else "#DCE3EC"
        self.plot_item.getAxis("bottom").setPen(pg.mkPen(axis))
        self.plot_item.getAxis("left").setPen(pg.mkPen(axis))
        self._request_render()

    def _toggle(self, idx: int, on: bool):
        if idx >= len(self._show):
            return
        self._show[idx] = on
        self.lines[idx].setVisible(on)
        self.target_lines[idx].setVisible(on)
        self._request_render()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.canvas.setVisible(not self._collapsed)
        self.filter_bar.setVisible(not self._collapsed)
        self.collapse_btn.setIcon(get_icon("expand" if self._collapsed else "collapse", size=16))
        self.collapse_btn.setToolTip("展开" if self._collapsed else "折叠")
        self.collapse_changed.emit(self._collapsed)
        if self._collapsed:
            self._render_timer.stop()
        else:
            self._start_rendering()

    def _request_render(self):
        if self.isVisible() and not self._collapsed:
            self._start_rendering()

    def _start_rendering(self):
        if self.isVisible() and not self._collapsed and not self._render_timer.isActive():
            self._render_timer.start()

    def _on_data(self, data: dict):
        state = data.get("state") if isinstance(data, dict) else None
        if not isinstance(state, (list, tuple)) or len(state) < self.joint_count:
            return
        try:
            values = np.asarray(state[:self.joint_count], dtype=np.float32)
        except (TypeError, ValueError):
            return
        if not np.all(np.isfinite(values)):
            return
        idx = self._write_index
        self._joint_buffer[:, idx] = values
        self._target_buffer[:, idx] = self._latest_targets
        self._write_index = (idx + 1) % self.MAX_POINTS
        self._sample_count = min(self._sample_count + 1, self.MAX_POINTS)
        self._latest_state = values
        for marker in self._curve_markers:
            marker["age"] += 1
        self._request_render()

    def _ordered_buffer(self, buffer):
        count = self._sample_count
        if count <= 0:
            return np.empty(0, dtype=np.float32)
        start = (self._write_index - count) % self.MAX_POINTS
        if start + count <= self.MAX_POINTS:
            return buffer[:, start:start + count]
        return np.concatenate((buffer[:, start:], buffer[:, :(start + count) % self.MAX_POINTS]), axis=1)

    def _render_frame(self):
        if self._collapsed or not self.isVisible():
            self._render_timer.stop()
            return
        count = self._sample_count
        if not count:
            return
        x = np.arange(count, dtype=np.float32)
        values = self._ordered_buffer(self._joint_buffer)
        targets = self._ordered_buffer(self._target_buffer)
        visible_values = []
        for i in range(self.joint_count):
            self.lines[i].setData(x=x, y=values[i])
            self.target_lines[i].setData(x=x, y=targets[i])
            if self._show[i]:
                visible_values.extend((values[i], targets[i]))
        if visible_values:
            merged = np.concatenate(visible_values)
            lo, hi = float(np.min(merged)), float(np.max(merged))
            margin = (hi - lo) * 0.15 if hi != lo else 15.0
            self.plot_item.setYRange(lo - margin, hi + margin, padding=0)
        self.plot_item.setXRange(0, max(self.MAX_POINTS, count), padding=0)
        self._render_markers(count)

    def _render_markers(self, count):
        active = []
        colors = {"contact_candidate": "#EAB308", "contact_confirmed": "#10B981", "limit_reached": "#F97316", "aborted": "#EF4444"}
        symbols = {"contact_candidate": "t", "contact_confirmed": "star", "limit_reached": "s", "aborted": "x"}
        for marker in self._curve_markers:
            x = count - 1 - marker["age"]
            if x < 0:
                continue
            marker["x"] = x
            if not self._show[marker["joint_index"]]:
                if marker.get("plot_obj"):
                    marker["plot_obj"].setVisible(False)
                active.append(marker)
                continue
            item = marker.get("plot_obj")
            if item is None:
                color = colors.get(marker["event_type"], "#EF4444")
                item = pg.ScatterPlotItem(size=10, pen=pg.mkPen(color), brush=pg.mkBrush(color), symbol=symbols.get(marker["event_type"], "x"))
                self.plot_item.addItem(item)
                marker["plot_obj"] = item
            item.setVisible(True)
            item.setData([x], [marker["y"]])
            active.append(marker)
        self._curve_markers = active

    def _on_finger_move_requested(self, targets: list):
        if targets:
            values = np.asarray(targets[:self.joint_count], dtype=np.float32)
            if values.size == self.joint_count and np.all(np.isfinite(values)):
                self._latest_targets = values

    def _on_grasp_state_changed(self, state):
        from lhgui.core.grasp_state import GraspState
        if state == GraspState.IDLE:
            self._clear_markers()

    def _clear_markers(self):
        for marker in self._curve_markers:
            if marker.get("plot_obj"):
                self.plot_item.removeItem(marker["plot_obj"])
        self._curve_markers.clear()

    def _on_grasp_curve_event(self, event: dict):
        if self._collapsed:
            return
        joint_idx = event.get("joint_index", 0)
        if not isinstance(joint_idx, int) or joint_idx >= self.joint_count or not self._show[joint_idx]:
            return
        event_type = event.get("event_type", "contact_confirmed")
        x_pos = self._sample_count - 1
        if event_type == "contact_candidate":
            recent = [m for m in self._curve_markers if m["joint_index"] == joint_idx and m["event_type"] == event_type]
            if recent and x_pos - recent[-1]["x"] < 5:
                return
        self._curve_markers.append({"x": x_pos, "age": 0, "y": float(event.get("value", 0.0)), "joint_index": joint_idx, "event_type": event_type, "plot_obj": None})
        self._request_render()

    def set_collapsed(self, collapsed: bool):
        if collapsed != self._collapsed:
            self._toggle_collapse()

    @property
    def collapsed(self):
        return self._collapsed

    def hideEvent(self, event):
        self._render_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._start_rendering()

    def _enter_fullscreen(self):
        if self._is_fullscreen:
            return
        self._is_fullscreen = True
        self._prev_collapsed = self._collapsed
        self.set_collapsed(False)
        self.canvas.setMaximumHeight(16777215)
        self._orig_parent = self.parentWidget()
        if not self._orig_parent or not self._orig_parent.layout():
            return
        self._orig_layout = self._orig_parent.layout()
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
            if self._dialog.layout():
                self._dialog.layout().removeWidget(self)
        self.hide()
        self.setParent(self._orig_parent)
        if self._orig_layout:
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
        self._start_rendering()
        self._dialog = None
