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

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.pose_view = HandPoseView(self.hand_joint)
        layout.addWidget(self.pose_view, stretch=1)

        # 关节位置精美双行摘要
        self.summary = QLabel("—")
        self.summary.setObjectName("JointValueSummary")
        self.summary.setAlignment(Qt.AlignCenter)
        self.summary.setTextFormat(Qt.RichText)
        layout.addWidget(self.summary)

        if not self.pose_view.is_supported():
            self.summary.setText("<span style='color:#ef4444; font-weight:600;'>当前型号不支持实时姿态图</span>")

    def _on_state(self, state: list):
        if not state or not self.pose_view.is_supported():
            return
        vals = list(state)[:6]
        
        # 实时将反馈位置同步给数字孪生机械手
        self.pose_view.update_joint_values(vals)
        
        # 每行 3 个关节数据，间距控制美观
        row1_parts = []
        row2_parts = []
        
        for i, (name, v) in enumerate(zip(self.joint_names_short, vals)):
            item_html = f"<span style='color:#64748b; font-size:12px;'>{name}</span> <span style='font-family:\"Cascadia Mono\", \"Consolas\", monospace; font-size:13px; font-weight:600; color:#0f172a;'>{int(v):03d}</span>"
            if i < 3:
                row1_parts.append(item_html)
            else:
                row2_parts.append(item_html)
                
        spacing = "&nbsp;" * 6
        html = f"<div style='line-height: 18px;'>{spacing.join(row1_parts)}<br/>{spacing.join(row2_parts)}</div>"
        self.summary.setText(html)

