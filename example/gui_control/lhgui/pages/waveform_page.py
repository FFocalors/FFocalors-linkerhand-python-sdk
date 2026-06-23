#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时曲线页面：承载可折叠/全屏的曲线面板。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog, QShortcut
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import Page
from lhgui.utils.icon_helper import get_icon
from lhgui.widgets.waveform_panel import WaveformPanel


class WaveformPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WaveformPage")
        self._panel = WaveformPanel()
        self._placeholder = QWidget()
        self._placeholder.setMinimumHeight(200)
        self._dialog = None
        self._is_fullscreen = False
        self._orig_parent = None
        self._orig_layout = None
        self._orig_index = -1
        self._orig_stretch = 0
        self._prev_collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self._panel)

        self._panel.fullscreen_requested.connect(self._enter_fullscreen)
        signal_bus.page_changed.connect(self._on_page_changed)

    def _on_page_changed(self, page: Page):
        if page != Page.WAVEFORM and self._is_fullscreen:
            self._exit_fullscreen()

    def _enter_fullscreen(self):
        if self._is_fullscreen:
            return
        self._is_fullscreen = True
        self._prev_collapsed = self._panel.collapsed
        self._panel.set_collapsed(False)

        # 记录原布局信息
        self._orig_parent = self._panel.parentWidget()
        self._orig_layout = self._orig_parent.layout()
        self._orig_index = self._orig_layout.indexOf(self._panel)
        self._orig_stretch = self._orig_layout.stretch(self._orig_index)

        # 插入占位
        self._orig_layout.insertWidget(self._orig_index, self._placeholder)
        self._orig_layout.setStretch(self._orig_layout.indexOf(self._placeholder), self._orig_stretch)

        # 从原布局移除并移到对话框
        self._orig_layout.removeWidget(self._panel)
        self._panel.hide()

        self._dialog = QDialog(self.window())
        self._dialog.setWindowTitle("实时曲线 - 全屏")
        self._dialog.setWindowState(Qt.WindowMaximized)
        dlg_layout = QVBoxLayout(self._dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(0)
        dlg_layout.addWidget(self._panel)

        self._dialog.finished.connect(self._exit_fullscreen)
        QShortcut(QKeySequence("Esc"), self._dialog, activated=self._exit_fullscreen)

        self._panel.show()
        self._dialog.showMaximized()

    def exit_fullscreen(self):
        self._exit_fullscreen()

    def _exit_fullscreen(self):
        if not self._is_fullscreen:
            return
        self._is_fullscreen = False

        if self._dialog:
            self._dialog.finished.disconnect(self._exit_fullscreen)
            self._dialog.close()

        self._panel.hide()
        dlg_layout = self._dialog.layout()
        if dlg_layout:
            dlg_layout.removeWidget(self._panel)

        self._panel.setParent(self._orig_parent)

        # 移除占位并放回原位
        if self._orig_layout:
            idx = self._orig_layout.indexOf(self._placeholder)
            self._orig_layout.removeWidget(self._placeholder)
            self._placeholder.setParent(None)
            if 0 <= self._orig_index <= self._orig_layout.count():
                self._orig_layout.insertWidget(self._orig_index, self._panel)
            else:
                self._orig_layout.addWidget(self._panel)
            self._orig_layout.setStretch(self._orig_layout.indexOf(self._panel), self._orig_stretch)

        self._panel.set_collapsed(self._prev_collapsed)
        self._panel.show()
        self._panel.raise_()
        self._panel.canvas.draw_idle()

        self._dialog = None

    def set_compact_mode(self, compact: bool):
        pass
