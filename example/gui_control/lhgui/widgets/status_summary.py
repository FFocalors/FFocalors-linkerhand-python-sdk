#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态摘要卡片：关键状态行 + 紧凑参数块（速度/扭矩弹窗设置）。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QSlider, QSpinBox, QAbstractSpinBox, QDialogButtonBox
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import (
    ui_state, ConnectionState, ActionState, RecorderState, PlaybackState
)
from lhgui.widgets.status_badge import StatusBadge


class _ParamBlock(QWidget):
    """紧凑参数块：标题 + 当前值 + 设置按钮。"""
    def __init__(self, title: str, value: int, on_set):
        super().__init__()
        self.setObjectName("ParamBlock")
        self._title = title
        self._value = value
        self._on_set = on_set
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        title_lbl = QLabel(self._title)
        title_lbl.setObjectName("ParamTitle")
        layout.addWidget(title_lbl)

        self.value_lbl = QLabel(str(self._value))
        self.value_lbl.setObjectName("ParamValue")
        self.value_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.value_lbl)

        set_btn = QPushButton("设置")
        set_btn.setProperty("category", "secondary")
        set_btn.setCursor(Qt.PointingHandCursor)
        set_btn.clicked.connect(self._open_dialog)
        layout.addWidget(set_btn)

    def _open_dialog(self):
        dlg = _ParamDialog(self.window(), self._title, 0, 255, self._value)
        if dlg.exec_() == QDialog.Accepted:
            self._value = dlg.value()
            self.value_lbl.setText(str(self._value))
            self._on_set(self._value)

    def set_enabled(self, enabled: bool):
        for child in self.findChildren(QWidget):
            child.setEnabled(enabled)


class _ParamDialog(QDialog):
    def __init__(self, parent, title: str, minimum: int, maximum: int, current: int):
        super().__init__(parent)
        self.setWindowTitle(f"设置{title}")
        self.setMinimumWidth(320)
        self._value = current

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info = QLabel(f"{title}范围 {minimum}–{maximum}")
        info.setStyleSheet("color:#6b7280;")
        layout.addWidget(info)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(current)
        layout.addWidget(self.slider)

        row = QHBoxLayout()
        row.addWidget(QLabel("当前"))
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setFixedWidth(70)
        self.spin.setValue(current)
        row.addWidget(self.spin)
        row.addStretch()
        layout.addLayout(row)

        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self._value = self.slider.value()
        self.accept()

    def value(self) -> int:
        return self._value


class StatusSummary(QWidget):
    def __init__(self, hand_joint: str):
        super().__init__()
        self.setObjectName("StatusSummaryCard")
        self.hand_joint = hand_joint
        self.joint_count = len(HAND_CONFIGS[hand_joint].joint_names)
        self._build()
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("状态与参数")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        # 状态行
        self.conn_badge = StatusBadge("未连接", level="disconnected")
        layout.addWidget(self._row("连接", self.conn_badge))

        self.action_lbl = QLabel("空闲")
        self.action_lbl.setObjectName("StatusValue")
        layout.addWidget(self._row("当前动作", self.action_lbl))

        self.demo_lbl = QLabel("关闭")
        layout.addWidget(self._row("演示模式", self.demo_lbl))

        self.rec_lbl = QLabel("空闲")
        layout.addWidget(self._row("录制/回放", self.rec_lbl))

        # 参数块
        param_row = QHBoxLayout()
        param_row.setSpacing(10)
        self.speed_block = _ParamBlock("速度", 255, self._set_speed)
        self.torque_block = _ParamBlock("扭矩", 255, self._set_torque)
        param_row.addWidget(self.speed_block)
        param_row.addWidget(self.torque_block)
        layout.addLayout(param_row)

        layout.addStretch()

    @staticmethod
    def _row(label_text: str, value_widget: QWidget) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setObjectName("StatusKey")
        lbl.setMinimumWidth(72)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(value_widget)
        return w

    def _on_ui_state(self, snapshot):
        conn = snapshot.connection
        if conn == ConnectionState.CONNECTED:
            self.conn_badge.set_level("connected")
            self.conn_badge.setText("已连接")
        elif conn == ConnectionState.CONNECTING:
            self.conn_badge.set_level("connecting")
            self.conn_badge.setText("连接中")
        elif conn == ConnectionState.ERROR:
            self.conn_badge.set_level("error")
            self.conn_badge.setText("失败")
        else:
            self.conn_badge.set_level("disconnected")
            self.conn_badge.setText("未连接")

        # 当前动作
        if snapshot.action == ActionState.CYCLE_RUNNING:
            self.action_lbl.setText("循环运行中")
        elif snapshot.action == ActionState.ACTION_RUNNING:
            self.action_lbl.setText("执行中")
        else:
            self.action_lbl.setText("空闲")

        self.demo_lbl.setText("开启" if snapshot.demo_mode else "关闭")

        if snapshot.recorder == RecorderState.RECORDING:
            self.rec_lbl.setText("录制中")
        elif snapshot.playback == PlaybackState.PLAYING:
            self.rec_lbl.setText("回放中")
        else:
            self.rec_lbl.setText("空闲")

        enabled = conn == ConnectionState.CONNECTED
        self.speed_block.set_enabled(enabled)
        self.torque_block.set_enabled(enabled)

    def _set_speed(self, v: int):
        signal_bus.speed_set_requested.emit([v] * self.joint_count)
        signal_bus.connection_message.emit("info", f"速度已设为 {v}")

    def _set_torque(self, v: int):
        signal_bus.torque_set_requested.emit([v] * self.joint_count)
        signal_bus.connection_message.emit("info", f"扭矩已设为 {v}")
