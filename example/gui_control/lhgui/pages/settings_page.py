#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置占位页面。"""
from PyQt5.QtWidgets import QVBoxLayout

from lhgui.widgets.empty_state_card import EmptyStateCard


class SettingsPage(EmptyStateCard):
    def __init__(self, parent=None):
        super().__init__("settings", "设置", "运行时设置功能开发中\n当前配置仍通过 setting.yaml 管理", parent)
        self.setObjectName("SettingsPage")

    def set_compact_mode(self, compact: bool):
        pass
