#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设动作卡片（QAbstractButton，统一卡片体系）。

支持四个视觉变体：
  - core:   2×2 核心动作 (张开/握拳/OK/点赞)
  - number: 数字手势行
  - custom: 自定义预设
  - add:    添加预设（虚线边框）
"""
from PyQt5.QtWidgets import (
    QAbstractButton, QVBoxLayout, QLabel, QStyle, QStyleOption, QWidget, QHBoxLayout, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer, QEvent
from PyQt5.QtGui import QPainter, QColor, QPixmap, QPen

from lhgui.utils.icon_helper import get_pixmap
from lhgui.utils.style_utils import set_dynamic_property

_ICON_MAP = {
    "张开": "hand_open", "握拳": "hand_fist", "OK": "hand_ok", "点赞": "hand_like",
    "添加预设": "add_preset",
}

_NUMBER_GLYPHS = {"壹": "1", "贰": "2", "叁": "3", "肆": "4", "伍": "5"}
_CORE_TONES = {"张开": "blue", "握拳": "slate", "OK": "teal", "点赞": "indigo"}
_CORE_ICON_COLORS = {
    "张开": "#4F73BA", "握拳": "#59697D", "OK": "#4F8876", "点赞": "#746BA3",
}

# (min_w, min_h)
_SIZES = {
    "core":   (140, 92),
    "number": (58, 70),
    "custom": (64, 60),
    "add":    (80, 60),
}


class PresetCard(QAbstractButton):
    triggered = pyqtSignal(str, list)

    def __init__(self, name: str, positions: list, variant: str = "normal",
                 preset_id: str = None):
        super().__init__()
        self.name = name
        self.positions = list(positions)
        self.variant = variant
        self.preset_id = preset_id
        self.setObjectName("PresetCard")
        self.setProperty("variant", variant)
        if variant == "core":
            self.setProperty("tone", _CORE_TONES.get(name, "blue"))
        self.setCheckable(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"预设动作 {name}")

        if self.preset_id:
            self.setToolTip(f"{name} (左键执行，右键管理)")
        else:
            self.setToolTip(name)

        w, h = _SIZES.get(variant, (100, 72))
        self.setMinimumSize(w, h)

        trigger_key = self.preset_id if self.preset_id else self.name
        self.clicked.connect(lambda: self.triggered.emit(trigger_key, self.positions))

        self._build(name)

        self._err = QTimer(self)
        self._err.setSingleShot(True)
        self._err.setInterval(900)
        self._err.timeout.connect(lambda: set_dynamic_property(self, "error", "false"))

    def _build(self, name: str):
        lo = QVBoxLayout(self)

        if self.variant == "core":
            lo.setContentsMargins(12, 14, 12, 12)
            lo.setSpacing(10)
        elif self.variant == "add":
            lo.setContentsMargins(6, 10, 6, 8)
            lo.setSpacing(6)
        else:
            lo.setContentsMargins(6, 8, 6, 6)
            lo.setSpacing(4)

        # ── 图形区域：核心动作用图标面板，数字手势使用数字徽标 ──
        self.icon_container = QWidget()
        self.icon_container.setObjectName(
            "PresetNumberBadge" if self.variant == "number" else "PresetIconContainer"
        )
        ic = QHBoxLayout(self.icon_container)
        ic.setContentsMargins(0, 0, 0, 0)
        ic.setSpacing(0)

        self.icn_lbl = QLabel()
        self.icn_lbl.setObjectName(
            "PresetNumberGlyph" if self.variant == "number" else "PresetIconGlyph"
        )
        self.icn_lbl.setAlignment(Qt.AlignCenter)
        self.icn_lbl.setStyleSheet("background:transparent; border:none;")
        ic.addWidget(self.icn_lbl)

        lo.addWidget(self.icon_container, stretch=1)

        # ── 文本标签 ──
        self.nm_lbl = QLabel(name)
        self.nm_lbl.setObjectName("PresetLabel")
        self.nm_lbl.setAlignment(Qt.AlignCenter)
        self.nm_lbl.setStyleSheet("background:transparent; border:none;")
        # 添加预设用两行显示
        self.nm_lbl.setWordWrap(True)
        lo.addWidget(self.nm_lbl)

    def _refresh_icon(self):
        if self.variant == "number":
            self.icn_lbl.setPixmap(QPixmap())
            self.icn_lbl.setText(_NUMBER_GLYPHS.get(self.name, self.name))
            return

        k = _ICON_MAP.get(self.name)
        if not k:
            if self.preset_id:
                k = "custom_preset"
            else:
                return

        sz = 34 if self.variant == "core" else 20
        color = _CORE_ICON_COLORS.get(self.name, "#64748B") if self.variant == "core" else "#64748B"

        self.icn_lbl.setText("")
        px = get_pixmap(k, sz, color, target_widget=self)
        self.icn_lbl.setPixmap(px)
    def contextMenuEvent(self, event):
        if not self.preset_id:
            super().contextMenuEvent(event)
            return

        from PyQt5.QtWidgets import QMenu, QMessageBox
        from lhgui.utils.ui_state import ui_state, ActionState

        menu = QMenu(self)
        delete_action = menu.addAction("删除预设")

        running = (ui_state.snapshot.action != ActionState.IDLE)

        action = menu.exec_(event.globalPos())
        if action == delete_action:
            if running:
                QMessageBox.warning(self, "警告", "当前有动作正在执行，请先停止后再删除。")
                return

            reply = QMessageBox.question(
                self, "删除确认", f"确定要删除自定义预设\"{self.name}\"吗？",
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
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._refresh_icon()

    def _surface_colors(self):
        """返回随主题变化的自绘卡片表面背景色和边框色。"""
        from lhgui.styles.theme_manager import is_dark_theme
        dark = is_dark_theme()
        if self.property("error") == "true":
            return ("#3A2028", "#FF777C") if dark else ("#FFF1F1", "#E5484D")
        if self.property("running") == "true" or self.isDown():
            return ("#1D3152", "#7EA2FF") if dark else ("#E4ECFA", "#6F8FCE")

        hovered = self.underMouse() and self.isEnabled()
        if self.variant == "number":
            if dark:
                return ("#24334A", "#6484B8") if hovered else ("#1B2635", "#3B4D66")
            return ("#EEF4FC", "#88A2D0") if hovered else ("#F7FAFE", "#C8D5E7")

        if dark:
            core_surfaces = {
                "blue": ("#1C2B45", "#415C86"),
                "slate": ("#222E3E", "#465970"),
                "teal": ("#18352F", "#3D6B5B"),
                "indigo": ("#2A2540", "#5C527F"),
            }
            background, border = core_surfaces.get(self.property("tone"), core_surfaces["blue"])
            return ("#26364A", "#708FBF") if hovered else (background, border)

        core_surfaces = {
            "blue": ("#EDF3FC", "#B7C8E7"),
            "slate": ("#F0F3F7", "#C9D3DF"),
            "teal": ("#ECF6F2", "#BFDACE"),
            "indigo": ("#F1EFF8", "#D0C9E2"),
        }
        background, border = core_surfaces.get(self.property("tone"), core_surfaces["blue"])
        return ("#FFFFFF", "#88A2D0") if hovered else (background, border)
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if self.isDown():
            p.translate(0, 1)

        if self.variant in ("core", "number"):
            background, border = self._surface_colors()
            p.setBrush(QColor(background))
            p.setPen(QPen(QColor(border), 1))
            radius = 12 if self.variant == "core" else 10
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), radius, radius)
        else:
            opt = QStyleOption()
            opt.initFrom(self)
            self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)

        # running 状态呼吸点
        if self.property("running") == "true":
            p.setBrush(QColor("#4F7FF7"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self.width() - 10, 6, 6, 6)

        p.end()
    def sizeHint(self) -> QSize:
        w, h = _SIZES.get(self.variant, (100, 72))
        return QSize(w, h)

    def set_running(self, on: bool):
        set_dynamic_property(self, "running", "true" if on else "false")
        self.setEnabled(not on)

    def set_error(self):
        set_dynamic_property(self, "error", "true")
        self._err.start()
