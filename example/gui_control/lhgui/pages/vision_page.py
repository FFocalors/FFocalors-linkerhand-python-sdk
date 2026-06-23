#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉识别占位页面。"""
from PyQt5.QtWidgets import QVBoxLayout

from lhgui.widgets.empty_state_card import EmptyStateCard


class VisionPage(EmptyStateCard):
    def __init__(self, parent=None):
        super().__init__("vision", "视觉识别", "功能开发中\n后续将接入摄像头与识别模型", parent)
        self.setObjectName("VisionPage")

    def set_compact_mode(self, compact: bool):
        pass
