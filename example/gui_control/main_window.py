#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主窗口：顶部栏 + 侧边栏 + 页面栈。"""
import importlib
import threading

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QLabel,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

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
from lhgui.pages.log_page import LogPage
from lhgui.pages.settings_page import SettingsPage
from lhgui.pages.demo_page import DemoPage


class _LazyPagePlaceholder(QWidget):
    """Lightweight page used while an optional page module is warming up."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("LazyPagePlaceholder")
        self._title = QLabel(title)
        self._title.setObjectName("PageTitle")
        self._message = QLabel("正在准备页面…")
        self._message.setObjectName("EmptyStateDescription")
        self._message.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._message)
        layout.addStretch(1)

    def set_status(self, message: str, error: bool = False):
        self._message.setText(message)
        self._message.setProperty("state", "error" if error else "info")
        style = self._message.style()
        style.unpolish(self._message)
        style.polish(self._message)


class MainWindow(QMainWindow):
    lazy_module_ready = pyqtSignal(object, object, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LinkerHand 控制台")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        # 核心层
        self.api_manager = ApiManager()
        self.data_source = DataSource(self.api_manager, state_hz=20)
        self.recorder = Recorder()
        self.action_executor = ActionExecutor()

        self.hand_joint = self.api_manager.hand_joint or "O6"

        # UI
        self.top_bar = TopBar()
        self.sidebar = Sidebar()
        self.stack = QStackedWidget()

        self._pages = {}
        # Vision/Game depend on cv2/mediapipe and are intentionally absent
        # until the user opens them. Once created, the instance is retained so
        # page-local state (recording, presets, diagnostics) remains intact.
        self._lazy_page_factories = {
            Page.VISION: ("lhgui.pages.vision_page", "VisionPage"),
            Page.GAME: ("lhgui.pages.game_page", "GamePage"),
        }
        self._lazy_modules = {}
        self._lazy_errors = {}
        self._lazy_placeholders = {}
        self._lazy_stop = threading.Event()
        self._lazy_preload_thread = None
        self._closing = False
        self._current_normal_page = Page.CONSOLE
        self._previous_normal_page = Page.CONSOLE
        self._active_page = None

        self._build()
        self._wire()
        self.lazy_module_ready.connect(self._on_lazy_module_ready)
        # Do not import optional modules during construction or first paint.
        # This callback runs once the event loop has started, then the import
        # itself happens on a daemon thread that never creates QWidget objects.
        QTimer.singleShot(0, self._start_lazy_preload)

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
        widget = self._ensure_page(page)
        if widget is None:
            return
        if self._active_page is not widget:
            self._deactivate_page(self._active_page)
        self._previous_normal_page = self._current_normal_page
        self._current_normal_page = page
        self.stack.setCurrentWidget(widget)
        self._active_page = widget
        self._activate_page(widget)
        self.sidebar._on_page_changed(page)

    def _ensure_page(self, page):
        """Return a cached page, or a non-blocking placeholder while warming."""
        existing = self._pages.get(page)
        if existing is not None:
            return existing
        factory = self._lazy_page_factories.get(page)
        if factory is None:
            return None
        module = self._lazy_modules.get(page)
        if module is None:
            placeholder = self._lazy_placeholders.get(page)
            if placeholder is None:
                placeholder = _LazyPagePlaceholder(self._page_title(page))
                self._lazy_placeholders[page] = placeholder
                self.stack.addWidget(placeholder)
            error = self._lazy_errors.get(page)
            if error:
                placeholder.set_status(f"页面加载失败：{error}", error=True)
            return placeholder
        return self._construct_lazy_page(page, module, factory[1])

    @staticmethod
    def _page_title(page):
        return {
            Page.VISION: "视觉识别",
            Page.GAME: "小游戏",
        }.get(page, "页面")

    def _construct_lazy_page(self, page, module, class_name):
        """Construct a ready module only on the GUI thread and cache it."""
        existing = self._pages.get(page)
        if existing is not None:
            return existing
        page_class = getattr(module, class_name)
        widget = page_class()
        self._pages[page] = widget
        self.stack.addWidget(widget)
        placeholder = self._lazy_placeholders.pop(page, None)
        if placeholder is not None:
            self.stack.removeWidget(placeholder)
            placeholder.deleteLater()
        # If the app is already dark, sync just this newly-created subtree.
        from PyQt5.QtWidgets import QApplication
        application = QApplication.instance()
        manager = getattr(application, "_linkerhand_theme_manager", None) if application else None
        if manager is not None:
            manager.refresh_widgets(widget)
        return widget

    def _start_lazy_preload(self):
        if self._closing or self._lazy_stop.is_set() or self._lazy_preload_thread is not None:
            return
        self._lazy_preload_thread = threading.Thread(
            target=self._preload_lazy_modules,
            name="linkerhand-page-preload",
            daemon=True,
        )
        self._lazy_preload_thread.start()

    def _preload_lazy_modules(self):
        for page, (module_name, _class_name) in self._lazy_page_factories.items():
            if self._lazy_stop.is_set():
                return
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                self.lazy_module_ready.emit(page, None, exc)
            else:
                self.lazy_module_ready.emit(page, module, None)

    def _on_lazy_module_ready(self, page, module, error):
        if self._closing:
            return
        if error is not None:
            self._lazy_errors[page] = f"{type(error).__name__}: {error}"
            placeholder = self._lazy_placeholders.get(page)
            if placeholder is not None:
                placeholder.set_status(f"页面加载失败：{self._lazy_errors[page]}", error=True)
            return
        self._lazy_modules[page] = module
        # Do not construct a heavyweight QWidget just because prewarming
        # finished. Construct only when the user is still on that page.
        if self._current_normal_page != page:
            return
        placeholder = self._lazy_placeholders.get(page)
        if placeholder is None or self._active_page is not placeholder:
            return
        class_name = self._lazy_page_factories[page][1]
        widget = self._construct_lazy_page(page, module, class_name)
        self.stack.setCurrentWidget(widget)
        self._active_page = widget
        self._activate_page(widget)
        self.sidebar._on_page_changed(page)

    @staticmethod
    def _activate_page(page):
        if page is not None:
            hook = getattr(page, "activate", None)
            if callable(hook):
                hook()

    @staticmethod
    def _deactivate_page(page):
        if page is not None:
            hook = getattr(page, "deactivate", None)
            if callable(hook):
                hook()

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
        self._closing = True
        self._lazy_stop.set()
        preload_thread = self._lazy_preload_thread
        if preload_thread is not None and preload_thread.is_alive():
            # Imports are finite and normally complete immediately; bounded
            # join keeps shutdown deterministic without hanging on a broken
            # optional dependency import.
            preload_thread.join(timeout=2.0)
        try:
            if Page.CONSOLE in self._pages:
                waveform_panel = getattr(self._pages[Page.CONSOLE], "waveform_panel", None)
                if waveform_panel is not None:
                    waveform_panel.exit_fullscreen()
            # 仅清理已经创建的页面；未访问的重页面不会触发依赖导入。
            self._deactivate_page(self._active_page)
            for page in tuple(self._pages.values()):
                # Only page classes that explicitly provide a no-argument
                # compatible closeEvent are called here; QWidget.closeEvent
                # expects a real QCloseEvent.
                hook = page.__class__.__dict__.get("closeEvent")
                if callable(hook) and page is not self._pages.get(Page.CONSOLE):
                    hook(page, None)
            self.recorder.stop_playback()
            self.action_executor.cancel()
            self.data_source.stop()
            self.api_manager.shutdown()
        except Exception as e:
            signal_bus.connection_message.emit("warning", f"关闭清理异常：{e}")
        event.accept()
