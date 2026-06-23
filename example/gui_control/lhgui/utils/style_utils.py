#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""样式工具函数。"""
from PyQt5.QtWidgets import QWidget


def set_dynamic_property(widget: QWidget, name: str, value):
    """设置 QSS 动态属性并触发 polish。"""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def repolish(widget: QWidget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def add_card_shadow(widget: QWidget, blur: int = 20, offset: int = 2):
    """为卡片添加极轻阴影。"""
    from PyQt5.QtWidgets import QGraphicsDropShadowEffect
    from PyQt5.QtGui import QColor
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset)
    effect.setColor(QColor(0, 0, 0, 26))
    widget.setGraphicsEffect(effect)
