#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 SVG 图标管理器。

核心修复：生成多分辨率 QIcon（1x / 1.5x / 2x / 3x），
让 Qt 在不同 DPI 屏幕上自动选择合适分辨率的 Pixmap。
缓存 QIcon 对象，按 (name, logical_size, color) 键。
"""
import os
from typing import Optional, Dict, Tuple

from PyQt5.QtCore import Qt, QByteArray, QRectF
from PyQt5.QtGui import QPixmap, QIcon, QPainter
from PyQt5.QtSvg import QSvgRenderer


_RESOURCES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "icons",
)

_COLOR_TOKENS = ("#000000", "currentColor")
_MULTI_DPR = (1.0, 1.5, 2.0, 3.0)


class IconManager:
    def __init__(self):
        self._svg_text: Dict[str, str] = {}
        self._cache: Dict[Tuple[str, int, str, float], QIcon] = {}
        self._pixmap_cache: Dict[Tuple[str, int, str, float], QPixmap] = {}

    def _load_svg_text(self, name: str) -> Optional[str]:
        if name in self._svg_text:
            return self._svg_text[name]
        path = os.path.join(_RESOURCES_DIR, f"{name}.svg")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self._svg_text[name] = text
            return text
        except Exception:
            return None

    def _colored_svg(self, name: str, color: str) -> Optional[bytes]:
        text = self._load_svg_text(name)
        if text is None:
            return None
        out = text
        for token in _COLOR_TOKENS:
            out = out.replace(token, color)
        return out.encode("utf-8")

    def _render_pixmap(self, name: str, logical: int, color: str, dpr: float) -> QPixmap:
        data = self._colored_svg(name, color)
        pixel = max(1, int(round(logical * dpr)))
        px = QPixmap(pixel, pixel)
        px.fill(Qt.transparent)
        px.setDevicePixelRatio(dpr)
        if data is not None:
            renderer = QSvgRenderer(QByteArray(data))
            painter = QPainter(px)
            painter.setRenderHint(QPainter.Antialiasing, True)
            renderer.render(painter, QRectF(0.0, 0.0, float(logical), float(logical)))
            painter.end()
        return px

    def get_icon(self, name: str, logical_size: int = 24,
                 color: str = "#1f2937", target_widget=None) -> QIcon:
        dpr = 1.0
        if target_widget is not None:
            try:
                dpr = target_widget.devicePixelRatioF()
            except Exception:
                pass
        
        # 缓存键包含 DPR
        dpr_key = round(dpr, 2)
        key = (name, int(logical_size), color, dpr_key)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        icon = QIcon()
        # 将不同 DPI 的 pixmap 添加入 QIcon，以便 Qt 自动选择
        for d in _MULTI_DPR:
            px = self._render_pixmap(name, int(logical_size), color, d)
            icon.addPixmap(px)
        self._cache[key] = icon
        return icon

    def get_pixmap(self, name: str, logical_size: int = 24,
                   color: str = "#1f2937", target_widget=None) -> QPixmap:
        dpr = 1.0
        if target_widget is not None:
            try:
                dpr = target_widget.devicePixelRatioF()
            except Exception:
                pass
        else:
            # 尝试从全局应用获取
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                try:
                    dpr = app.primaryScreen().devicePixelRatio()
                except Exception:
                    pass

        dpr_key = round(dpr, 2)
        key = (name, int(logical_size), color, dpr_key)
        cached = self._pixmap_cache.get(key)
        if cached is not None:
            return cached

        px = self._render_pixmap(name, logical_size, color, dpr)
        self._pixmap_cache[key] = px
        return px

    def clear_cache(self):
        self._cache.clear()
        self._pixmap_cache.clear()



icon_manager = IconManager()
