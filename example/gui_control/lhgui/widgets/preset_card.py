#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设动作项（QAbstractButton）。

利用 DPR-aware 提取物理尺寸 QPixmap，在 showEvent 及 DPI 变更时自动刷新，解决高 DPI 模糊。
无任何 Unicode 字符假冒图标，按钮图标与文本独立分开管理。
"""
from PyQt5.QtWidgets import (
    QAbstractButton, QVBoxLayout, QLabel, QStyle, QStyleOption
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer, QEvent
from PyQt5.QtGui import QPainter, QPixmap, QColor

from lhgui.utils.icon_helper import get_pixmap
from lhgui.utils.style_utils import set_dynamic_property

_ICON_MAP = {
    "张开": "hand_open", "握拳": "hand_fist", "OK": "hand_ok", "点赞": "hand_like",
    "壹": "number_one", "贰": "number_two", "叁": "number_three",
    "肆": "number_four", "伍": "number_five",
    "添加预设": "add_preset",
}
_SIZES = {"primary": (130, 96), "normal": (100, 76), "compact": (58, 56)}


class PresetCard(QAbstractButton):
    triggered = pyqtSignal(str, list)

    def __init__(self, name: str, positions: list, variant: str = "normal", preset_id: str = None):
        super().__init__()
        self.name = name
        self.positions = list(positions)
        self.variant = variant
        self.preset_id = preset_id
        self.setObjectName("PresetCard")
        self.setProperty("variant", variant)
        self.setCheckable(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"预设动作 {name}")
        if self.preset_id:
            self.setToolTip(f"{name} (左键执行，右键管理)")
        else:
            self.setToolTip(name)
        
        w, h = _SIZES.get(variant, (100, 76))
        self.setMinimumSize(w, h)
        
        # 如果是自定义预设，触发时发出 preset_id 唯一标识，而不是名字
        trigger_key = self.preset_id if self.preset_id else self.name
        self.clicked.connect(lambda: self.triggered.emit(trigger_key, self.positions))
        
        self._build(name)
        
        # 异常重置定时器
        self._err = QTimer(self)
        self._err.setSingleShot(True)
        self._err.setInterval(900)
        self._err.timeout.connect(lambda: set_dynamic_property(self, "error", "false"))

    def _build(self, name: str):
        lo = QVBoxLayout(self)
        from PyQt5.QtWidgets import QHBoxLayout, QWidget
        # 紧凑模式边距更小
        if self.variant == "compact":
            lo.setContentsMargins(6, 6, 6, 6)
            lo.setSpacing(4)
        else:
            lo.setContentsMargins(8, 10, 8, 10)
            lo.setSpacing(6)

        # 独立的图标圆角容器
        self.icon_container = QWidget()
        self.icon_container.setObjectName("PresetIconContainer")
        icon_layout = QHBoxLayout(self.icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(0)

        self.icn_lbl = QLabel()
        self.icn_lbl.setAlignment(Qt.AlignCenter)
        self.icn_lbl.setStyleSheet("background:transparent; border:none;")
        icon_layout.addWidget(self.icn_lbl)
        lo.addWidget(self.icon_container, stretch=1)

        # 文本容器
        self.nm_lbl = QLabel(name)
        self.nm_lbl.setObjectName("PresetLabel")
        self.nm_lbl.setAlignment(Qt.AlignCenter)
        self.nm_lbl.setStyleSheet("background:transparent; border:none;")
        lo.addWidget(self.nm_lbl)

    def _refresh_icon(self):
        k = _ICON_MAP.get(self.name)
        if not k:
            if self.preset_id:
                k = "custom_preset"
            else:
                return
        
        # 确定逻辑尺寸
        sz = 32 if self.variant == "primary" else (24 if self.variant == "normal" else 18)
        color = "#2563eb" if self.variant == "primary" else "#334155"
        
        # 动态获取 DPR 并获取物理清晰 QPixmap
        px = get_pixmap(k, sz, color, target_widget=self)
        self.icn_lbl.setPixmap(px)

    def contextMenuEvent(self, event):
        """仅自定义预设卡片提供右键删除菜单。"""
        if not self.preset_id:
            super().contextMenuEvent(event)
            return

        from PyQt5.QtWidgets import QMenu, QMessageBox
        from lhgui.utils.ui_state import ui_state, ActionState

        menu = QMenu(self)
        delete_action = menu.addAction("删除预设")

        # 检查是否在运行中，如果在执行中，禁止删除
        running = (ui_state.snapshot.action != ActionState.IDLE)

        action = menu.exec_(event.globalPos())
        if action == delete_action:
            if running:
                QMessageBox.warning(self, "警告", "当前有动作正在执行，请先停止后再删除。")
                return

            reply = QMessageBox.question(
                self, "删除确认", f"确定要删除自定义预设“{self.name}”吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                from lhgui.core.custom_preset_store import custom_preset_store
                from lhgui.utils.signal_bus import signal_bus
                success = custom_preset_store.remove(self.preset_id)
                if success:
                    signal_bus.custom_presets_changed.emit()
                else:
                    QMessageBox.warning(self, "错误", "删除失败：预设不存在或写入异常。")

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_icon()

    def changeEvent(self, event):
        super().changeEvent(event)
        # 监听 DPI 或窗口状态改变
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._refresh_icon()

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # 物理按压 1px 下沉反馈
        if self.isDown():
            p.translate(0, 1)
            
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        
        # 运行中状态呼吸点提示
        if self.property("running") == "true":
            p.setBrush(QColor("#4f82ff"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self.width() - 10, 6, 6, 6)
            
        p.end()

    def sizeHint(self) -> QSize:
        w, h = _SIZES.get(self.variant, (100, 76))
        return QSize(w, h)

    def set_running(self, on: bool):
        set_dynamic_property(self, "running", "true" if on else "false")
        self.setEnabled(not on)

    def set_error(self):
        set_dynamic_property(self, "error", "true")
        self._err.start()
