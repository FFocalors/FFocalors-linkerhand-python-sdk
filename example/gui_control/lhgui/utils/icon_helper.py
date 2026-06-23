#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标加载辅助（兼容入口）。内部委托 icon_manager。"""
from typing import Optional
from PyQt5.QtGui import QIcon, QPixmap
from lhgui.utils.icon_manager import icon_manager


def get_icon(name: str, size: int = 24, color: Optional[str] = None, target_widget=None) -> QIcon:
    return icon_manager.get_icon(name, size, color or "#1f2937", target_widget)


def get_pixmap(name: str, size: int = 24, color: Optional[str] = None, target_widget=None) -> QPixmap:
    return icon_manager.get_pixmap(name, size, color or "#1f2937", target_widget)

