#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连接栏：状态灯 + 设备信息 + 重连按钮。"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt5.QtCore import Qt

from lhgui.utils.signal_bus import signal_bus

_STATUS_TEXT = {
    "connected": "已连接",
    "disconnected": "未连接",
    "connecting": "连接中",
    "error": "连接错误",
}


class ConnectionBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("ConnectionBar")
        self.setFixedHeight(44)
        self._build()
        signal_bus.connection_changed.connect(self._on_status)
        signal_bus.hand_info_ready.connect(self._on_info)
        signal_bus.connection_message.connect(lambda lvl, msg: None)  # 日志交给 StatusPanel

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self.dot = QLabel()
        self.dot.setObjectName("StatusDot")
        self.dot.setFixedSize(12, 12)
        self.dot.setProperty("status", "disconnected")
        layout.addWidget(self.dot)

        self.status_label = QLabel("未连接")
        self.status_label.setMinimumWidth(80)
        layout.addWidget(self.status_label)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color:#4e5969;")
        layout.addWidget(self.info_label, stretch=1)

        layout.addStretch()

        self.reconnect_btn = QPushButton("重连")
        self.reconnect_btn.setProperty("category", "primary")
        self.reconnect_btn.setCursor(Qt.PointingHandCursor)
        self.reconnect_btn.clicked.connect(signal_bus.request_reconnect.emit)
        layout.addWidget(self.reconnect_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#e5e6eb;")
        layout.addWidget(sep)

        self.demo_btn = QPushButton("演示模式")
        self.demo_btn.setCheckable(True)
        self.demo_btn.setCursor(Qt.PointingHandCursor)
        self.demo_btn.toggled.connect(signal_bus.demo_mode_toggled.emit)
        layout.addWidget(self.demo_btn)

    def _on_status(self, status: str):
        self.dot.setProperty("status", status)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.status_label.setText(_STATUS_TEXT.get(status, status))
        self.reconnect_btn.setEnabled(status != "connecting")

    def _on_info(self, info: dict):
        joint = info.get("hand_joint", "")
        htype = info.get("hand_type", "")
        serial = info.get("serial", "") or ""
        version = info.get("version")
        ver_str = "".join(str(v) for v in version) if isinstance(version, list) else (version or "")
        text = f"{htype} · {joint}"
        if serial:
            text += f" · SN {serial}"
        if ver_str:
            text += f" · 固件 {ver_str}"
        self.info_label.setText(text)
