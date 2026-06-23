#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""添加自定义预设动作弹窗。

提供名称校验、关节范围安全边界、使用当前设备状态填入和多关节型号安全补位能力。
"""
import time
import uuid
import logging
import unicodedata
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton
)
from PyQt5.QtCore import Qt, QRegExp
from PyQt5.QtGui import QRegExpValidator

from lhgui.config.constants import HAND_CONFIGS
from lhgui.core.joint_state_cache import joint_state_cache
from lhgui.core.custom_preset_store import custom_preset_store, CustomPreset

logger = logging.getLogger("PresetEditorDialog")

JOINT_LABELS = [
    "1. 大拇指弯曲",
    "2. 大拇指横摆",
    "3. 食指弯曲",
    "4. 中指弯曲",
    "5. 无名指弯曲",
    "6. 小拇指弯曲"
]


class PresetEditorDialog(QDialog):
    def __init__(self, hand_model: str, parent=None):
        super().__init__(parent)
        self.hand_model = hand_model
        self.setWindowTitle("添加自定义预设")
        self.resize(380, 480)
        self.setMinimumSize(340, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # 隐藏的完整快照补位数据（仅对多关节型号有效）
        self.full_snapshot_values = None

        self._build()
        self._init_limits()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 20, 20, 20)
        lo.setSpacing(12)

        # 表单布局
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # 预设名称输入
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(32)  # 最大 32 个半角字符或 16 个全角字符
        self.name_edit.setPlaceholderText("请输入动作名称")
        form.addRow("动作名称:", self.name_edit)

        # 预设分组只读显示
        self.group_label = QLabel("自定义预设")
        self.group_label.setStyleSheet("color:#64748b; font-weight:600;")
        form.addRow("动作分组:", self.group_label)

        # 6 个关节 SpinBox
        self.spinboxes = []
        for label in JOINT_LABELS:
            spin = QSpinBox()
            spin.setRange(0, 255)  # 默认兜底
            spin.setValue(250)
            form.addRow(label + ":", spin)
            self.spinboxes.append(spin)

        lo.addLayout(form)

        # 错误提示内联标签
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color:#ef4444; font-size:12px; font-weight:600;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.error_label)

        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.feed_btn = QPushButton("使用当前姿态")
        self.feed_btn.setCursor(Qt.PointingHandCursor)
        self.feed_btn.clicked.connect(self._on_use_current)
        btn_layout.addWidget(self.feed_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.setProperty("category", "primary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        lo.addLayout(btn_layout)

    def _init_limits(self):
        """从当前型号配置中动态读取关节范围。如果配置中无明确关节范围，兜底使用 0-255 并记录日志。"""
        if self.hand_model not in HAND_CONFIGS:
            return
        config = HAND_CONFIGS[self.hand_model]
        
        # 记录日志，由于 constants.py 没有单独的关节 range 配置，所以使用 0-255 兜底
        logger.info(f"型号 {self.hand_model} 无范围配置，关节范围已统一兜底设置为 0-255。")

        # 将 SpinBox 的值初始化为该手型的 init_pos 中的对应值
        init_positions = list(config.init_pos)
        for i, spin in enumerate(self.spinboxes):
            if i < len(init_positions):
                spin.setValue(int(init_positions[i]))
                
        # 如果是设备未连接，禁用“使用当前姿态”
        from lhgui.utils.ui_state import ui_state, ConnectionState
        if ui_state.snapshot.connection != ConnectionState.CONNECTED:
            self.feed_btn.setEnabled(False)
            self.feed_btn.setToolTip("设备未连接，无法获取姿态")

    def _on_use_current(self):
        """读取缓存并自动填充 6 个关节，如果是多关节型号则在内存中保存完整 values 副本。"""
        self.error_label.setText("")
        
        if not joint_state_cache.is_fresh(self.hand_model, max_age_seconds=3.0):
            self.error_label.setText("当前关节反馈已过期，请等待设备刷新后重试。")
            return

        snapshot = joint_state_cache.latest(self.hand_model)
        if not snapshot:
            self.error_label.setText("未获取到当前关节反馈数据。")
            return

        # 填充前 6 个主要关节值
        vals = snapshot.values
        for i, spin in enumerate(self.spinboxes):
            if i < len(vals):
                spin.setValue(int(round(vals[i])))

        # 暂存完整向量作为隐藏补位数据
        self.full_snapshot_values = vals
        self.error_label.setText("<span style='color:#10b981;'>已成功填充当前姿态！</span>")

    def _on_save(self):
        """保存校验。不含重名、控制字符，首尾空格去除。"""
        self.error_label.setText("")

        # 1. 名字提取和规范化
        name_raw = self.name_edit.text()
        normalized = unicodedata.normalize("NFKC", name_raw).strip()

        # 2. 基础校验
        if not normalized:
            self.error_label.setText("保存失败：预设名称不能为空。")
            return

        # 3. 校验控制字符
        if any(c for c in normalized if unicodedata.category(c)[0] == 'C'):
            self.error_label.setText("保存失败：预设名称包含非法控制字符。")
            return

        # 4. 长度限制
        # 中文字符计为1，英文字符计为1，限制在16个字符内
        if len(normalized) > 16:
            self.error_label.setText("保存失败：动作名称不能超过 16 个字符。")
            return

        # 5. 重名校验
        if custom_preset_store.exists_name(self.hand_model, normalized):
            self.error_label.setText(f"保存失败：名称“{normalized}”已存在，请换一个名称。")
            return

        # 6. 非 L6 型号完整数据安全补齐校验
        config = HAND_CONFIGS.get(self.hand_model)
        if not config:
            self.error_label.setText("保存失败：未知手型配置。")
            return

        total_joints = len(config.init_pos)
        final_values = []

        if total_joints == 6:
            # 6 轴型号，直接取 6 个 SpinBox 的值
            final_values = [spin.value() for spin in self.spinboxes]
        else:
            # 多轴型号，必须获取完整的补位数据
            # 如果没有点击过“使用当前姿态”获取过补位数据，尝试从最新鲜活快照获取
            if self.full_snapshot_values is None:
                if joint_state_cache.is_fresh(self.hand_model, max_age_seconds=3.0):
                    snapshot = joint_state_cache.latest(self.hand_model)
                    if snapshot:
                        self.full_snapshot_values = snapshot.values
            
            # 若依旧无法获取，拒绝保存，必须给用户红字提示，不得静默补齐
            if self.full_snapshot_values is None:
                self.error_label.setText("当前设备未提供完整关节状态，无法安全创建自定义预设。")
                return

            # 用 6 个 SpinBox 覆盖前 6 维，其余关节保持快照中的原样数据
            final_values = list(self.full_snapshot_values)
            for i, spin in enumerate(self.spinboxes):
                if i < len(final_values):
                    final_values[i] = spin.value()

        # 7. 保存到持久化 Store 里面
        p_id = "custom_" + uuid.uuid4().hex[:8]
        ts = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        
        # 逐关节二次校验，保证存入的数据是安全的
        for v in final_values:
            if not (0 <= v <= 255):
                self.error_label.setText("保存失败：关节数值超出安全范围 0-255。")
                return

        preset = CustomPreset(
            id=p_id,
            name=normalized,
            category="custom",
            hand_model=self.hand_model,
            values=tuple(final_values),
            created_at=ts
        )

        try:
            custom_preset_store.add(preset)
            # 成功触发广播信号
            from lhgui.utils.signal_bus import signal_bus
            signal_bus.custom_presets_changed.emit()
            self.accept()
        except Exception as e:
            self.error_label.setText(f"保存失败，写入文件异常：{e}")
