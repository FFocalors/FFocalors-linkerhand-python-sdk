#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""底部控制条：运行状态展示、循环动作与紧急控制。

支持单行与双行响应式自适应布局。
紧急停止按钮高对比高亮，速度扭矩参数改用微调参数弹窗。
只承担 UI 控制与状态订阅职责，动作循环 Timer 等由外部 Controller 维护。
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QDialog, QSlider, QSpinBox, QAbstractSpinBox, QDialogButtonBox,
    QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.widgets.status_badge import StatusBadge


class _ParamDialog(QDialog):
    def __init__(self, parent, title, minimum, maximum, current):
        super().__init__(parent)
        self.setWindowTitle(f"设置{title}")
        self.setMinimumWidth(320)
        self._value = current
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        
        info = QLabel(f"{title}范围 {minimum}–{maximum}")
        info.setStyleSheet("color:#64748b;")
        layout.addWidget(info)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(current)
        layout.addWidget(self.slider)
        
        row = QHBoxLayout()
        row.addWidget(QLabel("当前值"))
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setFixedWidth(70)
        self.spin.setValue(current)
        row.addWidget(self.spin)
        row.addStretch()
        layout.addLayout(row)
        
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self._value = self.slider.value()
        self.accept()

    def value(self) -> int:
        return self._value


