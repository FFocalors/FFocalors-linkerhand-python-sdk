#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录制 / 回放控制面板。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QDoubleSpinBox, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt

from lhgui.core.recorder import Recorder
from lhgui.utils.signal_bus import signal_bus


class RecorderPanel(QWidget):
    def __init__(self, recorder: Recorder, joint_len: int):
        super().__init__()
        self._recorder = recorder
        self._joint_len = joint_len
        self._build()
        self._refresh_list()
        signal_bus.record_started.connect(self._on_record_started)
        signal_bus.record_stopped.connect(self._on_record_stopped)
        signal_bus.playback_started.connect(self._on_play_started)
        signal_bus.playback_stopped.connect(self._on_play_stopped)
        signal_bus.playback_progress.connect(self._on_progress)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("动作录制 / 回放")
        title.setStyleSheet("font-weight:600;color:#1f2329;")
        layout.addWidget(title)

        # 录制行
        rec_row = QHBoxLayout()
        rec_row.setSpacing(8)
        self.rec_btn = QPushButton("开始录制")
        self.rec_btn.setProperty("category", "danger")
        self.rec_btn.setCheckable(True)
        self.rec_btn.setCursor(Qt.PointingHandCursor)
        self.rec_btn.toggled.connect(self._on_rec_toggle)
        rec_row.addWidget(self.rec_btn)
        rec_row.addStretch()
        layout.addLayout(rec_row)

        # 回放行
        play_row = QHBoxLayout()
        play_row.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(140)
        play_row.addWidget(self.combo)
        self.speed_sp = QDoubleSpinBox()
        self.speed_sp.setRange(0.1, 4.0)
        self.speed_sp.setSingleStep(0.25)
        self.speed_sp.setValue(1.0)
        self.speed_sp.setSuffix("x")
        self.speed_sp.setFixedWidth(80)
        play_row.addWidget(self.speed_sp)
        self.play_btn = QPushButton("回放")
        self.play_btn.setProperty("category", "primary")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self._on_play)
        play_row.addWidget(self.play_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("category", "warning")
        self.stop_btn.clicked.connect(self._on_stop_play)
        play_row.addWidget(self.stop_btn)
        layout.addLayout(play_row)

        # 刷新/进度
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._refresh_list)
        bottom.addWidget(self.refresh_btn)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color:#4e5969;")
        bottom.addWidget(self.progress_label, stretch=1)
        layout.addLayout(bottom)

    def _on_rec_toggle(self, checked: bool):
        if checked:
            self._recorder.start_recording(self._joint_len)
            self.rec_btn.setText("停止录制")
        else:
            name, ok = QInputDialog.getText(self, "保存录制", "动作名称：")
            if ok and name.strip():
                self._recorder.stop_and_save(name.strip())
                self._refresh_list()
            else:
                self._recorder.discard()

    def _on_record_started(self):
        self.rec_btn.setChecked(True)
        self.rec_btn.setText("停止录制")

    def _on_record_stopped(self, _name: str):
        self.rec_btn.setChecked(False)
        self.rec_btn.setText("开始录制")

    def _on_play(self):
        name = self.combo.currentText().strip()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个录制")
            return
        self._recorder.play(name, self.speed_sp.value())

    def _on_stop_play(self):
        self._recorder.stop_playback()

    def _on_play_started(self):
        self.play_btn.setEnabled(False)

    def _on_play_stopped(self):
        self.play_btn.setEnabled(True)
        self.progress_label.setText("")

    def _on_progress(self, cur: int, total: int):
        self.progress_label.setText(f"回放进度：{cur}/{total}")

    def _refresh_list(self):
        self.combo.clear()
        self.combo.addItems(Recorder.list_recordings())
