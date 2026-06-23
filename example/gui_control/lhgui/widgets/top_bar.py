#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶部应用信息栏。

支持自适应高 DPI (不固定高度，最小高度自适应增高，按钮点击高度不低于 36px)。
利用 DPR-aware 获取精细图标，防裁切，中西文字符对齐。
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
)
from PyQt5.QtCore import Qt, QEvent, QSize
from PyQt5.QtGui import QFontMetrics

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ConnectionState
from lhgui.utils.icon_helper import get_icon, get_pixmap
from lhgui.widgets.status_badge import StatusBadge


class TopBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        
        # 使用 setMinimumHeight 而非 setFixedHeight 保证高 DPI 自然伸展
        self.setMinimumHeight(48)
        self._build()
        
        signal_bus.hand_info_ready.connect(self._on_hand_info)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(12)

        # 1. 左侧：图标 + 标题信息
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

        # 2. 右侧：状态标签 + 重新连接 + 演示模式
        self.status_badge = StatusBadge("未连接", level="disconnected")
        self.status_badge.setMinimumHeight(24)
        layout.addWidget(self.status_badge)

        self.reconnect_btn = QPushButton("重新连接")
        self.reconnect_btn.setProperty("category", "primary")
        self.reconnect_btn.setMinimumHeight(36) # 保证按钮最小点击高度不低于 36px
        self.reconnect_btn.setIcon(get_icon("reconnect", size=16, color="#ffffff", target_widget=self))
        self.reconnect_btn.setIconSize(QSize(16, 16))
        self.reconnect_btn.setCursor(Qt.PointingHandCursor)
        self.reconnect_btn.clicked.connect(signal_bus.request_reconnect.emit)
        layout.addWidget(self.reconnect_btn)

        self.demo_btn = QPushButton("演示模式")
        self.demo_btn.setProperty("category", "secondary")
        self.demo_btn.setMinimumHeight(36)
        self.demo_btn.setIcon(get_icon("demo", size=16, color="#475569", target_widget=self))
        self.demo_btn.setIconSize(QSize(16, 16))
        self.demo_btn.setCheckable(True)
        self.demo_btn.setCursor(Qt.PointingHandCursor)
        self.demo_btn.toggled.connect(signal_bus.demo_mode_toggled.emit)
        layout.addWidget(self.demo_btn)

    def _refresh_icon(self):
        # 实时根据 DPI 渲染高分辨率手型图标，防拉伸模糊
        px = get_pixmap("hand_open", 28, "#4f8cff", target_widget=self)
        self.icon_lbl.setPixmap(px)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_icon()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._refresh_icon()

    def _on_hand_info(self, info: dict):
        parts = [
            f"{info.get('hand_type', '').capitalize()}",
            info.get("hand_joint", ""),
        ]
        version = info.get("version")
        ver_str = "".join(str(v) for v in version) if isinstance(version, list) else (version or "")
        if ver_str:
            parts.append(f"固件 {ver_str}")
        self.info_lbl.setText(" · ".join(parts))

    def _on_ui_state(self, snapshot):
        conn = snapshot.connection
        if conn == ConnectionState.CONNECTED:
            self.status_badge.set_level("connected")
            self.status_badge.setText("已连接")
            self.reconnect_btn.setEnabled(True)
        elif conn == ConnectionState.CONNECTING:
            self.status_badge.set_level("connecting")
            self.status_badge.setText("连接中")
            self.reconnect_btn.setEnabled(False)
        elif conn == ConnectionState.ERROR:
            self.status_badge.set_level("error")
            self.status_badge.setText("连接失败")
            self.reconnect_btn.setEnabled(True)
        else:
            self.status_badge.set_level("disconnected")
            self.status_badge.setText("未连接")
            self.reconnect_btn.setEnabled(True)

    def set_demo_checked(self, checked: bool):
        self.demo_btn.blockSignals(True)
        self.demo_btn.setChecked(checked)
        self.demo_btn.blockSignals(False)
