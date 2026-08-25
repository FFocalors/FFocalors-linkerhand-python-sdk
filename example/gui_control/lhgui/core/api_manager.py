#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe facade for the LinkerHand device runtime.

``ApiManager`` intentionally contains no hardware calls.  It lives in the
GUI thread and only validates requests, updates a small snapshot cache and
pushes bounded commands into :class:`DeviceIoWorker`'s mailbox.  The worker
owns the SDK object and its complete lifecycle in a dedicated QThread.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from lhgui.config.constants import HAND_CONFIGS
from lhgui.core.device_io_worker import DeviceIoWorker
from lhgui.utils.signal_bus import command_trace, sanitize_finger_pose, signal_bus
from LinkerHand.utils.load_write_yaml import LoadWriteYaml


class _ApiInfoProxy:
    """Compatibility object for legacy UI code that reads ``api.api``.

    It exposes cached metadata only; it never forwards calls to the real SDK.
    """

    def __init__(self, manager: "ApiManager"):
        self._manager = manager

    def get_embedded_version(self):
        return self._manager.firmware_version or "unknown"

    def get_serial_number(self):
        return self._manager.serial_number or "-1"


class ApiManager(QObject):
    _instance = None

    api_ready = pyqtSignal(bool)
    snapshot_ready = pyqtSignal(dict)
    matrix_ready = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        ApiManager._instance = self
        self.yaml = LoadWriteYaml()
        self.hand_joint: Optional[str] = None
        self.hand_type: Optional[str] = None
        self.is_touch = False
        self.can = "PCAN_USBBUS1"
        self.modbus = "None"
        self._connected = False
        self._offline_mode = False
        self.saved_torque: Optional[List[int]] = None
        self._firmware_version: Optional[str] = None
        self._serial_number: Optional[str] = None
        self._snapshot = {"state": [], "current": [], "speed": []}
        self._virtual_pose = [250] * 6
        self._matrix = None
        self._shutdown = False

        self._read_config()
        # The configured joint model is known only after _read_config().
        # Initialise the compatibility virtual pose with its real arity so
        # offline L10/L25 flows never fall back to a six-joint pose.
        config = HAND_CONFIGS.get(self.hand_joint)
        self._virtual_pose = list(config.init_pos) if config else [250] * 6
        self._thread = QThread()
        self._worker = DeviceIoWorker(
            self.hand_joint,
            self.hand_type,
            self.modbus,
            self.can,
            is_touch=self.is_touch,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.connection_event.connect(self._on_connection_event)
        self._worker.message_event.connect(self._on_worker_message)
        self._worker.api_ready.connect(self._on_api_ready)
        self._worker.snapshot_ready.connect(self._on_snapshot)
        self._worker.matrix_ready.connect(self._on_matrix)
        self._thread.start()
        self._wire_signals()

    # —— 配置 ——
    def _read_config(self):
        setting = self.yaml.load_setting_yaml()
        if not setting:
            signal_bus.connection_message.emit("error", "配置文件 setting.yaml 读取失败")
            return
        lh = setting["LINKER_HAND"]
        left = lh["LEFT_HAND"]
        right = lh["RIGHT_HAND"]
        if left["EXISTS"]:
            cfg = left
            self.hand_type = "left"
        elif right["EXISTS"]:
            cfg = right
            self.hand_type = "right"
        else:
            signal_bus.connection_message.emit("error", "setting.yaml 中左右手 EXISTS 均为 False")
            return
        self.hand_joint = cfg["JOINT"]
        self.is_touch = bool(cfg["TOUCH"])
        self.can = cfg["CAN"]
        self.modbus = cfg.get("MODBUS", "None")
        signal_bus.connection_message.emit(
            "info",
            f"当前配置：Linker Hand {self.hand_type} {self.hand_joint} "
            f"压感:{self.is_touch} modbus:{self.modbus} CAN:{self.can}",
        )
        command_trace(
            f"config hand_type={self.hand_type} hand_joint={self.hand_joint} "
            f"touch={self.is_touch} modbus={self.modbus} CAN={self.can}"
        )

    def _wire_signals(self):
        signal_bus.request_reconnect.connect(self.reconnect)
        signal_bus.finger_move_requested.connect(self.finger_move)
        signal_bus.speed_set_requested.connect(self.set_speed)
        signal_bus.torque_set_requested.connect(self.set_torque)

    @property
    def api(self):
        # Legacy code uses this only as an availability check and to read
        # firmware metadata.  Never expose the LinkerHandApi instance here.
        return _ApiInfoProxy(self) if self._connected else None

    @property
    def firmware_version(self):
        return self._firmware_version

    @property
    def serial_number(self):
        return self._serial_number

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    # 生命周期：全部只是入队，不执行 SDK
    def connect(self):
        if self.hand_joint is None:
            signal_bus.connection_changed.emit("error")
            return
        self._worker.submit_connect()

    def reconnect(self):
        signal_bus.connection_changed.emit("connecting")
        signal_bus.connection_message.emit("info", "正在重新连接…")
        self._worker.submit_reconnect()

    def disconnect(self):
        self._worker.submit_disconnect()

    def start_polling(self):
        """Enable worker-side telemetry deadlines (thread-safe mailbox flag)."""
        self._worker.set_polling(True)

    def stop_polling(self):
        self._worker.set_polling(False)

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown = True
        done = threading.Event()
        self._worker.submit_shutdown(done)
        done.wait(2.5)
        self._thread.quit()
        self._thread.wait(2500)

    # 指令：校验后写入有界邮箱
    def finger_move(self, pose: List[int]):
        expected_len = len(HAND_CONFIGS[self.hand_joint].init_pos) if self.hand_joint in HAND_CONFIGS else None
        command_trace(f"ApiManager received finger_move pose={pose!r}")
        safe_pose, changed, reason = sanitize_finger_pose(pose, expected_len=expected_len)
        if safe_pose is None:
            command_trace(f"invalid pose: {reason}; raw={pose!r}")
            signal_bus.connection_message.emit("error", f"非法关节位置，已忽略：{reason}")
            return
        if changed:
            command_trace(f"pose sanitized in ApiManager: raw={pose!r} safe={safe_pose}")
        if not self._connected and not self._offline_mode:
            signal_bus.connection_message.emit("warning", "设备未连接，操作被忽略")
            command_trace("skipped because api not connected")
            return
        self._worker.submit_finger(safe_pose)

    def set_speed(self, speed: List[int]):
        if not self._connected and not self._offline_mode:
            signal_bus.connection_message.emit("warning", "设备未连接，操作被忽略")
            return
        self._worker.submit_speed(list(speed))

    def set_torque(self, torque: List[int]):
        self.saved_torque = list(torque)
        if not self._connected and not self._offline_mode:
            signal_bus.connection_message.emit("warning", "设备未连接，操作被忽略")
            return
        self._worker.submit_torque(list(torque))

    def set_temporary_torque(self, torque: List[int]):
        if self.saved_torque is None:
            self.saved_torque = [255] * len(torque)
        if self._connected:
            self._worker.submit_torque(list(torque), temporary=True)

    def restore_saved_torque(self):
        if self.saved_torque is not None and self._connected:
            self._worker.submit_restore_torque(list(self.saved_torque))

    # 数据：只读缓存，供旧调用方兼容
    def get_state(self):
        return list(self._snapshot.get("state") or []) or None

    def get_current(self):
        return list(self._snapshot.get("current") or []) or None

    def get_speed(self):
        return list(self._snapshot.get("speed") or []) or None

    def get_matrix_touch(self):
        return self._matrix

    # worker 回调（由 Qt 自动排队到 GUI 线程）
    def _on_api_ready(self, ready: bool):
        self.api_ready.emit(bool(ready))

    def _on_connection_event(self, status: str, version, serial, reason):
        if status == "connecting":
            signal_bus.connection_changed.emit("connecting")
            return
        if status == "connected":
            self._connected = True
            self._offline_mode = False
            self._firmware_version = str(version)
            self._serial_number = str(serial)
            signal_bus.connection_changed.emit("connected")
            signal_bus.connection_message.emit("success", "已连接设备")
            signal_bus.hand_info_ready.emit({
                "hand_type": self.hand_type,
                "hand_joint": self.hand_joint,
                "is_touch": self.is_touch,
                "version": version,
                "serial": serial,
                "joint_count": len(HAND_CONFIGS[self.hand_joint].joint_names),
            })
            command_trace(f"connect success version={version!r} serial={serial!r}")
        elif status == "offline":
            self._connected = False
            self._offline_mode = True
            self._firmware_version = str(version or "Virtual")
            self._serial_number = str(serial or "Virtual-Mode")
            signal_bus.connection_changed.emit("offline")
            signal_bus.connection_message.emit("warning", f"物理连接失败：{reason}。已自动切入虚拟/离线调试模式。")
            signal_bus.hand_info_ready.emit({
                "hand_type": self.hand_type,
                "hand_joint": self.hand_joint,
                "is_touch": self.is_touch,
                "version": self._firmware_version,
                "serial": self._serial_number,
                "joint_count": len(HAND_CONFIGS[self.hand_joint].joint_names) if self.hand_joint in HAND_CONFIGS else 6,
            })
        elif status == "disconnected":
            self._connected = False
            self._offline_mode = False
            signal_bus.connection_changed.emit("disconnected")
            signal_bus.connection_message.emit("info", "已断开连接")
        elif status == "error":
            signal_bus.connection_changed.emit("error")
            if reason:
                signal_bus.connection_message.emit("error", str(reason))

    def _on_worker_message(self, level: str, message: str):
        signal_bus.connection_message.emit(level, message)

    def _on_snapshot(self, snapshot: dict):
        self._snapshot = {
            "state": list(snapshot.get("state") or []),
            "current": list(snapshot.get("current") or []),
            "speed": list(snapshot.get("speed") or []),
        }
        if self._snapshot["state"]:
            self._virtual_pose = list(self._snapshot["state"])
        self.snapshot_ready.emit(dict(self._snapshot))
        signal_bus.waveform_updated.emit(dict(self._snapshot))
        if self._snapshot["state"]:
            signal_bus.joint_state_updated.emit(list(self._snapshot["state"]))

    def _on_matrix(self, matrix: dict):
        self._matrix = matrix
        self.matrix_ready.emit(dict(matrix))
        signal_bus.matrix_updated.emit(dict(matrix))
