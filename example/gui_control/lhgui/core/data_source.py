#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility facade for the device telemetry stream.

Polling now belongs to ``DeviceIoWorker``.  Keeping this tiny QObject facade
preserves ``MainWindow``'s ``start()/stop()`` lifecycle without creating a
second thread or ever calling the synchronous SDK from the GUI thread.
"""

from PyQt5.QtCore import QObject


class DataSource(QObject):
    def __init__(self, api_manager, state_hz=20, matrix_hz=2):
        super().__init__()
        self._api = api_manager
        self.state_hz = state_hz
        self.matrix_hz = matrix_hz
        self._running = False

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._api.start_polling()

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._api.stop_polling()
