#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""侧边栏导航项：真实指示条组件。

外层 QWidget + 左侧 3px 指示条 + QToolButton（图标 + 文字）。
选中时指示条显色 + 背景高亮，不依赖 QSS ::indicator。
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QFrame, QToolButton, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon

from lhgui.styles.theme_manager import get_theme_manager, is_dark_theme
from lhgui.utils.icon_helper import get_pixmap
from lhgui.utils.style_utils import set_dynamic_property


class SidebarItem(QWidget):
    clicked = pyqtSignal(object)   # 发射 page

    def __init__(self, page, text: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.page = page
        self._icon_name = icon_name
        self._active = False
        self.setObjectName("SidebarItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧指示条
        self.indicator = QFrame(self)
        self.indicator.setObjectName("SidebarActiveIndicator")
        self.indicator.setFixedWidth(3)
        self.indicator.setStyleSheet("background-color: transparent; border: none;")
        layout.addWidget(self.indicator)

        # 按钮
        self.button = QToolButton(self)
        self.button.setObjectName("SidebarButton")
        self.button.setText(text)
        self._refresh_icon()
        self.button.setIconSize(QSize(20, 20))
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setCheckable(True)
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.button.clicked.connect(lambda: self.clicked.emit(self.page))
        self.button.setToolTip(text)
        layout.addWidget(self.button)

        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(lambda _name: self._refresh_icon())

    def _refresh_icon(self):
        """为所有 QIcon 状态提供同一高对比位图，避免 Qt 自动压暗图标。"""
        if is_dark_theme():
            color = "#7EA2FF" if self._active else "#C2CDDB"
        else:
            color = "#4F7FF7" if self._active else "#334155"
        pixmap = get_pixmap(self._icon_name, 20, color=color, target_widget=self)
        icon = QIcon()
        for mode in (QIcon.Normal, QIcon.Disabled, QIcon.Active, QIcon.Selected):
            icon.addPixmap(pixmap, mode, QIcon.Off)
            icon.addPixmap(pixmap, mode, QIcon.On)
        self.button.setIcon(icon)

    def set_active(self, active: bool):
        self._active = active
        self.button.blockSignals(True)
        self.button.setChecked(active)
        self.button.blockSignals(False)
        if active:
            self.indicator.setStyleSheet("background-color: #4f8cff; border: none;")
        else:
            self.indicator.setStyleSheet("background-color: transparent; border: none;")
        set_dynamic_property(self, "active", "true" if active else "false")
        self._refresh_icon()

    def set_compact(self, compact: bool):
        self.button.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)
        self.button.setToolTip(self.button.text() or "")

    def set_icon_color_active(self, active: bool):
        # 选中态图标颜色由 QSS 控制；此处预留
        pass
