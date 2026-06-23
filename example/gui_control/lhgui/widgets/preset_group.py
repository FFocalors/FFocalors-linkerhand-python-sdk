#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快捷动作库 — 统一卡片化布局。

结构：
  快捷动作（总标题）
  ├─ 核心动作 (2×2 卡片网格: 张开/握拳/OK/点赞)
  ├─ 数字手势 (5列统一行: 壹贰叁肆伍)
  └─ 自定义预设 (统一网格 + 添加预设虚线卡片)
"""
from typing import Dict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.widgets.preset_card import PresetCard


class PresetGroup(QWidget):
    triggered = pyqtSignal(str, list)

    def __init__(self, hand_joint: str):
        super().__init__()
        self.setObjectName("PresetGroup")
        self.hand_joint = hand_joint
        self.actions = HAND_CONFIGS[hand_joint].preset_actions or {}
        self._cards: Dict[str, PresetCard] = {}
        self._build()
        signal_bus.action_started.connect(self._on_started)
        signal_bus.action_finished.connect(self._on_finished)
        signal_bus.action_failed.connect(lambda n, _: self._on_fail(n))
        signal_bus.ui_state_changed.connect(self._on_ui)
        signal_bus.custom_presets_changed.connect(self.refresh_custom_presets)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("PresetSectionTitle")
        lbl.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 600; padding: 0;")
        return lbl

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 总标题 ──
        title = QLabel("快捷动作")
        title.setObjectName("CardTitle")
        title.setStyleSheet("margin: 14px 14px 6px 14px;")
        root.addWidget(title)

        # ── 滚动区域 ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background:transparent; border:none;")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background:transparent;")
        self.scroll_area.setWidget(self.scroll_content)

        self.content = QVBoxLayout(self.scroll_content)
        self.content.setContentsMargins(14, 8, 14, 14)
        self.content.setSpacing(14)

        root.addWidget(self.scroll_area)

        # 构建静态分组
        self._build_core_actions()
        self._build_number_gestures()
        self._build_custom_presets()

        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self, blur=16, offset=1)

    # ────── 1. 核心动作 (2×2 网格) ──────
    def _build_core_actions(self):
        used = set()

        self.content.addWidget(self._section_title("核心动作"))

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        core_names = ["张开", "握拳", "OK", "点赞"]
        for i, n in enumerate(core_names):
            if n in self.actions:
                c = PresetCard(n, self.actions[n], "core")
                c.triggered.connect(self.triggered.emit)
                grid.addWidget(c, i // 2, i % 2)
                self._cards[n] = c
                used.add(n)

        # 不足 4 个时加 stretch
        if len([n for n in core_names if n in self.actions]) < 4:
            grid.setRowStretch(2, 1)
            grid.setColumnStretch(2, 1)

        wrapper = QWidget()
        wrapper.setStyleSheet("background:transparent;")
        wrapper.setLayout(grid)
        self.content.addWidget(wrapper)

        self._used_core = used

    # ────── 2. 数字手势 (单行 5 列) ──────
    def _build_number_gestures(self):
        num_names = ["壹", "贰", "叁", "肆", "伍"]
        available = [n for n in num_names if n in self.actions]
        if not available:
            return

        self.content.addWidget(self._section_title("数字手势"))

        row_layout = QHBoxLayout()
        row_layout.setSpacing(7)
        row_layout.setContentsMargins(0, 0, 0, 0)

        for n in available:
            c = PresetCard(n, self.actions[n], "number")
            c.triggered.connect(self.triggered.emit)
            row_layout.addWidget(c, stretch=1)
            self._cards[n] = c


        wrapper = QFrame()
        wrapper.setObjectName("PresetNumberRow")
        wrapper.setLayout(row_layout)
        self.content.addWidget(wrapper)

    # ────── 3. 自定义预设 ──────
    def _build_custom_presets(self):
        self.content.addWidget(self._section_title("自定义预设"))

        # 占位容器 — 在 _fill_custom_presets 中填充
        self.custom_wrapper = QWidget()
        self.custom_wrapper.setStyleSheet("background:transparent;")
        self.custom_layout = QVBoxLayout(self.custom_wrapper)
        self.custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_layout.setSpacing(8)
        self.content.addWidget(self.custom_wrapper)

        self._fill_custom_presets()

    def _fill_custom_presets(self):
        from lhgui.core.custom_preset_store import custom_preset_store
        presets = custom_preset_store.list_for_model(self.hand_joint)

        # 清理旧的 grid
        while self.custom_layout.count():
            item = self.custom_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

        if not presets:
            # 空状态: 仅显示添加预设卡片
            desc_lbl = QLabel("暂无自定义预设动作。\n点按右侧卡片添加当前姿态。")
            desc_lbl.setStyleSheet("color:#94A3B8; font-size:11px;")
            desc_lbl.setWordWrap(True)

            empty_row = QHBoxLayout()
            empty_row.setSpacing(12)
            empty_row.addWidget(desc_lbl, stretch=1)

            add_card = PresetCard("添加预设", [], "add")
            add_card.triggered.connect(self._on_add_preset)
            empty_row.addWidget(add_card)
            self._cards["__add_preset__"] = add_card

            self.custom_layout.addLayout(empty_row)
        else:
            grid = QGridLayout()
            grid.setSpacing(6)
            grid.setContentsMargins(0, 0, 0, 0)

            cols = 4
            for i, p in enumerate(presets):
                c = PresetCard(p.name, list(p.values), "custom", preset_id=p.id)
                c.triggered.connect(self.triggered.emit)
                grid.addWidget(c, i // cols, i % cols)
                self._cards[p.id] = c

            # 添加预设卡片 (虚线边框)
            add_card = PresetCard("添加预设", [], "add")
            add_card.triggered.connect(self._on_add_preset)
            grid.addWidget(add_card, len(presets) // cols, len(presets) % cols)
            self._cards["__add_preset__"] = add_card

            self.custom_layout.addLayout(grid)

    def _on_add_preset(self):
        from lhgui.widgets.preset_editor_dialog import PresetEditorDialog
        dialog = PresetEditorDialog(self.hand_joint, parent=self)
        dialog.exec_()

    def refresh_custom_presets(self):
        v_bar = self.scroll_area.verticalScrollBar()
        scroll_pos = v_bar.value()

        from lhgui.core.custom_preset_store import custom_preset_store
        presets = custom_preset_store.list_for_model(self.hand_joint)
        ids = [p.id for p in presets] + ["__add_preset__"]

        for pid in ids:
            if pid in self._cards:
                card = self._cards.pop(pid)
                try:
                    card.triggered.disconnect()
                except Exception:
                    pass
                card.deleteLater()

        self._fill_custom_presets()

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(50, lambda: v_bar.setValue(scroll_pos))

    def _clear_layout(self, layout):
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _on_started(self, name: str):
        c = self._cards.get(name)
        if c:
            c.set_running(True)

    def _on_finished(self, name: str):
        c = self._cards.get(name)
        if c:
            c.set_running(False)

    def _on_fail(self, name: str):
        c = self._cards.get(name)
        if c:
            c.set_running(False)
            c.set_error()

    def _on_ui(self, snap):
        ok = snap.connection == ConnectionState.CONNECTED and snap.action == ActionState.IDLE
        for c in self._cards.values():
            c.setEnabled(ok)
