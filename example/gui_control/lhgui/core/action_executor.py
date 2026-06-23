#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动作执行器。

统一管理预设动作、恢复初始位置等离散动作的生命周期。
底层 `LinkerHandApi.finger_move` 为同步调用且无完成回调，因此使用安全超时
（默认 300ms）后清除 ACTION_RUNNING 状态。
"""
from PyQt5.QtCore import QObject, QTimer

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState


class ActionExecutor(QObject):
    ACTION_TIMEOUT_MS = 300

    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._current_name = None

        signal_bus.preset_triggered.connect(self.execute)
        signal_bus.home_requested.connect(self.home)

    def execute(self, name: str, positions: list):
        if ui_state.snapshot.connection != ConnectionState.CONNECTED:
            signal_bus.connection_message.emit("warning", "设备未连接，动作未执行")
            return
        if ui_state.snapshot.action not in (ActionState.IDLE, ActionState.CYCLE_RUNNING):
            signal_bus.connection_message.emit("warning", f"当前有动作运行中，忽略 {name}")
            return

        # 1. 检测是否是自定义预设动作（name 在这里为 preset_id）
        from lhgui.core.custom_preset_store import custom_preset_store
        preset = custom_preset_store.get(name)

        from lhgui.config.constants import HAND_CONFIGS
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        hand_model = api.hand_joint if (api and api.hand_joint) else "O6"

        final_positions = list(positions)

        if preset:
            # 校验手型号是否一致
            if preset.hand_model != hand_model:
                signal_bus.connection_message.emit("error", f"动作预设型号 {preset.hand_model} 与当前硬件 {hand_model} 不匹配，拒绝执行。")
                return

            config = HAND_CONFIGS.get(hand_model)
            total_joints = len(config.init_pos) if config else 6

            # 如果是非 L6 的多关节型号，执行前必须根据当前实时反馈补位，保证隐藏关节不误动
            if total_joints > 6:
                from lhgui.core.joint_state_cache import joint_state_cache
                # 校验设备最新关节状态缓存是否鲜活且可用（有效期 5.0 秒）
                if not joint_state_cache.is_fresh(hand_model, max_age_seconds=5.0):
                    signal_bus.connection_message.emit("error", "当前设备未提供完整关节反馈，无法安全执行自定义预设。")
                    return
                snapshot = joint_state_cache.latest(hand_model)
                if not snapshot:
                    signal_bus.connection_message.emit("error", "无法获取当前设备实时关节反馈。")
                    return

                # 补位策略：非编辑关节保持当前实时值，前 6 个编辑关节覆盖对应位置
                fresh_values = list(snapshot.values)
                for idx in range(min(6, len(fresh_values))):
                    if idx < len(positions):
                        fresh_values[idx] = positions[idx]
                final_positions = fresh_values

        self._current_name = name
        ui_state.set_action_state(ActionState.ACTION_RUNNING)
        signal_bus.action_started.emit(name)
        signal_bus.finger_move_requested.emit([int(v) for v in final_positions])
        self._timer.start(self.ACTION_TIMEOUT_MS)

    def home(self, name: str, positions: list):
        self.execute(name, positions)

    def _on_timeout(self):
        name = self._current_name
        self._current_name = None
        ui_state.set_action_state(ActionState.IDLE)
        signal_bus.action_finished.emit(name or "")

    def cancel(self):
        if self._current_name:
            name = self._current_name
            self._timer.stop()
            self._current_name = None
            ui_state.set_action_state(ActionState.IDLE)
            signal_bus.action_cancelled.emit(name)
