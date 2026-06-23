#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 状态快照。

采用正交枚举 + 不可变 dataclass，避免单一 set 管理全部状态。
所有修改通过 UIStateManager 进行，组件只读快照。
"""
from dataclasses import dataclass, replace
from enum import Enum, auto

from PyQt5.QtCore import QObject

from lhgui.utils.signal_bus import signal_bus


class Page(Enum):
    CONSOLE = auto()
    WAVEFORM = auto()
    VISION = auto()
    GAME = auto()
    LOG = auto()
    SETTINGS = auto()
    DEMO = auto()


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class ActionState(Enum):
    IDLE = auto()
    ACTION_RUNNING = auto()
    CYCLE_RUNNING = auto()


class RecorderState(Enum):
    # 底层 Recorder 保留但 UI 已移除；状态位保留用于兼容
    IDLE = auto()


class PlaybackState(Enum):
    IDLE = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass(frozen=True)
class UiStateSnapshot:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    action: ActionState = ActionState.IDLE
    recorder: RecorderState = RecorderState.IDLE
    playback: PlaybackState = PlaybackState.IDLE
    demo_mode: bool = False


class UIStateManager(QObject):
    def __init__(self):
        super().__init__()
        self._snapshot = UiStateSnapshot()

    @property
    def snapshot(self) -> UiStateSnapshot:
        return self._snapshot

    def _emit(self):
        signal_bus.ui_state_changed.emit(self._snapshot)

    def set_connection_state(self, state: ConnectionState):
        if not isinstance(state, ConnectionState):
            raise TypeError("state must be ConnectionState")
        if state == self._snapshot.connection:
            return
        self._snapshot = replace(self._snapshot, connection=state)
        self._emit()

    def set_action_state(self, state: ActionState):
        if not isinstance(state, ActionState):
            raise TypeError("state must be ActionState")
        if state == self._snapshot.action:
            return
        self._snapshot = replace(self._snapshot, action=state)
        self._emit()

    def set_recorder_state(self, state: RecorderState):
        if not isinstance(state, RecorderState):
            raise TypeError("state must be RecorderState")
        if state == self._snapshot.recorder:
            return
        self._snapshot = replace(self._snapshot, recorder=state)
        self._emit()

    def set_playback_state(self, state: PlaybackState):
        if not isinstance(state, PlaybackState):
            raise TypeError("state must be PlaybackState")
        if state == self._snapshot.playback:
            return
        self._snapshot = replace(self._snapshot, playback=state)
        self._emit()

    def set_demo_mode(self, on: bool):
        if bool(on) == self._snapshot.demo_mode:
            return
        self._snapshot = replace(self._snapshot, demo_mode=bool(on))
        self._emit()


# 单例
ui_state = UIStateManager()
