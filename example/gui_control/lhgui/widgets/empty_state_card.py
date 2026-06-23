#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空状态占位卡片。"""
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from lhgui.utils.icon_helper import get_icon


class EmptyStateCard(QFrame):
    def __init__(self, icon_name: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateCard")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 40, 40, 40)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon(icon_name, size=48).pixmap(48, 48))
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("EmptyStateTitle")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet("color:#6b7280;")
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setWordWrap(True)
        layout.addWidget(sub_lbl)
