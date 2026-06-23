#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触觉矩阵热力图：复用原 DotMatrixWidget 绘制逻辑，接 signal_bus。"""
from typing import Optional
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QBrush

from lhgui.utils.signal_bus import signal_bus


def _flatten(data) -> list:
    if data is None:
        return [0] * 72
    if hasattr(data, "tolist"):
        data = data.tolist()
    out = []
    for item in data:
        if isinstance(item, (list, tuple)):
            out.extend(item)
        else:
            out.append(item)
    return out


class DotMatrixWidget(QWidget):
    def __init__(self, parent=None, rows=12, cols=6):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self.dot_size = 6
        self.spacing = 3
        self.data: Optional[list] = None
        w = cols * (self.dot_size + self.spacing) + self.spacing + 2
        h = rows * (self.dot_size + self.spacing) + self.spacing + 2
        self.setMinimumSize(w, h)
        self.setMaximumSize(w, h)

    def set_data(self, data):
        if data is None:
            self.data = None
        else:
            try:
                self.data = data.tolist() if hasattr(data, "tolist") else data
            except Exception:
                self.data = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        flat = None
        if self.data is not None:
            flat = self.data.flatten() if hasattr(self.data, "flatten") else self.data
        for row in range(self.rows):
            for col in range(self.cols):
                x = self.spacing + col * (self.dot_size + self.spacing)
                y = self.spacing + row * (self.dot_size + self.spacing)
                color = QColor("#c8c8c8")
                if flat is not None:
                    idx = row * self.cols + col
                    if idx < len(flat):
                        v = flat[idx]
                        if hasattr(v, "item"):
                            v = v.item()
                        if v > 0:
                            intensity = min(255, max(0, int(v)))
                            if intensity < 128:
                                color = QColor(255, 255 - intensity * 55 // 128, 255 - intensity * 55 // 128)
                            else:
                                color = QColor(255, 200 - (intensity - 128) * 200 // 127,
                                               200 - (intensity - 128) * 200 // 127)
                p.setBrush(QBrush(color))
                p.setPen(QColor("#666666"))
                p.drawEllipse(x, y, self.dot_size, self.dot_size)


class MatrixPanel(QWidget):
    FINGERS = [
        ("拇指", "thumb_matrix"),
        ("食指", "index_matrix"),
        ("中指", "middle_matrix"),
        ("无名指", "ring_matrix"),
        ("小指", "little_matrix"),
    ]

    def __init__(self):
        super().__init__()
        self.matrices = {}
        self._build()
        signal_bus.matrix_updated.connect(self._on_data)
        self._init_default()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        title = QLabel("触觉矩阵")
        title.setStyleSheet("font-weight:600;color:#1f2329;")
        outer.addWidget(title)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        for display, key in self.FINGERS[:3]:
            row1.addWidget(self._make_finger(display, key))
        row1.addStretch()
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        for display, key in self.FINGERS[3:]:
            row2.addWidget(self._make_finger(display, key))
        row2.addStretch()
        outer.addLayout(row2)
        outer.addStretch()

    def _make_finger(self, display: str, key: str) -> QGroupBox:
        gb = QGroupBox(display)
        lay = QVBoxLayout(gb)
        lay.setContentsMargins(4, 4, 4, 4)
        m = DotMatrixWidget()
        lay.addWidget(m, alignment=Qt.AlignCenter)
        self.matrices[key] = m
        return gb

    def _init_default(self):
        for m in self.matrices.values():
            m.set_data([0] * 72)

    def _on_data(self, data: dict):
        for key, m in self.matrices.items():
            if key in data and data[key] is not None:
                m.set_data(_flatten(data[key]))
