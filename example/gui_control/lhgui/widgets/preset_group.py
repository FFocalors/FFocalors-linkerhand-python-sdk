#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快捷动作库：分级动作快捷触发组件。

分为主要动作、次级动作、数字手势三个层次，排布紧凑合理，提供良好的状态反馈。
"""
from typing import Dict
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea, QFrame
from PyQt5.QtCore import Qt, pyqtSignal

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.widgets.preset_card import PresetCard

_PRIMARY = ["张开", "握拳"]
_NORMAL = ["OK", "点赞"]
_NUMBER = ["壹", "贰", "叁", "肆", "伍"]


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

    def _create_section_card(self, title_text: str) -> tuple:
        from PyQt5.QtWidgets import QFrame
        card = QFrame()
        card.setObjectName("PresetSectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(8)
        
        lbl = QLabel(title_text)
        lbl.setObjectName("PresetSectionTitle")
        card_layout.addWidget(lbl)
        
        return card, card_layout

    def _build(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 标题依然在外面固定，保持一致的设计美感
        title = QLabel("快捷动作")
        title.setObjectName("CardTitle")
        title.setStyleSheet("margin: 12px 12px 4px 12px;")
        root_layout.addWidget(title)

        # 滚动区域包裹所有卡片
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background:transparent; border:none;")
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background:transparent;")
        self.scroll_area.setWidget(self.scroll_content)
        
        self.container_layout = QVBoxLayout(self.scroll_content)
        self.container_layout.setContentsMargins(12, 4, 12, 12)
        self.container_layout.setSpacing(10)

        root_layout.addWidget(self.scroll_area)

        # 渲染静态系统内置卡片组
        self._build_static_groups()

        # 渲染自定义预设分组
        self._build_custom_preset_group()

        # 悬浮阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self)

    def _build_static_groups(self):
        used = set()

        # ── 1. 核心动作 ──
        card, card_layout = self._create_section_card("核心动作")
        
        # 核心主动作：大卡片并排
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for n in ["张开", "握拳"]:
            if n in self.actions:
                c = PresetCard(n, self.actions[n], "primary")
                c.triggered.connect(self.triggered.emit)
                row1.addWidget(c)
                self._cards[n] = c
                used.add(n)
        card_layout.addLayout(row1)

        # 辅助动作：中卡片并排
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for n in ["OK", "点赞"]:
            if n in self.actions:
                c = PresetCard(n, self.actions[n], "normal")
                c.triggered.connect(self.triggered.emit)
                row2.addWidget(c)
                self._cards[n] = c
                used.add(n)
        row2.addStretch()
        card_layout.addLayout(row2)
        
        self.container_layout.addWidget(card)

        # ── 2. 数字手势 ──
        card_num, card_num_layout = self._create_section_card("数字手势")
        grid_num = QGridLayout()
        grid_num.setSpacing(6)
        grid_num.setContentsMargins(0, 0, 0, 0)
        
        num_actions = ["壹", "贰", "叁", "肆", "伍"]
        for idx, n in enumerate(num_actions):
            if n in self.actions:
                c = PresetCard(n, self.actions[n], "compact")
                c.triggered.connect(self.triggered.emit)
                grid_num.addWidget(c, 0, idx)
                self._cards[n] = c
                used.add(n)
        card_num_layout.addLayout(grid_num)
        self.container_layout.addWidget(card_num)

        # ── 3. 其他动作 ──
        rest = {n: p for n, p in self.actions.items() if n not in used}
        if rest:
            card_rest, card_rest_layout = self._create_section_card("其他手势")
            grid_rest = QGridLayout()
            grid_rest.setSpacing(6)
            grid_rest.setContentsMargins(0, 0, 0, 0)
            for i, (n, pos) in enumerate(rest.items()):
                c = PresetCard(n, pos, "compact")
                c.triggered.connect(self.triggered.emit)
                grid_rest.addWidget(c, i // 5, i % 5)
                self._cards[n] = c
            card_rest_layout.addLayout(grid_rest)
            self.container_layout.addWidget(card_rest)

    def _build_custom_preset_group(self):
        # 创建自定义卡片
        self.custom_card, self.custom_card_layout = self._create_section_card("自定义预设")
        self.container_layout.addWidget(self.custom_card)
        self._fill_custom_presets()

    def _fill_custom_presets(self):
        from lhgui.core.custom_preset_store import custom_preset_store
        presets = custom_preset_store.list_for_model(self.hand_joint)
        
        if not presets:
            empty_layout = QHBoxLayout()
            empty_layout.setContentsMargins(4, 4, 4, 4)
            empty_layout.setSpacing(12)
            
            desc_lbl = QLabel("暂无自定义预设动作。\n您可在此添加以保存当前的关节姿态。")
            desc_lbl.setObjectName("PresetEmptyDesc")
            desc_lbl.setStyleSheet("color:#94a3b8; font-size:11px;")
            desc_lbl.setWordWrap(True)
            empty_layout.addWidget(desc_lbl, stretch=1)
            
            self.add_card = PresetCard("添加预设", [], "compact")
            self.add_card.setObjectName("AddPresetCard")
            self.add_card.triggered.connect(self._on_add_preset)
            empty_layout.addWidget(self.add_card)
            self._cards["__add_preset__"] = self.add_card
            
            self.custom_card_layout.addLayout(empty_layout)
        else:
            grid = QGridLayout()
            grid.setSpacing(6)
            grid.setContentsMargins(0, 0, 0, 0)
            
            col_count = 5
            i = 0
            for p in presets:
                c = PresetCard(p.name, list(p.values), "compact", preset_id=p.id)
                c.triggered.connect(self.triggered.emit)
                grid.addWidget(c, i // col_count, i % col_count)
                self._cards[p.id] = c
                i += 1
                
            self.add_card = PresetCard("添加预设", [], "compact")
            self.add_card.setObjectName("AddPresetCard")
            self.add_card.triggered.connect(self._on_add_preset)
            grid.addWidget(self.add_card, i // col_count, i % col_count)
            self._cards["__add_preset__"] = self.add_card
            
            self.custom_card_layout.addLayout(grid)

    def _on_add_preset(self):
        from lhgui.widgets.preset_editor_dialog import PresetEditorDialog
        dialog = PresetEditorDialog(self.hand_joint, parent=self)
        dialog.exec_()

    def refresh_custom_presets(self):
        """局部幂等刷新自定义预设，避免闪烁且保持滚动位置。"""
        # 1. 记录当前滚动高度
        v_bar = self.scroll_area.verticalScrollBar()
        scroll_pos = v_bar.value()
        
        # 2. 从 self._cards 清理已加载的旧自定义卡片
        from lhgui.core.custom_preset_store import custom_preset_store
        presets = custom_preset_store.list_for_model(self.hand_joint)
        ids_to_remove = [p.id for p in presets] + ["__add_preset__"]
        
        for p_id in ids_to_remove:
            if p_id in self._cards:
                card = self._cards.pop(p_id)
                try:
                    card.triggered.disconnect()
                except Exception:
                    pass
                card.deleteLater()

        # 3. 递归清理旧布局里的子控件 (仅清理 index=1 的 Grid，保留 0 位的标题)
        if self.custom_card_layout.count() > 1:
            item = self.custom_card_layout.takeAt(1)
            if item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()
        
        # 4. 重新构建填充数据
        self._fill_custom_presets()
        
        # 5. 延迟恢复滚动位置，确保布局绘制完毕后准确恢复
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(50, lambda: v_bar.setValue(scroll_pos))

    def _clear_layout(self, layout):
        if layout is not None:
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
