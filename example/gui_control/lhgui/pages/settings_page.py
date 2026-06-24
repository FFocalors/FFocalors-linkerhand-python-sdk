#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置占位页面。"""
from PyQt5.QtWidgets import QPushButton, QVBoxLayout

from lhgui.config.constants import HAND_CONFIGS
from lhgui.core.api_manager import ApiManager
from lhgui.utils.signal_bus import command_trace, emit_finger_move_requested, signal_bus
from lhgui.widgets.empty_state_card import EmptyStateCard


class SettingsPage(EmptyStateCard):
    def __init__(self, parent=None):
        super().__init__("settings", "设置", "运行时设置功能开发中\n当前配置仍通过 setting.yaml 管理", parent)
        self.setObjectName("SettingsPage")
        self.selfcheck_btn = QPushButton("下发链路自检：SAFE_OPEN")
        self.selfcheck_btn.setProperty("category", "primary")
        self.selfcheck_btn.clicked.connect(self._command_selfcheck)
        self.layout().addWidget(self.selfcheck_btn)

    def _command_selfcheck(self):
        api = ApiManager._instance
        hand_joint = api.hand_joint if api and api.hand_joint in HAND_CONFIGS else "O6"
        config = HAND_CONFIGS[hand_joint]
        pose = list((config.preset_actions or {}).get("张开", config.init_pos))
        command_trace(f"selfcheck requested hand_joint={hand_joint} pose={pose}")
        ok = emit_finger_move_requested(pose, source="SettingsPage:selfcheck_SAFE_OPEN")
        level = "info" if ok else "error"
        signal_bus.connection_message.emit(level, "下发链路自检已触发，请查看 [CommandTrace] 日志")

    def set_compact_mode(self, compact: bool):
        pass
