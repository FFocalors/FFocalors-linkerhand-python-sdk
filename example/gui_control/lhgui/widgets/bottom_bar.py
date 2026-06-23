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

    def _build_widgets(self):
        # 1. 状态展示
        self.action_title_lbl = QLabel("当前动作:")
        self.action_title_lbl.setStyleSheet("color:#64748b; font-weight:500;")
        self.action_lbl = QLabel("空闲")
        self.action_lbl.setObjectName("ActionInfo")
        self.action_lbl.setStyleSheet("color:#0f172a; font-weight:600;")
        
        self.sep1 = QFrame()
        self.sep1.setFrameShape(QFrame.VLine)
        self.sep1.setStyleSheet("color:#e2e8f0; max-width:1px;")
        self.sep1.setFixedSize(1, 20)

        self.cycle_title_lbl = QLabel("循环状态:")
        self.cycle_title_lbl.setStyleSheet("color:#64748b; font-weight:500;")
        self.cycle_badge = StatusBadge("空闲", level="disconnected")
        
        self.sep2 = QFrame()
        self.sep2.setFrameShape(QFrame.VLine)
        self.sep2.setStyleSheet("color:#e2e8f0; max-width:1px;")
        self.sep2.setFixedSize(1, 20)

        # 2. 速度与扭矩参数卡片
        self.speed_title_lbl = QLabel("速度:")
        self.speed_title_lbl.setStyleSheet("color:#64748b;")
        self.speed_btn = QPushButton(str(self._speed))
        self.speed_btn.setProperty("category", "secondary")
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.clicked.connect(self._set_speed)
        self.speed_btn.setToolTip("点击调整关节运动速度")
        
        self.torque_title_lbl = QLabel("扭矩:")
        self.torque_title_lbl.setStyleSheet("color:#64748b;")
        self.torque_btn = QPushButton(str(self._torque))
        self.torque_btn.setProperty("category", "secondary")
        self.torque_btn.setCursor(Qt.PointingHandCursor)
        self.torque_btn.clicked.connect(self._set_torque)
        self.torque_btn.setToolTip("点击调整关节最大扭矩")

        self.sep3 = QFrame()
        self.sep3.setFrameShape(QFrame.VLine)
        self.sep3.setStyleSheet("color:#e2e8f0; max-width:1px;")
        self.sep3.setFixedSize(1, 20)

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
        self.estop_btn.setStyleSheet("font-weight: bold; background-color: #fef2f2; border-color: #fca5a5; color: #b91c1c;")

        # 弹性的 Spacers
        self.spacer1 = QWidget()
        self.spacer1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.spacer2 = QWidget()
        self.spacer2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def _build_layout(self):
        # 顶层布局
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(0)

        # 顶部分割线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color:#e2e8f0; border:none;")
        self.outer.addWidget(sep)

        # 第一行容器
        self.row1_widget = QWidget()
        self.row1_layout = QHBoxLayout(self.row1_widget)
        self.row1_layout.setContentsMargins(16, 8, 16, 8)
        self.row1_layout.setSpacing(12)
        self.outer.addWidget(self.row1_widget)

        # 第二行容器
        self.row2_widget = QWidget()
        self.row2_layout = QHBoxLayout(self.row2_widget)
        self.row2_layout.setContentsMargins(16, 4, 16, 8)
        self.row2_layout.setSpacing(12)
        self.outer.addWidget(self.row2_widget)

    def _apply_layout(self):
        # 清空布局
        while self.row1_layout.count():
            self.row1_layout.takeAt(0)
        while self.row2_layout.count():
            self.row2_layout.takeAt(0)

        if self._layout_mode == "single":
            self.row2_widget.hide()
            # 单行排布全部控件
            self.row1_layout.addWidget(self.action_title_lbl)
            self.row1_layout.addWidget(self.action_lbl)
            self.row1_layout.addWidget(self.sep1)
            self.row1_layout.addWidget(self.cycle_title_lbl)
            self.row1_layout.addWidget(self.cycle_badge)
            self.row1_layout.addWidget(self.sep2)
            self.row1_layout.addWidget(self.speed_title_lbl)
            self.row1_layout.addWidget(self.speed_btn)
            self.row1_layout.addWidget(self.torque_title_lbl)
            self.row1_layout.addWidget(self.torque_btn)
            self.row1_layout.addWidget(self.sep3)
            self.row1_layout.addWidget(self.cycle_btn)
            self.row1_layout.addWidget(self.cycle_stop_btn)
            self.row1_layout.addWidget(self.spacer1)
            self.row1_layout.addWidget(self.home_btn)
            self.row1_layout.addWidget(self.estop_btn)
        else:
            self.row2_widget.show()
            # 第一行：状态值 + 速度扭矩
            self.row1_layout.addWidget(self.action_title_lbl)
            self.row1_layout.addWidget(self.action_lbl)
            self.row1_layout.addWidget(self.sep1)
            self.row1_layout.addWidget(self.cycle_title_lbl)
            self.row1_layout.addWidget(self.cycle_badge)
            self.row1_layout.addWidget(self.spacer1)
            self.row1_layout.addWidget(self.speed_title_lbl)
            self.row1_layout.addWidget(self.speed_btn)
            self.row1_layout.addWidget(self.torque_title_lbl)
            self.row1_layout.addWidget(self.torque_btn)

            # 第二行：循环动作 + 恢复停止
            self.row2_layout.addWidget(self.cycle_btn)
            self.row2_layout.addWidget(self.cycle_stop_btn)
            self.row2_layout.addWidget(self.spacer2)
            self.row2_layout.addWidget(self.home_btn)
            self.row2_layout.addWidget(self.estop_btn)

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
            self.speed_btn.setText(str(self._speed))
            signal_bus.speed_set_requested.emit([self._speed] * self.joint_count)
            signal_bus.connection_message.emit("info", f"速度已设为 {self._speed}")

    def _set_torque(self):
        dlg = _ParamDialog(self.window(), "扭矩", 0, 255, self._torque)
        if dlg.exec_() == QDialog.Accepted:
            self._torque = dlg.value()
            self.torque_btn.setText(str(self._torque))
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
