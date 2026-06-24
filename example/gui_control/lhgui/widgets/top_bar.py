#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶部应用信息栏：连接、主题与演示模式入口。"""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, QEvent, QSize

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ConnectionState
from lhgui.utils.icon_helper import get_icon, get_pixmap
from lhgui.widgets.status_badge import StatusBadge
from lhgui.styles.theme_manager import get_theme_manager, is_dark_theme


class TopBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(48)
        self._build()

        signal_bus.hand_info_ready.connect(self._on_hand_info)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(10)

        self.icon_lbl = QLabel()
        self.icon_lbl.setStyleSheet("background:transparent; border:none;")
        layout.addWidget(self.icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel("LinkerHand 控制台")
        self.title_lbl.setObjectName("TopBarTitle")
        title_col.addWidget(self.title_lbl)
        self.info_lbl = QLabel("未连接")
        self.info_lbl.setObjectName("TopBarInfo")
        title_col.addWidget(self.info_lbl)
        layout.addLayout(title_col)
        layout.addStretch()

        self.status_badge = StatusBadge("未连接", level="disconnected")
        self.status_badge.setMinimumHeight(24)
        layout.addWidget(self.status_badge)

        self.theme_btn = QPushButton("深色模式")
        self.theme_btn.setProperty("category", "secondary")
        self.theme_btn.setMinimumHeight(36)
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(is_dark_theme())
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("切换明暗主题")
        self.theme_btn.toggled.connect(self._on_theme_toggled)
        layout.addWidget(self.theme_btn)

        self.reconnect_btn = QPushButton("重新连接")
        self.reconnect_btn.setProperty("category", "primary")
        self.reconnect_btn.setMinimumHeight(36)
        self.reconnect_btn.setIcon(get_icon("reconnect", size=16, color="#FFFFFF", target_widget=self))
        self.reconnect_btn.setIconSize(QSize(16, 16))
        self.reconnect_btn.setCursor(Qt.PointingHandCursor)
        self.reconnect_btn.clicked.connect(signal_bus.request_reconnect.emit)
        layout.addWidget(self.reconnect_btn)

        self.demo_btn = QPushButton("演示模式")
        self.demo_btn.setProperty("category", "secondary")
        self.demo_btn.setMinimumHeight(36)
        self.demo_btn.setIconSize(QSize(16, 16))
        self.demo_btn.setCheckable(True)
        self.demo_btn.setCursor(Qt.PointingHandCursor)
        self.demo_btn.toggled.connect(signal_bus.demo_mode_toggled.emit)
        layout.addWidget(self.demo_btn)

        manager = get_theme_manager()
        if manager is not None:
            manager.theme_changed.connect(self._on_theme_changed)
        self._on_theme_changed("dark" if is_dark_theme() else "light")

    def _on_theme_toggled(self, checked: bool):
        manager = get_theme_manager()
        if manager is None or checked == manager.is_dark:
            return
        manager.toggle(self)

    def _on_theme_changed(self, name: str):
        dark = name == "dark"
        self.theme_btn.blockSignals(True)
        self.theme_btn.setChecked(dark)
        self.theme_btn.setText("浅色模式" if dark else "深色模式")
        self.theme_btn.blockSignals(False)
        self._refresh_icon()
        self.demo_btn.setIcon(get_icon(
            "demo", size=16, color="#C5D0DF" if dark else "#475569", target_widget=self
        ))

    def _refresh_icon(self):
        color = "#7EA2FF" if is_dark_theme() else "#4F8CFF"
        self.icon_lbl.setPixmap(get_pixmap("hand_open", 28, color, target_widget=self))

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_icon()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._refresh_icon()

    def _on_hand_info(self, info: dict):
        parts = [f"{info.get('hand_type', '').capitalize()}", info.get("hand_joint", "")]
        version = info.get("version")
        version_text = "".join(str(value) for value in version) if isinstance(version, list) else (version or "")
        if version_text:
            parts.append(f"固件 {version_text}")
        self.info_lbl.setText(" · ".join(parts))

    def _on_ui_state(self, snapshot):
        connection = snapshot.connection
        if connection == ConnectionState.CONNECTED:
            level, text, enabled = "connected", "已连接", True
        elif connection == ConnectionState.OFFLINE:
            level, text, enabled = "warning", "离线调试", True
        elif connection == ConnectionState.CONNECTING:
            level, text, enabled = "connecting", "连接中", False
        elif connection == ConnectionState.ERROR:
            level, text, enabled = "error", "连接失败", True
        else:
            level, text, enabled = "disconnected", "未连接", True
        self.status_badge.set_level(level)
        self.status_badge.setText(text)
        self.reconnect_btn.setEnabled(enabled)

    def set_demo_checked(self, checked: bool):
        self.demo_btn.blockSignals(True)
        self.demo_btn.setChecked(checked)
        self.demo_btn.blockSignals(False)
