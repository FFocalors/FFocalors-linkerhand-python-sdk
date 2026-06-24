#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空状态占位卡片。"""
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from lhgui.styles.theme_manager import get_theme_manager, is_dark_theme
from lhgui.utils.icon_helper import get_icon


class EmptyStateCard(QFrame):
    def __init__(self, icon_name: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateCard")
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 40, 40, 40)

        self._icon_label = QLabel()
        self._refresh_icon()
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("EmptyStateTitle")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet("color:#6b7280;")
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setWordWrap(True)
        layout.addWidget(sub_lbl)

        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(lambda _name: self._refresh_icon())

    def _refresh_icon(self):
        color = "#7EA2FF" if is_dark_theme() else "#4F7FF7"
        self._icon_label.setPixmap(
            get_icon(self._icon_name, size=48, color=color, target_widget=self).pixmap(48, 48)
        )
