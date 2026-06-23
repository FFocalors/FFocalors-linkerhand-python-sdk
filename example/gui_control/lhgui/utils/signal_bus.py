#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局信号总线。

组件之间通过单一信号总线通信，避免互相持有引用。
所有信号都从 GUI 主线程发出和接收，跨线程时 Qt 会自动排队。
"""
from PyQt5.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    # —— 页面切换 ——
    page_changed = pyqtSignal(object)           # Page enum

    # —— 动作生命周期 ——
    action_started = pyqtSignal(str)            # action_name
    action_finished = pyqtSignal(str)           # action_name
    action_failed = pyqtSignal(str, str)        # action_name, reason
    action_cancelled = pyqtSignal(str)          # action_name
    home_requested = pyqtSignal(str, list)      # action_name, positions
    custom_presets_changed = pyqtSignal()       # 自定义预设更改信号

    # —— UI 状态快照 ——
    ui_state_changed = pyqtSignal(object)       # UiStateSnapshot

    # —— 连接相关 ——
    connection_changed = pyqtSignal(str)        # "connected" | "disconnected" | "connecting" | "error"
    connection_message = pyqtSignal(str, str)   # level("info"|"warning"|"error"|"success"), message
    request_reconnect = pyqtSignal()            # 请求重连
    hand_info_ready = pyqtSignal(dict)          # 连接成功后下发手部信息(hand_type/hand_joint/serial/version)

    # —— 指令下发 ——
    finger_move_requested = pyqtSignal(list)    # 发送关节位置
    speed_set_requested = pyqtSignal(list)      # 设置速度
    torque_set_requested = pyqtSignal(list)     # 设置扭矩

    # —— 数据上行 ——
    joint_state_updated = pyqtSignal(list)      # 当前关节位置(来自硬件反馈)
    waveform_updated = pyqtSignal(dict)         # 曲线数据 {"state": [...], "current": [...], ...}
    matrix_updated = pyqtSignal(dict)           # 触觉矩阵数据

    # —— 预设动作 ——
    preset_triggered = pyqtSignal(str, list)    # action_name, positions

    # —— 录制 / 回放 ——
    record_started = pyqtSignal()
    record_stopped = pyqtSignal(str)            # 保存的动作名(空串表示放弃)
    playback_started = pyqtSignal()
    playback_stopped = pyqtSignal()
    playback_progress = pyqtSignal(int, int)    # 当前帧, 总帧数

    # —— 演示模式 ——
    demo_mode_toggled = pyqtSignal(bool)        # True=进入演示, False=回到开发


# 单例
signal_bus = SignalBus()
