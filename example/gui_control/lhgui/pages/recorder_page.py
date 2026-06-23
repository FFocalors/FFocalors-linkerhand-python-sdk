#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录制与回放页面。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QDoubleSpinBox, QMessageBox, QInputDialog
)
from PyQt5.QtCore import Qt

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, RecorderState, PlaybackState
from lhgui.core.recorder_adapter import RecorderAdapter
from lhgui.core.recorder import Recorder
from lhgui.widgets.status_badge import StatusBadge


class RecorderPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RecorderPage")
        self.recorder: Recorder = None
        self.adapter: RecorderAdapter = None
        self._build()
        signal_bus.ui_state_changed.connect(self._on_ui_state)
        signal_bus.record_started.connect(self._refresh)
        signal_bus.record_stopped.connect(lambda _: self._refresh())
        signal_bus.playback_started.connect(self._refresh)
        signal_bus.playback_stopped.connect(self._refresh)
        signal_bus.playback_progress.connect(self._on_progress)

    def set_recorder(self, recorder: Recorder, joint_count: int = 6):
        self.recorder = recorder
        self.adapter = RecorderAdapter(recorder)
        self._joint_count = joint_count
        self._refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        title = QLabel("录制与回放")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        # 录制控制
        rec_card = QWidget()
        rec_card.setObjectName("Card")
        rec_lay = QHBoxLayout(rec_card)
        rec_lay.setContentsMargins(16, 16, 16, 16)
        rec_lay.setSpacing(12)

        rec_lay.addWidget(QLabel("录制状态"))
        self.status_badge = StatusBadge("空闲", level="disconnected")
        rec_lay.addWidget(self.status_badge)

        self.rec_btn = QPushButton("开始录制")
        self.rec_btn.setProperty("category", "danger")
        self.rec_btn.clicked.connect(self._toggle_record)
        rec_lay.addWidget(self.rec_btn)

        self.discard_btn = QPushButton("放弃")
        self.discard_btn.setProperty("category", "warning")
        self.discard_btn.clicked.connect(self._discard)
        rec_lay.addWidget(self.discard_btn)

        rec_lay.addStretch()
        layout.addWidget(rec_card)

        # 列表 + 回放
        main = QHBoxLayout()
        main.setSpacing(12)

        list_card = QWidget()
        list_card.setObjectName("Card")
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(16, 16, 16, 16)
        list_lay.addWidget(QLabel("已保存记录"))
        self.list_widget = QListWidget()
        list_lay.addWidget(self.list_widget)

        del_btn = QPushButton("删除选中")
        del_btn.setProperty("category", "danger")
        del_btn.clicked.connect(self._delete_selected)
        list_lay.addWidget(del_btn)
        main.addWidget(list_card, stretch=1)

        play_card = QWidget()
        play_card.setObjectName("Card")
        play_lay = QVBoxLayout(play_card)
        play_lay.setContentsMargins(16, 16, 16, 16)
        play_lay.setSpacing(12)

        play_lay.addWidget(QLabel("回放控制"))
        self.play_progress = QLabel("")
        self.play_progress.setStyleSheet("color:#6b7280;")
        play_lay.addWidget(self.play_progress)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("倍速"))
        self.speed_sp = QDoubleSpinBox()
        self.speed_sp.setRange(0.1, 4.0)
        self.speed_sp.setSingleStep(0.25)
        self.speed_sp.setValue(1.0)
        self.speed_sp.setSuffix("x")
        speed_row.addWidget(self.speed_sp)
        play_lay.addLayout(speed_row)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.setProperty("category", "primary")
        self.play_btn.clicked.connect(self._play)
        btn_row.addWidget(self.play_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("category", "warning")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        play_lay.addLayout(btn_row)
        play_lay.addStretch()
        main.addWidget(play_card, stretch=1)

        layout.addLayout(main, stretch=1)

    def _toggle_record(self):
        if not self.recorder:
            return
        if self.recorder.recording:
            name, ok = QInputDialog.getText(self, "保存录制", "动作名称：")
            if ok and name.strip():
                self.recorder.stop_and_save(name.strip())
            else:
                self.recorder.discard()
        else:
            if ui_state.snapshot.connection != ConnectionState.CONNECTED:
                signal_bus.connection_message.emit("warning", "设备未连接，无法录制")
                return
            # 关节数从主窗口配置获取
            self.recorder.start_recording(self._joint_count)

    def _discard(self):
        if self.recorder and self.recorder.recording:
            self.recorder.discard()

    def _play(self):
        if not self.recorder:
            return
        item = self.list_widget.currentItem()
        if not item:
            signal_bus.connection_message.emit("warning", "请先选择一个录制")
            return
        name = item.data(Qt.UserRole)
        self.recorder.play(name, self.speed_sp.value())

    def _stop(self):
        if self.recorder:
            self.recorder.stop_playback()

    def _delete_selected(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", f"确定删除录制 {name} 吗？")
        if reply == QMessageBox.Yes and self.adapter:
            self.adapter.delete(name)
            self._refresh()

    def _on_progress(self, cur: int, total: int):
        self.play_progress.setText(f"回放进度：{cur}/{total}")

    def _on_ui_state(self, snapshot):
        conn = snapshot.connection == ConnectionState.CONNECTED
        rec = snapshot.recorder == RecorderState.RECORDING
        play = snapshot.playback == PlaybackState.PLAYING

        self.status_badge.set_level("running" if rec else "disconnected")
        self.status_badge.setText("录制中" if rec else "空闲")
        self.rec_btn.setText("停止录制" if rec else "开始录制")
        self.rec_btn.setEnabled(conn or rec)
        self.discard_btn.setEnabled(rec)
        self.play_btn.setEnabled(not rec and not play and self.list_widget.count() > 0)
        self.stop_btn.setEnabled(play)

    def _refresh(self):
        if not self.adapter:
            return
        current = self.list_widget.currentItem()
        current_name = current.data(Qt.UserRole) if current else None
        self.list_widget.clear()
        for item in self.adapter.list():
            name = item["name"]
            dur = self.adapter.duration_text(name)
            lw = QListWidgetItem(f"{name}  ({item['frames']} 帧, {dur})")
            lw.setData(Qt.UserRole, name)
            self.list_widget.addItem(lw)
            if name == current_name:
                self.list_widget.setCurrentItem(lw)
        self._on_ui_state(ui_state.snapshot)

    def set_compact_mode(self, compact: bool):
        pass
