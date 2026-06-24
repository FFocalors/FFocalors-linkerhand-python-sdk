#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局信号总线。

组件之间通过单一信号总线通信，避免互相持有引用。
所有信号都从 GUI 主线程发出和接收，跨线程时 Qt 会自动排队。
"""
import os
import time

from PyQt5.QtCore import QObject, pyqtSignal


COMMAND_TRACE_LOG = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "test_out.log")
)


def command_trace(message: str):
    """Write command-chain diagnostics to terminal and test_out.log."""
    line = f"[CommandTrace] {message}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(COMMAND_TRACE_LOG), exist_ok=True)
        with open(COMMAND_TRACE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception as exc:
        print(f"[CommandTrace] log write failed: {exc}", flush=True)


def sanitize_finger_pose(pose, expected_len=None):
    if not isinstance(pose, (list, tuple)):
        return None, False, "pose is not list/tuple"
    if expected_len is not None and len(pose) != int(expected_len):
        return None, False, f"pose length {len(pose)} != {expected_len}"
    safe = []
    changed = False
    for idx, value in enumerate(pose):
        if value is None:
            return None, changed, f"pose[{idx}] is None"
        try:
            numeric = float(value)
        except Exception:
            return None, changed, f"pose[{idx}] is not numeric: {value!r}"
        rounded = int(round(numeric))
        clamped = int(max(0, min(255, rounded)))
        if value != clamped:
            changed = True
        safe.append(clamped)
    return safe, changed, ""


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
    connection_changed = pyqtSignal(str)        # "connected" | "offline" | "disconnected" | "connecting" | "error"
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

    # —— 自适应抓取相关 ——
    grasp_state_changed = pyqtSignal(object)            # 当前总状态 (GraspState)
    grasp_joint_state_changed = pyqtSignal(int, object)  # 关节索引, 关节状态 (GraspJointState)
    grasp_contact_detected = pyqtSignal(int, object)     # 关节索引, 接触评分 (float)
    grasp_completed = pyqtSignal(object)                # 抓取结果
    grasp_failed = pyqtSignal(str)                      # 失败原因
    grasp_aborted = pyqtSignal(str)                     # 中止原因
    grasp_curve_event = pyqtSignal(object)              # 曲线事件对象 (dict)


# 单例
signal_bus = SignalBus()


def emit_finger_move_requested(pose, source="GUI"):
    command_trace(f"GUI request source={source} pose={pose!r}")
    safe, changed, reason = sanitize_finger_pose(pose)
    if safe is None:
        command_trace(f"invalid pose source={source}: {reason}; raw={pose!r}")
        return False
    if changed:
        command_trace(f"pose sanitized source={source}: raw={pose!r} safe={safe}")
    command_trace(f"signal emit finger_move_requested source={source} pose={safe}")
    signal_bus.finger_move_requested.emit(safe)
    return True
