#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""No-hardware invariants for the serial device runtime."""

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QCoreApplication, QThread

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from lhgui.core.device_io_worker import DeviceIoWorker
from lhgui.core.api_manager import ApiManager
from LinkerHand.utils.load_write_yaml import LoadWriteYaml


class FakeApi:
    def __init__(self, calls):
        self.calls = calls

    def _record(self, name, value=None):
        self.calls.append((name, threading.get_ident(), value))

    def set_speed(self, value):
        self._record("set_speed", list(value))

    def set_torque(self, value):
        self._record("set_torque", list(value))

    def get_embedded_version(self):
        self._record("get_embedded_version")
        return "fake"

    def get_serial_number(self):
        self._record("get_serial_number")
        return "fake-serial"

    def finger_move(self, value):
        self._record("finger_move", list(value))

    def get_state(self):
        self._record("get_state")
        return [250] * 6

    def get_current(self):
        self._record("get_current")
        return [0] * 6

    def get_speed(self):
        self._record("get_speed")
        return [255] * 6

    def close_can(self):
        self._record("close_can")


class TestDeviceIoWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.calls = []
        self.events = []
        self.thread = QThread()
        self.worker = DeviceIoWorker(
            "O6", "right", "None", "PCAN_USBBUS1",
            api_factory=lambda **_: FakeApi(self.calls),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.connection_event.connect(lambda *args: self.events.append(args))
        self.thread.start()
        self.worker.submit_connect()
        self.assertTrue(self._wait_for(lambda: any(e[0] == "connected" for e in self.events)))

    def tearDown(self):
        done = threading.Event()
        self.worker.submit_shutdown(done)
        self.assertTrue(done.wait(2.0))
        self.thread.quit()
        self.assertTrue(self.thread.wait(2000))

    def _wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_sdk_calls_run_in_worker_thread(self):
        self.worker.submit_finger([1] * 6)
        self.assertTrue(self._wait_for(lambda: any(c[0] == "finger_move" for c in self.calls)))
        thread_ids = {c[1] for c in self.calls}
        self.assertEqual(len(thread_ids), 1)
        self.assertNotEqual(next(iter(thread_ids)), threading.get_ident())

    def test_finger_mailbox_is_latest_wins(self):
        for index in range(40):
            self.worker.submit_finger([index] * 6)
        self.assertTrue(self._wait_for(lambda: any(c[0] == "finger_move" for c in self.calls)))
        moves = [c[2] for c in self.calls if c[0] == "finger_move"]
        self.assertEqual(moves[-1], [39] * 6)
        self.assertLessEqual(len(moves), 2)

    def test_offline_finger_updates_rate_limiter(self):
        worker = DeviceIoWorker("O6", "right", "None", "PCAN_USBBUS1")
        worker._offline_mode = True
        worker._finger_move([1] * 6)
        first_sent = worker._last_finger_sent
        self.assertGreater(first_sent, 0.0)
        worker.submit_finger([2] * 6)
        # The second value is retained, but cannot be selected until the
        # 20 Hz deadline expires.
        self.assertIsNone(worker._take_next())
        self.assertEqual(worker._latest_finger, [2] * 6)

    def test_lifecycle_commands_are_not_evicted_by_parameters(self):
        worker = DeviceIoWorker("O6", "right", "None", "PCAN_USBBUS1")
        for index in range(100):
            worker.submit_speed([index] * 6)
            worker.submit_torque([index] * 6)
        worker.submit_disconnect()
        worker.submit_shutdown(threading.Event())
        with worker._lock:
            lifecycle = list(worker._lifecycle)
            parameters = dict(worker._parameters)
        self.assertEqual([item[0] for item in lifecycle], ["shutdown", "disconnect"])
        self.assertLessEqual(len(parameters), worker._parameter_limit)
        self.assertEqual(parameters["speed"], [99] * 6)
        self.assertEqual(parameters["torque"], [99] * 6)

    def test_virtual_pose_uses_configured_joint_count(self):
        setting = {
            "LINKER_HAND": {
                "LEFT_HAND": {"EXISTS": False},
                "RIGHT_HAND": {
                    "EXISTS": True,
                    "JOINT": "L25",
                    "TOUCH": False,
                    "CAN": "PCAN_USBBUS1",
                    "MODBUS": "None",
                },
            }
        }
        with patch.object(LoadWriteYaml, "load_setting_yaml", return_value=setting):
            manager = ApiManager()
        try:
            self.assertEqual(manager.hand_joint, "L25")
            self.assertEqual(len(manager._virtual_pose), 25)
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
