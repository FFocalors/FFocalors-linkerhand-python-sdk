#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速设置：速度 / 扭矩。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton, QGroupBox
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus


class QuickSettings(QGroupBox):
    def __init__(self, hand_joint: str):
        super().__init__("快速设置")
        self.hand_joint = hand_joint
        self._build()

    def _joint_len(self) -> int:
        return len(HAND_CONFIGS[self.hand_joint].joint_names)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 速度
        srow = QHBoxLayout()
        srow.addWidget(QLabel("速度"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(0, 255)
        self.speed_slider.setValue(255)
        self.speed_val = QLabel("255")
        self.speed_val.setMinimumWidth(32)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_val.setText(str(v)))
        srow.addWidget(self.speed_slider, stretch=1)
        srow.addWidget(self.speed_val)
        sbtn = QPushButton("设置")
        sbtn.clicked.connect(self._set_speed)
        srow.addWidget(sbtn)
        layout.addLayout(srow)

        # 扭矩
        trow = QHBoxLayout()
        trow.addWidget(QLabel("扭矩"))
        self.torque_slider = QSlider(Qt.Horizontal)
        self.torque_slider.setRange(0, 255)
        self.torque_slider.setValue(255)
        self.torque_val = QLabel("255")
        self.torque_val.setMinimumWidth(32)
        self.torque_slider.valueChanged.connect(lambda v: self.torque_val.setText(str(v)))
        trow.addWidget(self.torque_slider, stretch=1)
        trow.addWidget(self.torque_val)
        tbtn = QPushButton("设置")
        tbtn.clicked.connect(self._set_torque)
        trow.addWidget(tbtn)
        layout.addLayout(trow)

    def _set_speed(self):
        v = self.speed_slider.value()
        signal_bus.speed_set_requested.emit([v] * self._joint_len())
        signal_bus.connection_message.emit("info", f"速度已设为 {v}")

    def _set_torque(self):
        v = self.torque_slider.value()
        signal_bus.torque_set_requested.emit([v] * self._joint_len())
        signal_bus.connection_message.emit("info", f"扭矩已设为 {v}")
