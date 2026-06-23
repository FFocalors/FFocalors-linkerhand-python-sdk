#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手部姿态卡片：HandPoseView + 精美中西文等宽关节反馈摘要。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.widgets.hand_pose_view import HandPoseView

SHORT_NAMES = {
    "大拇指弯曲": "拇弯",
    "大拇指横摆": "拇摆",
    "食指弯曲": "食指",
    "中指弯曲": "中指",
    "无名指弯曲": "无名",
    "小拇指弯曲": "小指"
}


class HandPoseCard(QWidget):
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("HandPoseCard")
        self.hand_joint = hand_joint
        
        # 提取六关节全名
        full_names = list(HAND_CONFIGS[hand_joint].joint_names)[:6]
        # 映射为简写
        self.joint_names_short = [SHORT_NAMES.get(n, n[:2]) for n in full_names]
        self._build()
        signal_bus.joint_state_updated.connect(self._on_state)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 顶部标题栏 Header
        from PyQt5.QtWidgets import QHBoxLayout, QPushButton
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 4)
        header.setSpacing(8)
        
        title_container = QWidget()
        title_container.setStyleSheet("background:transparent;")
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        
        self.title_lbl = QLabel("实时姿态监控")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #1e293b;")
        title_layout.addWidget(self.title_lbl)
        
        device_info = f"当前模型: {self.hand_joint} · 固件 Virtual"
        self.subtitle_lbl = QLabel(device_info)
        self.subtitle_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
        title_layout.addWidget(self.subtitle_lbl)
        header.addWidget(title_container)
        
        header.addStretch()
        
        self.reset_cam_btn = QPushButton("重置视角")
        self.reset_cam_btn.setObjectName("IconActionButton")
        self.reset_cam_btn.setCursor(Qt.PointingHandCursor)
        self.reset_cam_btn.setToolTip("将 3D 相机重置为默认视角")
        self.reset_cam_btn.clicked.connect(self._reset_camera)
        header.addWidget(self.reset_cam_btn)
        
        layout.addLayout(header)

        self.pose_view = HandPoseView(self.hand_joint)
        layout.addWidget(self.pose_view, stretch=1)

        # 仪表盘化：2行3列圆角参数格 ParamBlock
        from PyQt5.QtWidgets import QGridLayout, QFrame
        self.param_grid = QGridLayout()
        self.param_grid.setSpacing(8)
        self.param_grid.setContentsMargins(0, 0, 0, 0)
        
        self.param_boxes = []
        self.param_vals = []
        
        for i, name in enumerate(self.joint_names_short):
            box = QFrame()
            box.setObjectName("ParamBlock")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(8, 6, 8, 6)
            box_layout.setSpacing(4)
            
            title_lbl = QLabel(name)
            title_lbl.setObjectName("ParamTitle")
            title_lbl.setAlignment(Qt.AlignCenter)
            box_layout.addWidget(title_lbl)
            
            val_lbl = QLabel("000")
            val_lbl.setObjectName("ParamValue")
            val_lbl.setAlignment(Qt.AlignCenter)
            box_layout.addWidget(val_lbl)
            
            self.param_vals.append(val_lbl)
            self.param_boxes.append(box)
            self.param_grid.addWidget(box, i // 3, i % 3)
            
        layout.addLayout(self.param_grid)

        # 悬浮阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self)

        if not self.pose_view.is_supported():
            for box in self.param_boxes:
                box.hide()
            err_lbl = QLabel("当前型号不支持实时姿态图")
            err_lbl.setStyleSheet("color:#ef4444; font-weight:600; font-size:12px;")
            err_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(err_lbl)

    def _on_state(self, state: list):
        if not state or not self.pose_view.is_supported():
            return
        vals = list(state)[:6]
        
        # 实时将反馈位置同步给数字孪生机械手
        self.pose_view.update_joint_values(vals)
        
        # 实时更新网格化仪表盘参数
        for i, v in enumerate(vals):
            if i < len(self.param_vals):
                self.param_vals[i].setText(f"{int(v):03d}")

    def _reset_camera(self):
        if hasattr(self.pose_view, "reset_camera"):
            self.pose_view.reset_camera()

    def _on_ui_state(self, snapshot):
        from lhgui.utils.ui_state import ConnectionState
        conn = snapshot.connection
        
        if conn == ConnectionState.CONNECTED:
            device_info = f"当前模型: {self.hand_joint} · 在线"
        elif conn == ConnectionState.OFFLINE:
            device_info = f"当前模型: {self.hand_joint} · 离线调试模式"
        elif conn == ConnectionState.CONNECTING:
            device_info = f"当前模型: {self.hand_joint} · 正在连接..."
        else:
            device_info = f"当前模型: {self.hand_joint} · 设备未连接"
            
        self.subtitle_lbl.setText(device_info)
