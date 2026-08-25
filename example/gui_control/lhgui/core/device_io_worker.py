#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serialised LinkerHand I/O worker.

The SDK uses synchronous CAN/RS485 calls.  This object is deliberately kept
small and owns the SDK instance for its whole lifetime.  It must only be
used from the :class:`QThread` it is moved to; the ``submit_*`` methods are
the exception: they only touch a lock-protected command mailbox and never
touch the SDK, so they are safe to call from the GUI thread.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import OrderedDict, deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import command_trace
from LinkerHand.linker_hand_api import LinkerHandApi


Command = Tuple[str, Any]


class DeviceIoWorker(QObject):
    """Own the physical API and execute all I/O serially.

    Finger moves use a single latest-value slot.  Parameter changes and
    lifecycle operations are bounded priority commands.  A 10 ms service
    timer drains at most one hardware operation at a time, while deadlines
    prevent a slow read from causing a second overlapping read.
    """

    connection_event = pyqtSignal(str, object, object, object)
    message_event = pyqtSignal(str, str)
    snapshot_ready = pyqtSignal(dict)
    matrix_ready = pyqtSignal(dict)
    api_ready = pyqtSignal(bool)

    def __init__(
        self,
        hand_joint: Optional[str],
        hand_type: Optional[str],
        modbus: str,
        can: str,
        is_touch: bool = False,
        api_factory: Callable[..., Any] = LinkerHandApi,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.hand_joint = hand_joint
        self.hand_type = hand_type
        self.modbus = modbus
        self.can = can
        self.is_touch = bool(is_touch)
        self._api_factory = api_factory

        self._api: Any = None
        self._connected = False
        self._offline_mode = False
        self._firmware_version: Optional[str] = None
        self._serial: Optional[str] = None
        self._virtual_pose: List[int] = self._initial_pose()
        self._consecutive_failures = 0

        self._lock = threading.Lock()
        # Keep lifecycle commands separate from coalesced parameter commands.
        # A bounded deque with maxlen would silently evict a shutdown or
        # disconnect command, so lifecycle entries are explicitly deduplicated
        # instead of relying on deque's implicit eviction semantics.
        self._lifecycle: deque[Command] = deque()
        self._parameters: OrderedDict[str, Any] = OrderedDict()
        self._parameter_limit = 4  # speed, torque, temporary, restore
        self._latest_finger: Optional[List[int]] = None
        self._latest_finger_at = 0.0
        self._shutdown_event: Optional[threading.Event] = None
        self._polling_enabled = False
        self._last_finger_sent = 0.0

        self._service_timer: Optional[QTimer] = None
        self._next_state = 0.0
        self._next_current = 0.0
        self._next_speed = 0.0
        self._next_matrix = 0.0
        self._last_snapshot: Dict[str, Any] = {
            "state": list(self._virtual_pose),
            "current": [],
            "speed": [],
        }

    @property
    def thread_api(self):
        """The real API, for diagnostics/tests only, never for GUI callers."""
        return self._api

    def _initial_pose(self) -> List[int]:
        config = HAND_CONFIGS.get(self.hand_joint)
        return list(config.init_pos) if config else [250] * 6

    @pyqtSlot()
    def start(self):
        """Create timers after the QThread event loop starts."""
        if self._service_timer is not None:
            return
        self._service_timer = QTimer(self)
        self._service_timer.setInterval(10)
        self._service_timer.timeout.connect(self._service)
        self._service_timer.start()

    # The following submit methods intentionally do not use @pyqtSlot.
    # ApiManager calls them directly across threads; they only enqueue data.
    def submit_connect(self):
        self._enqueue_urgent(("connect", None))

    def submit_reconnect(self):
        self._enqueue_urgent(("reconnect", None))

    def submit_disconnect(self):
        self._enqueue_urgent(("disconnect", None))

    def submit_shutdown(self, done: threading.Event):
        self._enqueue_urgent(("shutdown", done))

    def submit_finger(self, pose: List[int]):
        with self._lock:
            self._latest_finger = list(pose)
            self._latest_finger_at = time.monotonic()

    def submit_speed(self, values: List[int]):
        self._enqueue_latest_urgent("speed", list(values))

    def submit_torque(self, values: List[int], temporary: bool = False):
        self._enqueue_latest_urgent("temporary_torque" if temporary else "torque", list(values))

    def submit_restore_torque(self, values: List[int]):
        self._enqueue_latest_urgent("restore_torque", list(values))

    def set_polling(self, enabled: bool):
        with self._lock:
            self._polling_enabled = bool(enabled)

    def _enqueue_urgent(self, command: Command):
        with self._lock:
            name = command[0]
            if name == "shutdown":
                # Shutdown supersedes pending lifecycle work and is always
                # observed first.  Its Event remains attached to the command.
                self._lifecycle = deque(item for item in self._lifecycle if item[0] != "shutdown")
                self._lifecycle.appendleft(command)
                return
            if name == "reconnect":
                # A reconnect supersedes an unstarted connect/reconnect but
                # does not remove a pending disconnect that precedes it.
                self._lifecycle = deque(
                    item for item in self._lifecycle if item[0] not in {"connect", "reconnect"}
                )
            elif name in {"connect", "disconnect"}:
                # Repeated lifecycle requests are idempotent while queued.
                if any(item[0] == name for item in self._lifecycle):
                    return
            self._lifecycle.append(command)

    def _enqueue_latest_urgent(self, name: str, value: Any):
        with self._lock:
            # Every parameter kind has one slot.  This is a hard bound and
            # latest-wins merge; lifecycle commands are stored separately and
            # can never be evicted by this path.
            if name not in self._parameters and len(self._parameters) >= self._parameter_limit:
                self._parameters.popitem(last=False)
            self._parameters[name] = value

    def _take_next(self) -> Optional[Command]:
        with self._lock:
            if self._lifecycle:
                return self._lifecycle.popleft()
            if self._parameters:
                name, value = self._parameters.popitem(last=False)
                return name, value
            if self._latest_finger is not None:
                now = time.monotonic()
                if now - self._last_finger_sent >= 0.05:
                    pose = self._latest_finger
                    self._latest_finger = None
                    return ("finger", pose)
        return None

    @pyqtSlot()
    def _service(self):
        # Exactly one command/read runs at a time in this thread.  A timer
        # callback cannot re-enter itself, so slow SDK calls do not overlap.
        command = self._take_next()
        if command is not None:
            self._execute(command)

        if not self._polling_enabled or not self._connected or self._api is None:
            return
        now = time.monotonic()
        snapshot_changed = False
        if now >= self._next_state:
            self._next_state = now + 0.05
            snapshot_changed = self._poll_state(now) or snapshot_changed
        if now >= self._next_current:
            self._next_current = now + 0.10
            snapshot_changed = self._poll_current() or snapshot_changed
        if now >= self._next_speed:
            self._next_speed = now + 1.0
            snapshot_changed = self._poll_speed() or snapshot_changed
        if snapshot_changed:
            self.snapshot_ready.emit(dict(self._last_snapshot))
        if self._polling_enabled and self._next_matrix <= now and getattr(self, "is_touch", False):
            self._next_matrix = now + 0.5
            self._poll_matrix()

    def _execute(self, command: Command):
        name, value = command
        if name == "connect":
            self._connect()
        elif name == "reconnect":
            self._disconnect()
            self._connect()
        elif name == "disconnect":
            self._disconnect()
        elif name == "shutdown":
            self._polling_enabled = False
            self._disconnect()
            if value is not None:
                value.set()
            if self._service_timer is not None:
                self._service_timer.stop()
        elif name == "finger":
            self._finger_move(value)
        elif name == "speed":
            self._call("set_speed", value, error_label="设置速度")
        elif name in {"torque", "temporary_torque", "restore_torque"}:
            self._call("set_torque", value, error_label="设置扭矩", silent=name != "torque")

    def _connect(self):
        if not self.hand_joint:
            self.connection_event.emit("error", None, None, "未配置手部型号")
            return
        self.connection_event.emit("connecting", None, None, None)
        command_trace(
            f"connect start hand_type={self.hand_type} hand_joint={self.hand_joint} "
            f"modbus={self.modbus} CAN={self.can}"
        )
        api_instance = None
        try:
            api_instance = self._api_factory(
                hand_joint=self.hand_joint,
                hand_type=self.hand_type,
                modbus=self.modbus,
                can=self.can,
            )
            joint_count = len(HAND_CONFIGS[self.hand_joint].init_pos)
            try:
                api_instance.set_speed([255] * joint_count)
                api_instance.set_torque([255] * joint_count)
            except Exception as exc:
                command_trace(f"initial speed/torque failed: {exc}")
            version = api_instance.get_embedded_version()
            serial = api_instance.get_serial_number()
            if not version or serial in ("-1", "", None):
                raise ConnectionError("未检测到有效的硬件版本或序列号")
            self._api = api_instance
            self._connected = True
            self._offline_mode = False
            self._firmware_version = str(version)
            self._serial = str(serial)
            self.api_ready.emit(True)
            self.connection_event.emit("connected", version, serial, None)
            command_trace(f"connect success version={version!r} serial={serial!r}")
        except Exception as exc:
            command_trace(f"connect failed: {traceback.format_exc().strip()}")
            if api_instance is not None:
                self._dispose_api(api_instance)
            self._api = None
            self._connected = False
            self._offline_mode = True
            self._firmware_version = "Virtual"
            self._serial = "Virtual-Mode"
            self.api_ready.emit(False)
            self.connection_event.emit("offline", "Virtual", "Virtual-Mode", str(exc))

    def _disconnect(self):
        api = self._api
        self._api = None
        was_connected = self._connected
        self._connected = False
        self._offline_mode = False
        self.api_ready.emit(False)
        self._dispose_api(api)
        if was_connected:
            self.connection_event.emit("disconnected", None, None, None)

    @staticmethod
    def _dispose_api(api):
        if api is None:
            return
        hand = getattr(api, "hand", None)
        if hand is not None:
            try:
                hand.running = False
            except Exception:
                pass
            bus = getattr(hand, "bus", None)
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
        try:
            api.close_can()
        except Exception:
            pass

    def _finger_move(self, pose: List[int]):
        if self._offline_mode and self._api is None:
            self._virtual_pose = list(pose)
            self._last_finger_sent = time.monotonic()
            self._last_snapshot = {"state": list(pose), "current": [], "speed": []}
            self.snapshot_ready.emit(dict(self._last_snapshot))
            self.message_event.emit("warning", "当前为离线调试模式，指令未下发到真实机械手")
            return
        if not self._connected or self._api is None:
            self.message_event.emit("warning", "设备未连接，操作被忽略")
            return
        try:
            self._api.finger_move(list(pose))
            self._last_finger_sent = time.monotonic()
            self.message_event.emit("info", f"已发送关节位置: {pose}")
        except Exception as exc:
            command_trace(f"api.finger_move failed: {traceback.format_exc().strip()}")
            self.message_event.emit("error", f"发送关节位置失败：{exc}")

    def _call(self, method: str, value: List[int], error_label: str, silent: bool = False):
        if not self._connected or self._api is None:
            if not silent:
                self.message_event.emit("warning", "设备未连接，操作被忽略")
            return
        try:
            getattr(self._api, method)(list(value))
        except Exception as exc:
            if not silent:
                self.message_event.emit("error", f"{error_label}失败：{exc}")

    def _poll_state(self, now: float) -> bool:
        try:
            value = self._api.get_state()
            if value is None:
                raise ValueError("Returned empty state")
            self._consecutive_failures = 0
            self._last_snapshot["state"] = _as_list(value)
            return True
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 5:
                self._consecutive_failures = 0
                self._disconnect()
                self.connection_event.emit("error", None, None, f"物理设备连接已断开: {exc}")
            return False

    def _poll_current(self) -> bool:
        try:
            self._last_snapshot["current"] = _as_list(self._api.get_current())
            return True
        except Exception:
            return False

    def _poll_speed(self) -> bool:
        try:
            self._last_snapshot["speed"] = _as_list(self._api.get_speed())
            return True
        except Exception:
            return False

    def _poll_matrix(self):
        try:
            data = {
                "thumb_matrix": self._api.get_thumb_matrix_touch(),
                "index_matrix": self._api.get_index_matrix_touch(),
                "middle_matrix": self._api.get_middle_matrix_touch(),
                "ring_matrix": self._api.get_ring_matrix_touch(),
                "little_matrix": self._api.get_little_matrix_touch(),
            }
            self.matrix_ready.emit(data)
        except Exception:
            pass


def _as_list(value):
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value)