class BottomBar(QWidget):
    def __init__(self, hand_joint: str):
        super().__init__()
        self.setObjectName("BottomBar")
        self.hand_joint = hand_joint
        self.joint_count = len(HAND_CONFIGS[hand_joint].joint_names)
        self._speed = 255
        self._torque = 255
        self._layout_mode = "single"  # single | double
        self._cycle = None
        
        self._build_widgets()
        self._build_layout()
        self._apply_layout()
        
        signal_bus.ui_state_changed.connect(self._on_ui_state)

        # 悬浮阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self)

    def _create_sep(self):
        sep = QFrame()
        sep.setObjectName("__sep__")
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color:#e9eef4; max-width:1px; border:none; margin:4px 6px;")
        return sep

    def _build_widgets(self):
        # 1. 状态展示
        self.action_title_lbl = QLabel("当前动作")
        self.action_title_lbl.setStyleSheet("color:#64748b; font-size:11px; font-weight:500;")
        self.action_lbl = QLabel("空闲")
        self.action_lbl.setObjectName("ActionInfo")
        self.action_lbl.setStyleSheet("color:#1e293b; font-weight:600;")
        
        self.cycle_title_lbl = QLabel("循环状态")
        self.cycle_title_lbl.setStyleSheet("color:#64748b; font-size:11px; font-weight:500;")
        self.cycle_badge = StatusBadge("空闲", level="disconnected")
        
        # 2. 速度与扭矩参数卡片
        self.speed_btn = QPushButton(f"速度\n{self._speed}")
        self.speed_btn.setObjectName("ParamButton")
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.clicked.connect(self._set_speed)
        self.speed_btn.setToolTip("点击调整关节运动速度")
        
        self.torque_btn = QPushButton(f"扭矩\n{self._torque}")
        self.torque_btn.setObjectName("ParamButton")
        self.torque_btn.setCursor(Qt.PointingHandCursor)
        self.torque_btn.clicked.connect(self._set_torque)
        self.torque_btn.setToolTip("点击调整关节最大扭矩")

        # 3. 循环控制
        self.cycle_btn = QPushButton("开始循环")
        self.cycle_btn.setProperty("category", "primary")
        self.cycle_btn.setCursor(Qt.PointingHandCursor)
        self.cycle_btn.clicked.connect(self._toggle_cycle)
        
        self.cycle_stop_btn = QPushButton("停止循环")
        self.cycle_stop_btn.setProperty("category", "danger")
        self.cycle_stop_btn.setCursor(Qt.PointingHandCursor)
        self.cycle_stop_btn.setEnabled(False)
        self.cycle_stop_btn.clicked.connect(self._stop_cycle)

        # 4. 恢复初始 & 紧急停止
        self.home_btn = QPushButton("恢复初始")
        self.home_btn.setProperty("category", "warning")
        self.home_btn.setCursor(Qt.PointingHandCursor)

        self.estop_btn = QPushButton("紧急停止")
        self.estop_btn.setProperty("category", "danger")
        self.estop_btn.setCursor(Qt.PointingHandCursor)

        # 弹性的 Spacers
        self.spacer1 = QWidget()
        self.spacer1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.spacer2 = QWidget()
        self.spacer2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # ---- 将各功能模块分类包装在精致底栏容器中 (BottomGroup) ----
        # 1. 状态组
        self.status_group = QWidget()
        self.status_group.setObjectName("BottomGroup")
        self.status_group.setStyleSheet("background:transparent;")
        status_layout = QHBoxLayout(self.status_group)
        status_layout.setContentsMargins(10, 4, 10, 4)
        status_layout.setSpacing(10)
        status_layout.addWidget(self.action_title_lbl)
        status_layout.addWidget(self.action_lbl)
        status_layout.addWidget(self.cycle_title_lbl)
        status_layout.addWidget(self.cycle_badge)

        # 2. 参数设置组
        self.param_group = QWidget()
        self.param_group.setObjectName("BottomGroup")
        self.param_group.setStyleSheet("background:transparent;")
        param_layout = QHBoxLayout(self.param_group)
        param_layout.setContentsMargins(10, 4, 10, 4)
        param_layout.setSpacing(10)
        param_layout.addWidget(self.speed_btn)
        param_layout.addWidget(self.torque_btn)

        # 3. 循环控制组
        self.cycle_group = QWidget()
        self.cycle_group.setObjectName("BottomGroup")
        self.cycle_group.setStyleSheet("background:transparent;")
        cycle_layout = QHBoxLayout(self.cycle_group)
        cycle_layout.setContentsMargins(10, 4, 10, 4)
        cycle_layout.setSpacing(10)
        cycle_layout.addWidget(self.cycle_btn)
        cycle_layout.addWidget(self.cycle_stop_btn)

        # 4. 应急安全组
        self.safety_group = QWidget()
        self.safety_group.setObjectName("BottomGroup")
        self.safety_group.setStyleSheet("background:transparent;")
        safety_layout = QHBoxLayout(self.safety_group)
        safety_layout.setContentsMargins(10, 4, 10, 4)
        safety_layout.setSpacing(10)
        safety_layout.addWidget(self.home_btn)
        safety_layout.addWidget(self.estop_btn)

    def _build_layout(self):
        # 顶层布局，稍微留一点内边距以实现精美的卡片效果
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(12, 8, 12, 8)
        self.outer.setSpacing(0)

        # 第一行容器
        self.row1_widget = QWidget()
        self.row1_widget.setStyleSheet("background:transparent;")
        self.row1_layout = QHBoxLayout(self.row1_widget)
        self.row1_layout.setContentsMargins(0, 0, 0, 0)
        self.row1_layout.setSpacing(12)
        self.outer.addWidget(self.row1_widget)

        # 第二行容器
        self.row2_widget = QWidget()
        self.row2_widget.setStyleSheet("background:transparent;")
        self.row2_layout = QHBoxLayout(self.row2_widget)
        self.row2_layout.setContentsMargins(0, 0, 0, 0)
        self.row2_layout.setSpacing(12)
        self.outer.addWidget(self.row2_widget)

    def _apply_layout(self):
        # 清空布局
        while self.row1_layout.count():
            item = self.row1_layout.takeAt(0)
            if item.widget() and item.widget().objectName() == "__sep__":
                item.widget().deleteLater()
        while self.row2_layout.count():
            item = self.row2_layout.takeAt(0)
            if item.widget() and item.widget().objectName() == "__sep__":
                item.widget().deleteLater()

        if self._layout_mode == "single":
            self.row2_widget.hide()
            # 单行模式：横向有序摆放四大功能分组
            self.row1_layout.addWidget(self.status_group)
            
            self.row1_layout.addWidget(self._create_sep())
            self.row1_layout.addWidget(self.param_group)
            
            self.row1_layout.addWidget(self._create_sep())
            self.row1_layout.addWidget(self.cycle_group)
            
            self.row1_layout.addWidget(self._create_sep())
            self.row1_layout.addWidget(self.spacer1) # 将应急操作推向最右侧
            self.row1_layout.addWidget(self.safety_group)
        else:
            self.row2_widget.show()
            # 双行模式：
            # 第一行：状态面板 + 参数面板
            self.row1_layout.addWidget(self.status_group)
            self.row1_layout.addWidget(self._create_sep())
            self.row1_layout.addWidget(self.spacer1)
            self.row1_layout.addWidget(self.param_group)

            # 第二行：循环面板 + 风险应急面板
            self.row2_layout.addWidget(self.cycle_group)
            self.row2_layout.addWidget(self._create_sep())
            self.row2_layout.addWidget(self.spacer2)
            self.row2_layout.addWidget(self.safety_group)

    def set_layout_mode(self, mode: str):
        """设定单行(single)或双行(double)排版模式。"""
        if mode not in ("single", "double"):
            return
        if self._layout_mode == mode:
            return
        self._layout_mode = mode
        self._apply_layout()

    def set_cycle_controller(self, controller):
        self._cycle = controller
        controller.status_updated.connect(self._on_cycle_status)

    def _toggle_cycle(self):
        if self._cycle is not None:
            self._cycle.start() if not self._cycle._active else self._cycle.stop()

    def _stop_cycle(self):
        if self._cycle is not None:
            self._cycle.stop()

    def _on_cycle_status(self, active: bool, name: str = ""):
        self.cycle_btn.setEnabled(not active)
        self.cycle_btn.setText("循环中" if active else "开始循环")
        self.cycle_stop_btn.setEnabled(active)
        self.cycle_badge.set_level("running" if active else "disconnected")
        self.cycle_badge.setText("运行中" if active else "空闲")

    def _set_speed(self):
        dlg = _ParamDialog(self.window(), "速度", 0, 255, self._speed)
        if dlg.exec_() == QDialog.Accepted:
            self._speed = dlg.value()
            self.speed_btn.setText(f"速度\n{self._speed}")
            signal_bus.speed_set_requested.emit([self._speed] * self.joint_count)
            signal_bus.connection_message.emit("info", f"速度已设为 {self._speed}")

    def _set_torque(self):
        dlg = _ParamDialog(self.window(), "扭矩", 0, 255, self._torque)
        if dlg.exec_() == QDialog.Accepted:
            self._torque = dlg.value()
            self.torque_btn.setText(f"扭矩\n{self._torque}")
            signal_bus.torque_set_requested.emit([self._torque] * self.joint_count)
            signal_bus.connection_message.emit("info", f"扭矩已设为 {self._torque}")

    def _on_ui_state(self, snapshot):
        enabled = snapshot.connection == ConnectionState.CONNECTED
        self.home_btn.setEnabled(enabled)
        self.speed_btn.setEnabled(enabled)
        self.torque_btn.setEnabled(enabled)
        self.cycle_btn.setEnabled(enabled and not (self._cycle is not None and self._cycle._active))
        
        if snapshot.action == ActionState.ACTION_RUNNING:
            self.action_lbl.setText("执行中")
        elif snapshot.action == ActionState.CYCLE_RUNNING:
            self.action_lbl.setText("循环中")
        else:
            self.action_lbl.setText("空闲")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 根据宽度自动切换单行或双行响应式排版
        if self.width() < 1180:
            self.set_layout_mode("double")
        else:
            self.set_layout_mode("single")
