#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主窗口：顶部栏 + 侧边栏 + 页面栈。"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
)
from PyQt5.QtCore import Qt

from lhgui.core.api_manager import ApiManager
from lhgui.core.data_source import DataSource
from lhgui.core.recorder import Recorder
from lhgui.core.action_executor import ActionExecutor
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import (
    Page, ConnectionState, PlaybackState, ui_state
)
from lhgui.config.constants import HAND_CONFIGS

from lhgui.widgets.top_bar import TopBar
from lhgui.widgets.sidebar import Sidebar

from lhgui.pages.console_page import ConsolePage
from lhgui.pages.vision_page import VisionPage
from lhgui.pages.game_page import GamePage
from lhgui.pages.log_page import LogPage
from lhgui.pages.settings_page import SettingsPage
from lhgui.pages.demo_page import DemoPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LinkerHand 控制台")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        # 核心层
        self.api_manager = ApiManager()
        self.data_source = DataSource(self.api_manager)
        self.recorder = Recorder()
        self.action_executor = ActionExecutor()

        self.hand_joint = self.api_manager.hand_joint or "O6"

        # UI
        self.top_bar = TopBar()
        self.sidebar = Sidebar()
        self.stack = QStackedWidget()

        self._pages = {}
        self._current_normal_page = Page.CONSOLE
        self._previous_normal_page = Page.CONSOLE

        self._build()
        self._wire()

        # 启动
        self.api_manager.connect()
        self.data_source.start()

    def _build(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.top_bar)
        right.addWidget(self.stack, stretch=1)
        root.addLayout(right, stretch=1)

        self._pages = {
            Page.CONSOLE: ConsolePage(self.hand_joint),
            Page.VISION: VisionPage(),
            Page.GAME: GamePage(),
            Page.LOG: LogPage(),
            Page.SETTINGS: SettingsPage(),
            Page.DEMO: DemoPage(self.hand_joint),
        }
        for page in self._pages.values():
            self.stack.addWidget(page)

        self.setCentralWidget(central)
        self._switch_page(Page.CONSOLE)

    def _wire(self):
        signal_bus.page_changed.connect(self._on_page_changed)
        signal_bus.demo_mode_toggled.connect(self._on_demo_toggled)
        signal_bus.connection_changed.connect(self._on_connection_changed)

        signal_bus.playback_started.connect(
            lambda: ui_state.set_playback_state(PlaybackState.PLAYING)
        )
        signal_bus.playback_stopped.connect(
            lambda: ui_state.set_playback_state(PlaybackState.IDLE)
        )

    def _on_connection_changed(self, status: str):
        mapping = {
            "connected": ConnectionState.CONNECTED,
            "connecting": ConnectionState.CONNECTING,
            "offline": ConnectionState.OFFLINE,
            "error": ConnectionState.ERROR,
            "disconnected": ConnectionState.DISCONNECTED,
        }
        ui_state.set_connection_state(mapping.get(status, ConnectionState.ERROR))

    def _on_page_changed(self, page: Page):
        if page == Page.DEMO:
            return
        if ui_state.snapshot.demo_mode:
            ui_state.set_demo_mode(False)
            self.top_bar.set_demo_checked(False)
        self._switch_page(page)

    def _switch_page(self, page: Page):
        widget = self._pages.get(page)
        if widget is None:
            return
        self._previous_normal_page = self._current_normal_page
        self._current_normal_page = page
        self.stack.setCurrentWidget(widget)
        self.sidebar._on_page_changed(page)

    def _on_demo_toggled(self, checked: bool):
        if checked:
            if ui_state.snapshot.connection != ConnectionState.CONNECTED:
                signal_bus.connection_message.emit("warning", "演示模式需要设备已连接")
                self.top_bar.set_demo_checked(False)
                return
            ui_state.set_demo_mode(True)
            self._switch_page(Page.DEMO)
        else:
            ui_state.set_demo_mode(False)
            self._switch_page(self._previous_normal_page or Page.CONSOLE)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        self.sidebar.set_compact(width < 1500)
        console = self._pages.get(Page.CONSOLE)
        if console is not None and hasattr(console, "set_layout_mode"):
            console.set_layout_mode(width < 980)

    def closeEvent(self, event):
        try:
            if Page.CONSOLE in self._pages:
                self._pages[Page.CONSOLE].waveform_panel.exit_fullscreen()
            # 停止摄像头工作线程，避免退出时资源泄漏
            for page_key in (Page.VISION, Page.GAME):
                page = self._pages.get(page_key)
                if page is not None:
                    if hasattr(page, "closeEvent"):
                        page.closeEvent(None)
            self.recorder.stop_playback()
            self.action_executor.cancel()
            self.data_source.stop()
            self.api_manager.shutdown()
        except Exception as e:
            signal_bus.connection_message.emit("warning", f"关闭清理异常：{e}")
        event.accept()
