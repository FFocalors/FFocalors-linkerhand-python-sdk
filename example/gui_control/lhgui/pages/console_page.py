#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台主页面。

主操作区：左关节控制 + 中实时姿态 + 右动作库。
底部：自适应控制条。
实现真正的响应式布局（宽屏、紧凑屏、窄屏三档自适应），完全复用已有控件，无重复连接。
通过固定的父级容器与 Layout remove/add 机制，彻底杜绝 QWidget 弹窗成为独立窗口的问题。
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ActionState, ConnectionState
from lhgui.widgets.joint_panel import JointPanel
from lhgui.widgets.hand_pose_card import HandPoseCard
from lhgui.widgets.preset_group import PresetGroup
from lhgui.widgets.bottom_bar import BottomBar
from lhgui.widgets.waveform_panel import WaveformPanel


class _CycleController(QWidget):
    status_updated = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self._actions = []
        self._index = 0
        self._active = False
        
        # 统一业务调度 Timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._run_next)

    def set_actions(self, actions):
        self._actions = actions
        if self._active:
            self.stop()

    def start(self):
        if not self._actions:
            return
        self._active = True
        ui_state.set_action_state(ActionState.CYCLE_RUNNING)
        self._index = 0
        self._run_next()
        self._timer.start()
        self.status_updated.emit(True, "")

    def stop(self):
        self._active = False
        self._timer.stop()
        if ui_state.snapshot.action in (ActionState.CYCLE_RUNNING, ActionState.ACTION_RUNNING):
            ui_state.set_action_state(ActionState.IDLE)
        self._index = 0
        self.status_updated.emit(False, "")
        signal_bus.connection_message.emit("info", "已停止循环")

    def _run_next(self):
        if not self._active or not self._actions:
            return
        if self._index >= len(self._actions):
            self._index = 0
        name, positions = self._actions[self._index]
        self._index += 1
        self.status_updated.emit(True, name)
        signal_bus.preset_triggered.emit(name, list(positions))


