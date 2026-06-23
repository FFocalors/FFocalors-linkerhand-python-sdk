#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""左侧导航栏（使用 SidebarItem 指示条）。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSpacerItem, QSizePolicy
from PyQt5.QtCore import Qt

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import Page
from lhgui.utils.style_utils import set_dynamic_property
from lhgui.widgets.sidebar_item import SidebarItem


_NAV_ITEMS = [
    (Page.CONSOLE, "控制台", "console"),
    (Page.VISION, "视觉识别", "vision"),
    (Page.GAME, "小游戏", "game"),
    (Page.LOG, "日志", "log"),
    (Page.SETTINGS, "设置", "settings"),
]


class Sidebar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self._items = {}
        self._build()
        signal_bus.page_changed.connect(self._on_page_changed)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(2)

        for page, text, icon in _NAV_ITEMS:
            item = SidebarItem(page, text, icon)
            item.clicked.connect(self._on_click)
            self._items[page] = item
            layout.addWidget(item)

        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def _on_click(self, page):
        signal_bus.page_changed.emit(page)

    def _on_page_changed(self, page: Page):
        for p, item in self._items.items():
            item.set_active(p == page)

    def set_compact(self, compact: bool):
        set_dynamic_property(self, "compact", "true" if compact else "false")
        for item in self._items.values():
            item.set_compact(compact)
