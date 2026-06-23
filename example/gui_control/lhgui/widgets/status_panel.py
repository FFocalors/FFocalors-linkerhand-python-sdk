#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态日志面板：带级别着色与时间戳。"""
import time
from collections import deque

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLabel
from PyQt5.QtCore import Qt

from lhgui.utils.signal_bus import signal_bus

_LEVEL_COLOR = {
    "info": "#4e5969",
    "success": "#0f9b5a",
    "warning": "#d97510",
    "error": "#c9272c",
}


class StatusPanel(QWidget):
    MAX_LINES = 500

    def __init__(self):
        super().__init__()
        self._lines = deque(maxlen=self.MAX_LINES)
        self._build()
        signal_bus.connection_message.connect(self.append)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("状态日志")
        title.setStyleSheet("font-weight:600;color:#1f2329;")
        layout.addWidget(title)

        self.view = QTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        layout.addWidget(self.view, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        clear_btn = QPushButton("清除日志")
        clear_btn.clicked.connect(self.clear)
        row.addWidget(clear_btn)
        layout.addLayout(row)

    def append(self, level: str, message: str):
        color = _LEVEL_COLOR.get(level, "#4e5969")
        ts = time.strftime("%H:%M:%S")
        line = f'<span style="color:#86909c;">[{ts}]</span> ' \
               f'<span style="color:{color};">{message}</span>'
        self._lines.append(line)
        self.view.setHtml("<br>".join(self._lines))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def clear(self):
        self._lines.clear()
        self.view.setHtml('<span style="color:#86909c;">日志已清除</span>')
