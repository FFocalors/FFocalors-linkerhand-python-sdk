#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主题管理器：加载并切换 QSS 样式表。"""
import os
from PyQt5.QtWidgets import QApplication


class ThemeManager:
    THEME = "theme"

    def __init__(self, app: QApplication):
        self.app = app
        self._style_dir = os.path.dirname(os.path.abspath(__file__))
        self._cache = {}
        self._current = None

    def _load(self, name: str) -> str:
        if name not in self._cache:
            path = os.path.join(self._style_dir, f"{name}.qss")
            with open(path, "r", encoding="utf-8") as f:
                self._cache[name] = f.read()
        return self._cache[name]

    def apply(self, name: str = None):
        name = name or self.THEME
        self.app.setStyleSheet(self._load(name))
        self._current = name

    @property
    def current(self) -> str:
        return self._current
