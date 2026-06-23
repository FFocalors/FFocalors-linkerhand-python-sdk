#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单个关节控制行（紧凑两层）。

第一行：名称（左） + 实时反馈值（右，等宽灰字）
第二行：滑块（主宽） + 无按钮 SpinBox（自适应宽度，与滑块有12px间距）
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QAbstractSpinBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFontMetrics

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
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(6)

        # 第一行：关节名称与当前反馈值（左右对齐）
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        
        self.name_lbl = QLabel(self.name)
        self.name_lbl.setObjectName("JointRowName")
        row1.addWidget(self.name_lbl)
        
        row1.addStretch()

        self.feedback_lbl = QLabel("000")
        self.feedback_lbl.setObjectName("JointFeedback")
        self.feedback_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.feedback_lbl.setToolTip(f"{self.name} 实时反馈位置")
        row1.addWidget(self.feedback_lbl)
        
        outer.addLayout(row1)

        # 第二行：滑块与目标值输入框
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.setContentsMargins(0, 0, 0, 0)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(self.min_val, self.max_val)
        self.slider.setToolTip(f"{self.name}\n范围 {self.min_val}–{self.max_val}")
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderPressed.connect(self._set_active)
        row2.addWidget(self.slider, stretch=1)

        self.spin = QSpinBox()
        self.spin.setRange(self.min_val, self.max_val)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setFixedWidth(46)
        self.spin.setToolTip(f"{self.name} 目标值\n范围 {self.min_val}–{self.max_val}")
        self.spin.valueChanged.connect(self._spin_changed)
        row2.addWidget(self.spin)
        
        outer.addLayout(row2)

        # 底部分隔线
        self._separator = QFrame()
        self._separator.setObjectName("JointRowSep")
        self._separator.setFrameShape(QFrame.HLine)
        outer.addWidget(self._separator)

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
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(self.min_val, min(self.max_val, v))
        self.feedback_lbl.setText(f"{v}")

    def set_enabled(self, enabled: bool):
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)
        self.name_lbl.setEnabled(enabled)
        self.feedback_lbl.setEnabled(enabled)
