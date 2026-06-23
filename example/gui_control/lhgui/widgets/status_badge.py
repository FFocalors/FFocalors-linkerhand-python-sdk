#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态标签。"""
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt

from lhgui.utils.style_utils import set_dynamic_property


class StatusBadge(QLabel):
    def __init__(self, text: str = "", level: str = "disconnected", parent=None):
        super().__init__(text, parent)
        self.setObjectName("StatusBadge")
        self.setAlignment(Qt.AlignCenter)
        self.set_level(level)

    def set_level(self, level: str):
        set_dynamic_property(self, "level", level)
