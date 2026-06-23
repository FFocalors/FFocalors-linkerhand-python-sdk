#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据源：在工作线程中轮询硬件，驱动实时曲线与触觉矩阵。

CAN 读取是同步调用（send_frame + sleep），在主线程跑会卡 UI，
因此放到 QThread 里，按固定节拍拉取 state/current/speed/matrix。
"""
from PyQt5.QtCore import QThread, QTimer
from lhgui.utils.signal_bus import signal_bus


class DataSource(QThread):
    def __init__(self, api_manager, state_hz=20, matrix_hz=2):
        super().__init__()
        self._api = api_manager
        self._state_ms = int(1000 / state_hz)
        self._matrix_ms = int(1000 / matrix_hz)
        self._state_timer: QTimer = None
        self._matrix_timer: QTimer = None

    def run(self):
        # QTimer 必须在所属线程内创建
        self._state_timer = QTimer()
        self._state_timer.moveToThread(self)
        self._state_timer.timeout.connect(self._poll_state)
        self._state_timer.start(self._state_ms)

        self._matrix_timer = QTimer()
        self._matrix_timer.moveToThread(self)
        self._matrix_timer.timeout.connect(self._poll_matrix)
        self._matrix_timer.start(self._matrix_ms)

        self.exec_()

    def _poll_state(self):
        if not self._api.connected:
            return
        state = self._api.get_state()
        current = self._api.get_current()
        speed = self._api.get_speed()
        signal_bus.waveform_updated.emit({
            "state": _as_list(state),
            "current": _as_list(current),
            "speed": _as_list(speed),
        })
        if state is not None:
            signal_bus.joint_state_updated.emit(_as_list(state))

    def _poll_matrix(self):
        if not self._api.connected or not self._api.is_touch:
            return
        data = self._api.get_matrix_touch()
        if data is not None:
            signal_bus.matrix_updated.emit(data)

    def stop(self):
        if self._state_timer:
            self._state_timer.stop()
        if self._matrix_timer:
            self._matrix_timer.stop()
        self.quit()
        self.wait(2000)


def _as_list(v):
    if v is None:
        return []
    if hasattr(v, "tolist"):
        return v.tolist()
    return list(v)
