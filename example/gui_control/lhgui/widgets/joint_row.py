#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单个关节控制行（现代双层：名称+目标值 / 高质量滑动条）。

Row 1: [关节名称]                    [目标值 SpinBox]
Row 2: [━━━━━━━━━━━━●━━━━━━━━━━━]

不再显示冗余反馈值；反馈数据仅用于曲线和姿态监控。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QAbstractSpinBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from lhgui.utils.style_utils import set_dynamic_property


class JointRow(QFrame):
    value_changed = pyqtSignal(int)

    def __init__(self, index: int, name: str, min_val: int = 0, max_val: int = 255,
                 initial: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("JointRow")
        self.index = index
        self.name = name
        self.min_val = min_val
        self.max_val = max_val
        self._syncing = False

        self._active_timer = QTimer(self)
        self._active_timer.setSingleShot(True)
        self._active_timer.setInterval(450)
        self._active_timer.timeout.connect(self._clear_active)

        self._build()
        self.set_value(initial, emit=False)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 4, 14, 4)
        outer.setSpacing(2)

        # ── Row 1: 关节名称 + 目标值 ──
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)

        self.name_lbl = QLabel(self.name)
        self.name_lbl.setObjectName("JointRowName")
        row1.addWidget(self.name_lbl)

        row1.addStretch()

        # 目标值 SpinBox — 仅显示数值，无上下箭头
        self.spin = QSpinBox()
        self.spin.setObjectName("JointRowValue")
        self.spin.setRange(self.min_val, self.max_val)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setToolTip(f"{self.name} 目标值\n范围 {self.min_val}–{self.max_val}")
        self.spin.valueChanged.connect(self._spin_changed)
        row1.addWidget(self.spin)

        outer.addLayout(row1)

        # ── Row 2: 高质量滑动条 ──
        row2 = QHBoxLayout()
        row2.setSpacing(0)
        row2.setContentsMargins(0, 0, 0, 0)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName("JointControlSlider")
        # 为圆形手柄预留稳定的上下绘制空间，避免 Qt 按默认 sizeHint 裁切。
        self.slider.setFixedHeight(24)
        self.slider.setRange(self.min_val, self.max_val)
        self.slider.setToolTip(f"{self.name}\n范围 {self.min_val}–{self.max_val}")
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderPressed.connect(self._set_active)
        row2.addWidget(self.slider, stretch=1)

        outer.addLayout(row2)

        # ── 底部分隔线 ──
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.HLine)
        self._separator.setStyleSheet("background-color: #E8EDF3; max-height: 1px; border: none;")
        # 不添加到 layout 中，而是作为 JointRow 的 border-bottom 处理
        # 但 QFrame HLine 保留在无 QSS border 场景下的兜底
        self._separator.hide()  # 用 QSS border-bottom 代替，更干净

    def _slider_changed(self, value: int):
        if self._syncing:
            return
        self._syncing = True
        self.spin.setValue(value)
        self._syncing = False
        self._set_active()
        self.value_changed.emit(value)

    def _spin_changed(self, value: int):
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(value)
        self._syncing = False
        self._set_active()
        self.value_changed.emit(value)

    def _set_active(self):
        set_dynamic_property(self, "active", "true")
        self._active_timer.start()

    def _clear_active(self):
        set_dynamic_property(self, "active", "false")

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int, emit: bool = False):
        self._syncing = True
        v = max(self.min_val, min(self.max_val, int(value)))
        self.slider.setValue(v)
        self.spin.setValue(v)
        self._syncing = False
        if emit:
            self.value_changed.emit(v)

    def set_feedback(self, value: int):
        """接收底层反馈数据，用于 JointPanel 统一处理（本行内不显示）。"""
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        # 反馈数据仅保留给底层同步，UI 内不再展示重复数值
        _ = max(self.min_val, min(self.max_val, v))

    def set_enabled(self, enabled: bool):
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)
        self.name_lbl.setEnabled(enabled)