class ConsolePage(QWidget):
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ConsolePage")
        self.hand_joint = hand_joint
        self._current_mode = ""  # wide | compact | narrow
        
        # 1. 优先实例化所有子组件（它们在此处隐式以 self 作为 parent 建立绑定）
        self._build_widgets()
        
        # 2. 初始化固定的根级垂直布局与内部容器，永远不销毁它们以防 QWidget 脱离 parent
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(16, 16, 16, 16)
        self.root_layout.setSpacing(16)

        # 宽屏/紧凑屏所使用的水平并排容器
        self.wide_widget = QWidget(self)
        self.wide_widget.setStyleSheet("background:transparent;")
        self.wide_layout = QHBoxLayout(self.wide_widget)
        self.wide_layout.setContentsMargins(0, 0, 0, 0)
        self.wide_layout.setSpacing(14)
        
        # 将宽屏容器和窄屏滚动区域预置入根布局中，底部控制栏也预置于下方
        self.root_layout.addWidget(self.wide_widget, stretch=1)
        self.root_layout.addWidget(self.scroll_area, stretch=1)
        self.root_layout.addWidget(self.bottom_bar)
        
        # 订阅反馈数据更新至状态缓存
        from lhgui.core.joint_state_cache import joint_state_cache
        signal_bus.joint_state_updated.connect(
            lambda state: joint_state_cache.update(self.hand_joint, state)
        )
        
        # 3. 初始应用一次布局
        self._update_responsive_layout("wide")

    def _build_widgets(self):
        # 左侧组合面板（关节控制 + 实时数据曲线）
        self.left_widget = QWidget(self)
        self.left_widget.setStyleSheet("background:transparent;")
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(14)

        # 左上：关节面板
        self.joint_panel = JointPanel(self.hand_joint)
        self.joint_panel.values_changed.connect(self._on_local_values)

        # 左下：实时曲线面板
        self.waveform_panel = WaveformPanel(self.hand_joint, self)

        self.left_layout.addWidget(self.joint_panel, stretch=1)
        self.left_layout.addWidget(self.waveform_panel, stretch=0)

        # 中：手部姿态（直接作为视觉核心，不加多余顶栏）
        self.pose_card = HandPoseCard(self.hand_joint)

        # 右：预设动作库
        self.preset_group = PresetGroup(self.hand_joint)
        self.preset_group.triggered.connect(signal_bus.preset_triggered.emit)

        # 底部：控制条
        self.bottom_bar = BottomBar(self.hand_joint)
        
        # 业务循环动作调度器 (由 Controller 维护，解耦 BottomBar 的 UI)
        actions = list((HAND_CONFIGS[self.hand_joint].preset_actions or {}).items())
        self._cycle_controller = _CycleController()
        self._cycle_controller.set_actions(actions)
        self.bottom_bar.set_cycle_controller(self._cycle_controller)
        
        # 绑定恢复初始与紧急停止的底层信号
        self.bottom_bar.home_btn.clicked.connect(
            lambda: signal_bus.home_requested.emit(
                "恢复初始位置", list(HAND_CONFIGS[self.hand_joint].init_pos)
            )
        )
        self.bottom_bar.estop_btn.clicked.connect(
            lambda: (
                signal_bus.playback_stopped.emit(),
                signal_bus.connection_message.emit("warning", "紧急停止")
            )
        )

        # 只要快捷动作或恢复初始被触发，我们就同步更新左侧 JointPanel 的滑块目标值
        signal_bus.preset_triggered.connect(lambda name, pos: self._sync_joint_values(pos))
        signal_bus.home_requested.connect(lambda name, pos: self._sync_joint_values(pos))

        # 窄屏模式下所需的滚动支撑
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background:transparent; border:none;")
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background:transparent;")
        self.scroll_area.setWidget(self.scroll_content)
        
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(12, 12, 12, 12)
        self.scroll_layout.setSpacing(12)
        
        self.scroll_area.hide()

    def _update_responsive_layout(self, mode: str):
        if self._current_mode == mode:
            return
        
        # 1. 首先把这三个主控件从它们当前的布局中 remove 出来
        # 警告：这里绝对不要调用 setParent(None)！只用 removeWidget。
        # 这样控件在转移过程中 parent 依旧是 ConsolePage，绝对不会作为顶层独立窗口弹出来！
        if self._current_mode == "narrow":
            self.scroll_layout.removeWidget(self.left_widget)
            self.scroll_layout.removeWidget(self.pose_card)
            self.scroll_layout.removeWidget(self.preset_group)
        else:
            self.wide_layout.removeWidget(self.left_widget)
            self.wide_layout.removeWidget(self.pose_card)
            self.wide_layout.removeWidget(self.preset_group)
            
        # 2. 根据新模式，重新分配到对应的布局中
        if mode == "narrow":
            self.wide_widget.hide()
            self.scroll_area.show()
            
            # 清理 scroll_layout 中的临时 QHBoxLayout，防止多次 resize 时叠加
            while self.scroll_layout.count():
                item = self.scroll_layout.takeAt(0)
                if item.layout():
                    while item.layout().count():
                        item.layout().takeAt(0)
                    item.layout().deleteLater()
            
            # 窄屏上部：左侧面板与手势卡片并排
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(self.left_widget, stretch=1)
            row.addWidget(self.pose_card, stretch=1)
            
            self.scroll_layout.addLayout(row)
            self.scroll_layout.addWidget(self.preset_group)
        else:
            self.scroll_area.hide()
            self.wide_widget.show()
            
            spacing = 14 if mode == "wide" else 8
            self.wide_layout.setContentsMargins(0, 0, 0, 0)
            self.wide_layout.setSpacing(spacing)
            
            # 宽屏/紧凑屏并排填入三栏布局中
            self.wide_layout.addWidget(self.left_widget, stretch=28)
            self.wide_layout.addWidget(self.pose_card, stretch=36)
            self.wide_layout.addWidget(self.preset_group, stretch=36)
            
        self._current_mode = mode

    def _on_local_values(self, values: list):
        self.pose_card.pose_view.update_joint_values(values)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        if width >= 1420:
            self._update_responsive_layout("wide")
        elif width >= 1100:
            self._update_responsive_layout("compact")
        else:
            self._update_responsive_layout("narrow")

    def _sync_joint_values(self, pos: list):
        if pos:
            # emit=False，避免点击时二次发射
            self.joint_panel.set_values(pos[:6], emit=False)
