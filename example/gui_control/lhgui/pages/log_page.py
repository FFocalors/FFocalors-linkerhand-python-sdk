#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志页面。"""
import time
from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QCheckBox, QFileDialog, QMessageBox
)
from PyQt5.QtGui import QClipboard
from PyQt5.QtCore import Qt

from lhgui.utils.signal_bus import signal_bus


_LEVEL_COLOR = {
    "info": "#6b7280",
    "success": "#166534",
    "warning": "#92400e",
    "error": "#991b1b",
}


class LogPage(QWidget):
    MAX_ENTRIES = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogPage")
        self._entries = deque(maxlen=self.MAX_ENTRIES)
        self._build()
        signal_bus.connection_message.connect(self._append)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        title = QLabel("日志")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.view = QTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        layout.addWidget(self.view, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.auto_scroll_cb = QCheckBox("自动滚动")
        self.auto_scroll_cb.setChecked(True)
        row.addWidget(self.auto_scroll_cb)

        row.addStretch()

        copy_btn = QPushButton("复制")
        copy_btn.setProperty("category", "secondary")
        copy_btn.clicked.connect(self._copy)
        row.addWidget(copy_btn)

        export_btn = QPushButton("导出")
        export_btn.setProperty("category", "secondary")
        export_btn.clicked.connect(self._export)
        row.addWidget(export_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setProperty("category", "danger")
        clear_btn.clicked.connect(self._clear)
        row.addWidget(clear_btn)

        layout.addLayout(row)

    def _append(self, level: str, message: str):
        ts = time.strftime("%H:%M:%S")
        color = _LEVEL_COLOR.get(level, "#6b7280")
        self._entries.append((ts, level, message))
        self._render()

    def _render(self):
        lines = []
        for ts, level, msg in self._entries:
            color = _LEVEL_COLOR.get(level, "#6b7280")
            lines.append(
                f'<span style="color:#9ca3af;">[{ts}]</span> '
                f'<span style="color:{color};">[{level.upper()}]</span> '
                f'<span style="color:{color};">{msg}</span>'
            )
        self.view.setHtml("<br>".join(lines))
        if self.auto_scroll_cb.isChecked():
            scrollbar = self.view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _copy(self):
        text = "\n".join(f"[{ts}] [{level.upper()}] {msg}" for ts, level, msg in self._entries)
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        signal_bus.connection_message.emit("success", "日志已复制到剪贴板")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "linkerhand_log.txt", "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for ts, level, msg in self._entries:
                    f.write(f"[{ts}] [{level.upper()}] {msg}\n")
            signal_bus.connection_message.emit("success", f"日志已导出：{path}")
        except Exception as e:
            signal_bus.connection_message.emit("error", f"导出失败：{e}")

    def _clear(self):
        if not self._entries:
            return
        reply = QMessageBox.question(self, "确认清空", "确定清空所有日志吗？")
        if reply == QMessageBox.Yes:
            self._entries.clear()
            self._render()

    def set_compact_mode(self, compact: bool):
        pass
