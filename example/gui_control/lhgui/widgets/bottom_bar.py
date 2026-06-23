#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""底部控制条 — 产品级完整卡片布局。

结构:
  [状态组] [参数组] [循环组]   [恢复初始] [紧急停止]

各分组内部整齐排列，不再像拼装件。
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QDialog, QSlider, QSpinBox, QAbstractSpinBox,
    QDialogButtonBox, QVBoxLayout as QVBox
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.widgets.status_badge import StatusBadge


class _ParamDialog(QDialog):
    def __init__(self, parent, title, minimum, maximum, current):
        super().__init__(parent)
        self.setWindowTitle(f"设置{title}")
        self.setMinimumWidth(360)
        self._value = current

        layout = QVBox(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info = QLabel(f"{title}范围 {minimum}–{maximum}")
        info.setStyleSheet("color:#64748B;")
        layout.addWidget(info)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(current)
        layout.addWidget(self.slider)

        row = QHBoxLayout()
        row.addWidget(QLabel("当前值"))
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setFixedWidth(72)
        self.spin.setValue(current)
        row.addWidget(self.spin)
        row.addStretch()
        layout.addLayout(row)

        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self._value = self.slider.value()
        self.accept()

    def value(self) -> int:
        return self._value


class BottomBar(QWidget):
    def __init__(self, hand_joint: str):
        super().__init__()
        self.setObjectName("BottomBar")
        self.hand_joint = hand_joint
        self.joint_count = len(HAND_CONFIGS[hand_joint].joint_names)
        self._speed = 255
        self._torque = 255
        self._layout_mode = "single"
        self._cycle = None

        self._build()
        signal_bus.ui_state_changed.connect(self._on_ui_state)

        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self, blur=12, offset=1)

    # ────── helpers ──────

    def _divider(self):
        sep = QFrame()
        sep.setObjectName("BottomDivider")
        sep.setFrameShape(QFrame.VLine)
        return sep

    def _status_block(self, label: str) -> tuple:
        """Creates a #StatusInfoBlock with label/value pair."""
        block = QFrame()
        block.setObjectName("StatusInfoBlock")
        bl = QHBoxLayout(block)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(6)

        lbl = QLabel(label)
        lbl.setObjectName("StatusInfoLabel")
        bl.addWidget(lbl)

        val = QLabel("—")
        val.setObjectName("StatusInfoValue")
        bl.addWidget(val)

        return block, val

    # ────── build ──────

    def _build(self):
        # Top-level layout
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(16, 10, 16, 10)
        self.outer.setSpacing(0)

        self.main_row = QHBoxLayout()
        self.main_row.setContentsMargins(0, 0, 0, 0)
        self.main_row.setSpacing(10)
        self.outer.addLayout(self.main_row)

        # ── 1. 状态组 ──
        self.status_blk, self.status_val = self._status_block("当前动作")
        self.main_row.addWidget(self.status_blk)

        self.cycle_blk, self.cycle_val = self._status_block("循环状态")
        self.main_row.addWidget(self.cycle_blk)

        self.main_row.addWidget(self._divider())

        # ── 2. 参数组 ──
        self.speed_btn = QPushButton(f"速度\n{self._speed}")
        self.speed_btn.setObjectName("ParameterBlock")
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.clicked.connect(self._set_speed)
        self.speed_btn.setToolTip("点击调整关节运动速度")
        self.speed_btn.setFixedHeight(48)
        self.main_row.addWidget(self.speed_btn)

        self.torque_btn = QPushButton(f"扭矩\n{self._torque}")
        self.torque_btn.setObjectName("ParameterBlock")
        self.torque_btn.setCursor(Qt.PointingHandCursor)
        self.torque_btn.clicked.connect(self._set_torque)
        self.torque_btn.setToolTip("点击调整关节最大扭矩")
        self.torque_btn.setFixedHeight(48)
        self.main_row.addWidget(self.torque_btn)

        self.main_row.addWidget(self._divider())

        # ── 3. 循环控制组 ──
        self.cycle_btn = QPushButton("开始循环")
        self.cycle_btn.setProperty("category", "primary")
        self.cycle_btn.setCursor(Qt.PointingHandCursor)
        self.cycle_btn.clicked.connect(self._toggle_cycle)
        self.main_row.addWidget(self.cycle_btn)

        self.cycle_stop_btn = QPushButton("停止循环")
        self.cycle_stop_btn.setProperty("category", "danger")
        self.cycle_stop_btn.setCursor(Qt.PointingHandCursor)
        self.cycle_stop_btn.setEnabled(False)
        self.cycle_stop_btn.clicked.connect(self._stop_cycle)
        self.main_row.addWidget(self.cycle_stop_btn)

        # ── 弹性空间 → 安全操作推向右侧 ──
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.main_row.addWidget(self.spacer)

        self.main_row.addWidget(self._divider())

        # ── 4. 安全操作组 ──
        self.home_btn = QPushButton("恢复初始")
        self.home_btn.setProperty("category", "warning")
        self.home_btn.setCursor(Qt.PointingHandCursor)
        self.main_row.addWidget(self.home_btn)

        self.estop_btn = QPushButton("紧急停止")
        self.estop_btn.setProperty("category", "emergency")
        self.estop_btn.setCursor(Qt.PointingHandCursor)
        self.main_row.addWidget(self.estop_btn)

    def set_cycle_controller(self, controller):
        self._cycle = controller
        controller.status_updated.connect(self._on_cycle_status)

    def _toggle_cycle(self):
        if self._cycle is not None:
            self._cycle.start() if not self._cycle._active else self._cycle.stop()

    def _stop_cycle(self):
        if self._cycle is not None:
            self._cycle.stop()

    def _on_cycle_status(self, active: bool, name: str = ""):
        self.cycle_btn.setEnabled(not active)
        self.cycle_btn.setText("循环中" if active else "开始循环")
        self.cycle_stop_btn.setEnabled(active)
        self.cycle_val.setText(name if active else "空闲")
        self.cycle_val.setStyleSheet(
            "color: #4F7FF7; font-weight:600;" if active else "color: #1E293B;"
        )

    def set_layout_mode(self, mode: str):
        """保留接口兼容性。当前底部栏使用自适应单行布局，无需手动切换。"""
        self._layout_mode = mode

    # ────── param dialogs ──────

    def _set_speed(self):
        dlg = _ParamDialog(self.window(), "速度", 0, 255, self._speed)
        if dlg.exec_() == QDialog.Accepted:
            self._speed = dlg.value()
            self.speed_btn.setText(f"速度\n{self._speed}")
            signal_bus.speed_set_requested.emit([self._speed] * self.joint_count)
            signal_bus.connection_message.emit("info", f"速度已设为 {self._speed}")

    def _set_torque(self):
        dlg = _ParamDialog(self.window(), "扭矩", 0, 255, self._torque)
        if dlg.exec_() == QDialog.Accepted:
            self._torque = dlg.value()
            self.torque_btn.setText(f"扭矩\n{self._torque}")
            signal_bus.torque_set_requested.emit([self._torque] * self.joint_count)
            signal_bus.connection_message.emit("info", f"扭矩已设为 {self._torque}")

    # ────── ui state ──────

    def _on_ui_state(self, snapshot):
        enabled = snapshot.connection in (ConnectionState.CONNECTED, ConnectionState.OFFLINE)
        self.home_btn.setEnabled(enabled)
        self.speed_btn.setEnabled(enabled)
        self.torque_btn.setEnabled(enabled)
        self.cycle_btn.setEnabled(enabled and not (self._cycle is not None and self._cycle._active))

        if snapshot.action == ActionState.ACTION_RUNNING:
            self.status_val.setText("执行中")
            self.status_val.setStyleSheet("color: #4F7FF7; font-weight:600;")
        elif snapshot.action == ActionState.CYCLE_RUNNING:
            self.status_val.setText("循环中")
            self.status_val.setStyleSheet("color: #4F7FF7; font-weight:600;")
        else:
            self.status_val.setText("空闲")
            self.status_val.setStyleSheet("color: #1E293B;")
