#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小游戏占位页面。"""
from PyQt5.QtWidgets import QVBoxLayout

from lhgui.widgets.empty_state_card import EmptyStateCard


class GamePage(EmptyStateCard):
    def __init__(self, parent=None):
        super().__init__("game", "小游戏", "功能开发中\n后续将加载基于手势控制的游戏模块", parent)
        self.setObjectName("GamePage")

    def set_compact_mode(self, compact: bool):
        pass
