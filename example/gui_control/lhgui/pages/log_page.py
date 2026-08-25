#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志页面。"""
import time
import html
from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QCheckBox, QFileDialog, QMessageBox
)
from PyQt5.QtGui import QClipboard
from PyQt5.QtCore import Qt, QTimer

from lhgui.utils.signal_bus import signal_bus


_LEVEL_COLOR = {
    "info": "#6b7280",
    "success": "#166534",
    "warning": "#92400e",
    "error": "#991b1b",
}
_DARK_LEVEL_COLOR = {
    "info": "#AEBBCD",
    "success": "#61D49A",
    "warning": "#F2B84B",
    "error": "#FF8585",
}


class LogPage(QWidget):
    MAX_ENTRIES = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._entries = deque(maxlen=self.MAX_ENTRIES)
        self._pending_entries = []
        self._theme_dirty = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_pending)
        self._build()
        signal_bus.connection_message.connect(self._append)
        from lhgui.styles.theme_manager import get_theme_manager
        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(self._on_theme_changed)

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
        # Keep the document bounded independently of the Python deque. New
        # entries are inserted as blocks; Qt drops the oldest block in O(1)
        # when the limit is reached, so capacity does not trigger setHtml.
        self.view.document().setMaximumBlockCount(self.MAX_ENTRIES)
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
        self._entries.append((ts, level, message))
        self._pending_entries.append((ts, level, message))
        self._schedule_render()

    def _schedule_render(self):
        if self._render_timer.isActive() or not self.isVisible():
            return
        # 20 Hz 足以反映生命周期日志，同时把突发消息合并成一次 Qt 文档更新。
        self._render_timer.start(50)

    def _on_theme_changed(self, _name):
        self._theme_dirty = True
        if self.isVisible():
            self._schedule_render()

    def showEvent(self, event):
        super().showEvent(event)
        if self._theme_dirty or self._pending_entries:
            self._schedule_render()

    @staticmethod
    def _line_html(ts, level, msg, dark=False):
        colors = _DARK_LEVEL_COLOR if dark else _LEVEL_COLOR
        timestamp_color = "#91A1B6" if dark else "#9ca3af"
        color = colors.get(level, colors["info"])
        return (
            f'<span style="color:{timestamp_color};">[{html.escape(str(ts))}]</span> '
            f'<span style="color:{color};">[{html.escape(str(level).upper())}]</span> '
            f'<span style="color:{color};">{html.escape(str(msg))}</span>'
        )

    def _render(self):
        from lhgui.styles.theme_manager import is_dark_theme
        dark = is_dark_theme()
        lines = [f"<div>{self._line_html(ts, level, msg, dark)}</div>"
                 for ts, level, msg in self._entries]
        self.view.setHtml("".join(lines))
        self._pending_entries.clear()
        self._theme_dirty = False
        if self.auto_scroll_cb.isChecked():
            scrollbar = self.view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _flush_pending(self):
        if not self.isVisible():
            return
        if self._theme_dirty:
            self._render()
            return
        if self._pending_entries:
            from lhgui.styles.theme_manager import is_dark_theme
            dark = is_dark_theme()
            cursor = self.view.textCursor()
            cursor.movePosition(cursor.End)
            for ts, level, msg in self._pending_entries:
                cursor.insertHtml(self._line_html(ts, level, msg, dark))
                cursor.insertBlock()
            self._pending_entries.clear()
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
