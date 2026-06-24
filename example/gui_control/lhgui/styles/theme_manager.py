#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""明暗主题管理、持久化与平滑交叉淡化。"""
import colorsys
import os
import re

from PyQt5.QtCore import (
    QObject, QEvent, QEasingCurve, QPropertyAnimation, QSettings, Qt, pyqtSignal,
)
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
_DECL_RE = re.compile(
    r"(?P<property>selection-background-color|selection-color|background-color|background|"
    r"border-color|border|color)(?P<separator>\s*:\s*)(?P<value>[^;{}]+)",
    re.IGNORECASE,
)


class ThemeManager(QObject):
    LIGHT = "light"
    DARK = "dark"
    THEME = LIGHT  # 兼容旧调用
    TRANSITION_MS = 520

    theme_changed = pyqtSignal(str)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self._style_dir = os.path.dirname(os.path.abspath(__file__))
        self._cache = {}
        self._current = None
        self._animations = []
        self._syncing_inline = False
        self._settings = QSettings("LinkerHand", "Console")
        self.app._linkerhand_theme_manager = self
        self.app.installEventFilter(self)

    @property
    def saved_theme(self) -> str:
        value = str(self._settings.value("appearance/theme", self.LIGHT))
        return value if value in (self.LIGHT, self.DARK) else self.LIGHT

    def _load_light(self) -> str:
        if self.LIGHT not in self._cache:
            path = os.path.join(self._style_dir, "theme.qss")
            with open(path, "r", encoding="utf-8") as file:
                self._cache[self.LIGHT] = file.read()
        return self._cache[self.LIGHT]

    def _load(self, name: str) -> str:
        if name == self.LIGHT:
            return self._load_light()
        if self.DARK not in self._cache:
            self._cache[self.DARK] = self._transform_stylesheet(self._load_light())
        return self._cache[self.DARK]

    @staticmethod
    def _rgb(hex_color: str):
        color = hex_color.lstrip("#")
        return tuple(int(color[index:index + 2], 16) / 255.0 for index in (0, 2, 4))

    @staticmethod
    def _hex(rgb):
        values = [max(0, min(255, round(channel * 255))) for channel in rgb]
        return "#{:02X}{:02X}{:02X}".format(*values)

    @classmethod
    def _dark_color(cls, hex_color: str, role: str) -> str:
        source = hex_color.upper()
        background_map = {
            "#FFFFFF": "#182130", "#F3F6FA": "#101722", "#FAFBFD": "#182230",
            "#F8FAFC": "#1D2837", "#F7F9FC": "#1B2635", "#F6F7F9": "#1D2735",
            "#F5F7FA": "#1F2A3A", "#F4F7FB": "#1C2736", "#F3F5F8": "#202B3A",
            "#F1F5F9": "#243143", "#F0F4FC": "#1C2A42", "#EEF3FD": "#1B2B47",
            "#EAF1FF": "#1C2D4B", "#EAF0FA": "#202F48", "#EDF3FC": "#1D2D47",
            "#EFF7F4": "#18332D", "#ECF8F2": "#17352D", "#E6F6EC": "#17372C",
            "#F3F2F8": "#29253A", "#F1EFF8": "#2A2540", "#E9E6F2": "#302A47",
            "#FFF1F1": "#3A2028", "#FEE2E2": "#45232A", "#FCF6EA": "#342A19",
            "#FFF8E6": "#382D16", "#FFFBEB": "#362C17", "#FEF3C7": "#403315",
            "#151B27": "#0B111B", "#202A3A": "#121A27",
        }
        border_map = {
            "#DCE3EC": "#35465D", "#E8EDF3": "#2D3B4F", "#E2E8F0": "#334258",
            "#D9E2EE": "#3A4B63", "#E1E7EF": "#324157", "#CBD5E1": "#4C5E76",
            "#E0E6EE": "#36465C", "#D9E1EB": "#3A4A60", "#C9D3DF": "#4B5D74",
        }
        text_map = {
            "#172033": "#F2F6FC", "#1E293B": "#E7EEF8", "#202B3C": "#E5EDF7",
            "#243148": "#DDE7F3", "#253247": "#DCE6F2", "#28364B": "#D8E3F0",
            "#2E3B50": "#D6E1ED", "#334155": "#D2DDEA", "#405066": "#C6D2E0",
            "#64748B": "#AEBBCD", "#65748A": "#AAB8CA", "#68778B": "#A7B5C8",
            "#718096": "#9FAEC2", "#7A889D": "#9EACC0", "#8794A7": "#96A5B9",
            "#8995A6": "#94A3B7", "#8A97A8": "#95A4B8", "#94A3B8": "#91A1B6",
            "#FFFFFF": "#FFFFFF", "#4F7FF7": "#7EA2FF", "#3E6FEA": "#6F96FF",
            "#22A06B": "#52C991", "#E5484D": "#FF777C", "#D99000": "#F2B84B",
            "#B91C1C": "#FF8585", "#991B1B": "#FF9A9A", "#92400E": "#F3B66D",
        }
        if role == "background" and source in background_map:
            return background_map[source]
        if role == "border" and source in border_map:
            return border_map[source]
        if role == "text" and source in text_map:
            return text_map[source]

        red, green, blue = cls._rgb(source)
        hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
        neutral = saturation < 0.13

        if role == "background":
            if lightness > 0.72:
                if neutral:
                    level = 0.14 if lightness > 0.94 else 0.18
                    return cls._hex((level * 0.86, level * 0.96, level * 1.12))
                return cls._hex(colorsys.hls_to_rgb(hue, 0.19, min(0.42, max(0.24, saturation))))
            return source

        if role == "border":
            if neutral:
                return "#3B4C63" if lightness > 0.58 else "#52657E"
            target_l = 0.46 if lightness > 0.65 else max(0.48, lightness)
            return cls._hex(colorsys.hls_to_rgb(hue, target_l, min(0.55, max(0.30, saturation))))

        # text
        if neutral:
            if lightness < 0.45:
                return "#E2EAF4"
            if lightness < 0.78:
                return "#AAB8CA"
            return source
        target_l = max(0.66, lightness)
        return cls._hex(colorsys.hls_to_rgb(hue, min(0.78, target_l), min(0.72, max(0.40, saturation))))

    @classmethod
    def _transform_stylesheet(cls, stylesheet: str) -> str:
        def replace_declaration(match):
            prop = match.group("property")
            value = match.group("value")
            lower = prop.lower()
            if "background" in lower:
                role = "background"
            elif "border" in lower:
                role = "border"
            else:
                role = "text"
            value = _HEX_RE.sub(lambda color: cls._dark_color(color.group(0), role), value)
            return f"{prop}{match.group('separator')}{value}"

        return _DECL_RE.sub(replace_declaration, stylesheet)

    def _palette(self, name: str) -> QPalette:
        palette = QPalette()
        if name == self.DARK:
            palette.setColor(QPalette.Window, QColor("#101722"))
            palette.setColor(QPalette.WindowText, QColor("#E7EEF8"))
            palette.setColor(QPalette.Base, QColor("#182130"))
            palette.setColor(QPalette.AlternateBase, QColor("#1D2837"))
            palette.setColor(QPalette.Text, QColor("#E7EEF8"))
            palette.setColor(QPalette.Button, QColor("#1D2837"))
            palette.setColor(QPalette.ButtonText, QColor("#E7EEF8"))
            palette.setColor(QPalette.Highlight, QColor("#638AF2"))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            palette.setColor(QPalette.ToolTipBase, QColor("#202C3C"))
            palette.setColor(QPalette.ToolTipText, QColor("#E7EEF8"))
            palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#718096"))
            palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#718096"))
        else:
            palette = self.app.style().standardPalette()
        return palette

    def _sync_single_inline_style(self, widget: QWidget, name: str):
        current = widget.styleSheet()
        stored = widget.property("_lh_light_stylesheet")
        if name == self.DARK:
            if not current:
                return
            transformed_stored = self._transform_stylesheet(str(stored)) if stored else None
            if stored is None or current != transformed_stored:
                stored = current
                widget.setProperty("_lh_light_stylesheet", stored)
            target = self._transform_stylesheet(str(stored))
            if current != target:
                widget.setStyleSheet(target)
        elif stored is not None:
            widget.setStyleSheet(str(stored))
            widget.setProperty("_lh_light_stylesheet", None)

    def refresh_widgets(self, root: QWidget = None):
        widgets = root.findChildren(QWidget) if root else self.app.allWidgets()
        if root is not None:
            widgets = [root] + widgets
        self._syncing_inline = True
        try:
            for widget in widgets:
                self._sync_single_inline_style(widget, self._current or self.LIGHT)
        finally:
            self._syncing_inline = False

    def eventFilter(self, watched, event):
        if self._current == self.DARK and isinstance(watched, QWidget):
            if event.type() in (QEvent.Show, QEvent.StyleChange) and not self._syncing_inline:
                self._syncing_inline = True
                try:
                    self._sync_single_inline_style(watched, self.DARK)
                finally:
                    self._syncing_inline = False
        return super().eventFilter(watched, event)

    def _apply_now(self, name: str):
        self.app.setProperty("linkerhandTheme", name)
        self.app.setPalette(self._palette(name))
        self.app.setStyleSheet(self._load(name))
        self._current = name
        self.refresh_widgets()
        self.theme_changed.emit(name)
        self.app.processEvents()

    def apply(self, name: str = None, animated: bool = False, source_widget: QWidget = None,
              persist: bool = False):
        name = name or self.saved_theme
        if name not in (self.LIGHT, self.DARK):
            name = self.LIGHT
        if name == self._current:
            return

        window = source_widget.window() if source_widget is not None else self.app.activeWindow()
        overlay = None
        if animated and window is not None and window.isVisible():
            old_frame = window.grab()
            overlay = QLabel(window)
            overlay.setObjectName("ThemeTransitionOverlay")
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.setGeometry(window.rect())
            overlay.setPixmap(old_frame)
            overlay.setScaledContents(True)
            overlay.show()
            overlay.raise_()

        self._apply_now(name)
        if persist:
            self._settings.setValue("appearance/theme", name)

        if overlay is not None:
            effect = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(effect)
            effect.setOpacity(1.0)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(self.TRANSITION_MS)
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)
            animation.setEasingCurve(QEasingCurve.InOutCubic)
            record = (animation, overlay, effect)
            self._animations.append(record)

            def cleanup():
                overlay.deleteLater()
                if record in self._animations:
                    self._animations.remove(record)

            animation.finished.connect(cleanup)
            animation.start()

    def toggle(self, source_widget: QWidget = None):
        target = self.LIGHT if self._current == self.DARK else self.DARK
        self.apply(target, animated=True, source_widget=source_widget, persist=True)

    @property
    def current(self) -> str:
        return self._current or self.LIGHT

    @property
    def is_dark(self) -> bool:
        return self.current == self.DARK


def get_theme_manager() -> ThemeManager:
    app = QApplication.instance()
    return getattr(app, "_linkerhand_theme_manager", None) if app else None


def is_dark_theme() -> bool:
    manager = get_theme_manager()
    return bool(manager and manager.is_dark)


def theme_color(light: str, dark: str) -> str:
    return dark if is_dark_theme() else light
