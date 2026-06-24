#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应抓取控制面板卡片。

职责：
1. 包含控制 Profile 的下拉框，展示核心参数。
2. 呈现全局抓取状态徽章（IDLE, CLOSING_COARSE, SUCCESS 等）。
3. 列出各可用关节的单独状态及接触得分进度条。
4. 提供“开始抓取”、“停止抓取”、“安全释放”、“空载标定”和“参数设置”交互按钮。
5. 监听 SignalBus 上的自适应抓取专有信号，实现 UI 的实时更新与互斥控制。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QProgressBar, QFrame, QDialog, QFormLayout, QSpinBox, QMessageBox,
    QAbstractSpinBox
)
from PyQt5.QtCore import Qt, QTimer

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState
from lhgui.utils.icon_helper import get_icon
from lhgui.core.grasp_state import GraspState, GraspJointState
from lhgui.core.grasp_profile import GraspProfile, grasp_profile_manager
from lhgui.core.grasp_calibration import grasp_calibration_manager
from lhgui.core.adaptive_grasp_controller import AdaptiveGraspController


# 状态友好名称映射
STATE_NAMES = {
    GraspState.IDLE: ("空闲", "#F1F5F9", "#475569"),
    GraspState.PREPARING: ("就绪中", "#EFF6FF", "#1D4ED8"),
    GraspState.PREGRASP: ("定位预抓取", "#EFF6FF", "#1D4ED8"),
    GraspState.CLOSING_COARSE: ("快速闭合", "#EFF6FF", "#1D4ED8"),
    GraspState.CLOSING_FINE: ("精细逼近", "#DBEAFE", "#1E40AF"),
    GraspState.FORMING_CONTACT: ("接触判定", "#F5F3FF", "#6D28D9"),
    GraspState.PRELOADING: ("位置预紧", "#FEF3C7", "#B45309"),
    GraspState.HOLDING: ("保持抓取", "#ECFDF5", "#047857"),
    GraspState.VERIFYING: ("稳定性检验", "#D1FAE5", "#065F46"),
    GraspState.SUCCESS: ("抓取成功", "#D1FAE5", "#065F46"),
    GraspState.RELEASING: ("安全释放", "#FEF3C7", "#B45309"),
    GraspState.FAILED: ("空抓失败", "#FEE2E2", "#B91C1C"),
    GraspState.ABORTED: ("动作中止", "#FEE2E2", "#B91C1C"),
}

JOINT_STATE_NAMES = {
    GraspJointState.IDLE: ("准备中", "#F8FAFC", "#64748B"),
    GraspJointState.CLOSING_COARSE: ("快速闭合", "#EFF6FF", "#1D4ED8"),
    GraspJointState.CLOSING_FINE: ("精细逼近", "#DBEAFE", "#1E40AF"),
    GraspJointState.CONTACT_CANDIDATE: ("疑似接触", "#FEF9C3", "#A16207"),
    GraspJointState.CONTACT_CONFIRMED: ("最佳位置", "#ECFDF5", "#047857"),
    GraspJointState.FROZEN: ("固定/冻结", "#F1F5F9", "#475569"),
    GraspJointState.LIMIT_REACHED: ("安全限位", "#FFEDD5", "#C2410C"),
    GraspJointState.ERROR: ("关节错误", "#FEF2F2", "#B91C1C"),
}


class _ParamEditDialog(QDialog):
    """自适应参数快速配置对话框。"""
    def __init__(self, profile: GraspProfile, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"参数配置 - {profile.name}")
        self.setMinimumWidth(320)
        self.profile = profile

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.coarse_spin = QSpinBox()
        self.coarse_spin.setRange(1, 20)
        self.coarse_spin.setValue(profile.coarse_step)
        form.addRow("快速逼进步长:", self.coarse_spin)

        self.fine_spin = QSpinBox()
        self.fine_spin.setRange(1, 10)
        self.fine_spin.setValue(profile.fine_step)
        form.addRow("精细逼进步长:", self.fine_spin)

        self.preload_spin = QSpinBox()
        self.preload_spin.setRange(1, 10)
        self.preload_spin.setValue(profile.preload_step)
        form.addRow("预紧微调步长:", self.preload_spin)

        self.preload_max_spin = QSpinBox()
        self.preload_max_spin.setRange(1, 5)
        self.preload_max_spin.setValue(profile.maximum_preload_steps)
        form.addRow("最大预紧步数:", self.preload_max_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1000, 15000)
        self.timeout_spin.setSingleStep(500)
        self.timeout_spin.setValue(profile.timeout_ms)
        form.addRow("整体抓取超时 (ms):", self.timeout_spin)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok_btn = QPushButton("保存")
        ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _save(self):
        self.profile.coarse_step = self.coarse_spin.value()
        self.profile.fine_step = self.fine_spin.value()
        self.profile.preload_step = self.preload_spin.value()
        self.profile.maximum_preload_steps = self.preload_max_spin.value()
        self.profile.timeout_ms = self.timeout_spin.value()
        
        # 写入持久化
        grasp_profile_manager.save_profile(self.profile)
        self.accept()


class FingerRow(QWidget):
    """展现单一手指自适应监测行。"""
    def __init__(self, joint_index: int, name: str, parent=None):
        super().__init__(parent)
        self.joint_index = joint_index
        self.name = name
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # 1. 关节名
        self.name_lbl = QLabel(self.name)
        self.name_lbl.setObjectName("JointRowName")
        self.name_lbl.setFixedWidth(70)
        layout.addWidget(self.name_lbl)

        # 2. 评分条
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(12)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: #E2E8F0;
                border-radius: 6px;
                border: none;
            }
            QProgressBar::chunk {
                background: #EAB308;
                border-radius: 6px;
            }
        """)
        self.progress.setToolTip("当前滑动分析器算出的接触评分 (0% - 100%)")
        layout.addWidget(self.progress, stretch=1)

        # 3. 关节状态标签
        self.state_lbl = QLabel("准备中")
        self.state_lbl.setObjectName("GraspJointStateBadge")
        self.state_lbl.setAlignment(Qt.AlignCenter)
        self.state_lbl.setFixedWidth(64)
        self.state_lbl.setStyleSheet("""
            background: #F1F5F9;
            color: #64748B;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 500;
            padding: 1px 4px;
        """)
        layout.addWidget(self.state_lbl)

    def update_score(self, score: float):
        percent = int(max(0.0, min(1.0, score)) * 100)
        self.progress.setValue(percent)

    def update_state(self, state: GraspJointState):
        name, bg_color, fg_color = JOINT_STATE_NAMES.get(state, ("未知", "#F1F5F9", "#64748B"))
        self.state_lbl.setText(name)
        self.state_lbl.setStyleSheet(f"""
            background: {bg_color};
            color: {fg_color};
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 4px;
        """)
        if state == GraspJointState.CONTACT_CONFIRMED:
            self.progress.setValue(100)
            self.progress.setStyleSheet("""
                QProgressBar { background: #E2E8F0; border-radius: 6px; border: none; }
                QProgressBar::chunk { background: #10B981; border-radius: 6px; }
            """)
        elif state == GraspJointState.LIMIT_REACHED:
            self.progress.setStyleSheet("""
                QProgressBar { background: #E2E8F0; border-radius: 6px; border: none; }
                QProgressBar::chunk { background: #F97316; border-radius: 6px; }
            """)
        elif state == GraspJointState.ERROR:
            self.progress.setStyleSheet("""
                QProgressBar { background: #E2E8F0; border-radius: 6px; border: none; }
                QProgressBar::chunk { background: #EF4444; border-radius: 6px; }
            """)
        elif state == GraspJointState.FROZEN:
            self.progress.setValue(0)
            self.progress.setStyleSheet("""
                QProgressBar { background: #F1F5F9; border-radius: 6px; border: none; }
                QProgressBar::chunk { background: #94A3B8; border-radius: 6px; }
            """)
        else:
            self.progress.setStyleSheet("""
                QProgressBar { background: #E2E8F0; border-radius: 6px; border: none; }
                QProgressBar::chunk { background: #3B82F6; border-radius: 6px; }
            """)


class AdaptiveGraspCard(QWidget):
    """自适应抓取控制 Fluent 卡片组件。"""
    def __init__(self, hand_joint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("AdaptiveGraspCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hand_joint = hand_joint
        self.finger_rows: Dict[int, FingerRow] = {}

        self._build()
        self._wire_signals()
        self._refresh_profiles()

        # 极轻卡片阴影
        from lhgui.utils.style_utils import add_card_shadow
        add_card_shadow(self, blur=16, offset=1)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        # ── Header: 标题 + 全局状态 Badge ──
        header = QHBoxLayout()
        title = QLabel("自适应抓取控制")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch()

        self.status_badge = QLabel("空闲")
        self.status_badge.setObjectName("GraspStatusBadge")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setStyleSheet("""
            background: #F1F5F9;
            color: #64748B;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 10px;
        """)
        header.addWidget(self.status_badge)
        layout.addLayout(header)

        # ── Profile 下拉选择框 ──
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("抓取配置:"))
        self.combo = QComboBox()
        self.combo.setObjectName("GraspProfileCombo")
        self.combo.setMinimumWidth(160)
        self.combo.currentIndexChanged.connect(self._on_profile_changed)
        profile_row.addWidget(self.combo, stretch=1)

        # 参数编辑小图标
        self.settings_btn = QPushButton()
        self.settings_btn.setProperty("category", "tool")
        self.settings_btn.setFlat(True)
        self.settings_btn.setIcon(get_icon("settings", size=16))
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setToolTip("编辑当前配置参数")
        self.settings_btn.clicked.connect(self._edit_parameters)
        profile_row.addWidget(self.settings_btn)
        layout.addLayout(profile_row)

        # ── 各手指监测列表 ──
        self.list_container = QFrame()
        self.list_container.setObjectName("GraspListContainer")
        self.list_container.setStyleSheet("background: transparent; border: none;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 4, 0, 4)
        self.list_layout.setSpacing(6)
        layout.addWidget(self.list_container)

        self._rebuild_finger_rows()

        # ── 下部按钮群组（三行排布，整洁现代） ──
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        # 第一行：开始抓取 与 停止抓取 并排
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.start_btn = QPushButton("开始自适应抓取")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._start_grasp)
        self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F7FF7;
                border: 1px solid #3E6FEA;
                border-radius: 8px;
                color: #FFFFFF;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #3E6FEA;
                border-color: #2F5FD9;
            }
            QPushButton:pressed {
                background-color: #2F5FD9;
                border-color: #1E4FC8;
            }
            QPushButton:disabled {
                background-color: #E2E8F0;
                border-color: #E2E8F0;
                color: #94A3B8;
            }
        """)
        row1.addWidget(self.start_btn, stretch=1)

        self.stop_btn = QPushButton("停止并锁定")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_grasp)
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF1F1;
                border: 1px solid #E5484D;
                border-radius: 8px;
                color: #E5484D;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FEE2E2;
                border-color: #DC2626;
                color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #FCA5A5;
                border-color: #B91C1C;
            }
            QPushButton:disabled {
                background-color: #F8FAFC;
                border-color: #E8EDF3;
                color: #94A3B8;
            }
        """)
        row1.addWidget(self.stop_btn, stretch=1)
        btn_layout.addLayout(row1)

        # 第二行：安全释放 与 定制锁定姿态 并排
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.release_btn = QPushButton("安全释放")
        self.release_btn.setCursor(Qt.PointingHandCursor)
        self.release_btn.clicked.connect(self._release_grasp)
        self.release_btn.setFixedHeight(32)
        self.release_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #DCE3EC;
                border-radius: 8px;
                color: #1E293B;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #EAF1FF;
                border-color: #4F7FF7;
                color: #4F7FF7;
            }
            QPushButton:pressed {
                background-color: #DBEAFE;
                border-color: #3E6FEA;
            }
            QPushButton:disabled {
                background-color: #F8FAFC;
                border-color: #E8EDF3;
                color: #94A3B8;
            }
        """)
        row2.addWidget(self.release_btn, stretch=1)

        self.custom_lock_btn = QPushButton("定制并锁定")
        self.custom_lock_btn.setCursor(Qt.PointingHandCursor)
        self.custom_lock_btn.setEnabled(False)
        self.custom_lock_btn.clicked.connect(self._custom_lock_pose)
        self.custom_lock_btn.setFixedHeight(32)
        self.custom_lock_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F7FF7;
                border: 1px solid #3E6FEA;
                border-radius: 8px;
                color: #FFFFFF;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #3E6FEA;
                border-color: #2F5FD9;
            }
            QPushButton:pressed {
                background-color: #2F5FD9;
                border-color: #1E4FC8;
            }
            QPushButton:disabled {
                background-color: #E2E8F0;
                border-color: #E2E8F0;
                color: #94A3B8;
            }
        """)
        row2.addWidget(self.custom_lock_btn, stretch=1)
        btn_layout.addLayout(row2)

        # 第三行：空载标定独占一行
        row3 = QHBoxLayout()
        self.calib_btn = QPushButton("空载基线标定")
        self.calib_btn.setCursor(Qt.PointingHandCursor)
        self.calib_btn.clicked.connect(self._run_calibration)
        self.calib_btn.setFixedHeight(32)
        self.calib_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFBEB;
                border: 1px solid #D99000;
                border-radius: 8px;
                color: #D99000;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FEF3C7;
                border-color: #B45309;
                color: #B45309;
            }
            QPushButton:pressed {
                background-color: #FDE68A;
                border-color: #92400E;
            }
            QPushButton:disabled {
                background-color: #F8FAFC;
                border-color: #E8EDF3;
                color: #94A3B8;
            }
        """)
        row3.addWidget(self.calib_btn, stretch=1)
        btn_layout.addLayout(row3)

        layout.addLayout(btn_layout)

    def _wire_signals(self):
        # 订阅全局信号
        signal_bus.hand_info_ready.connect(self._on_hand_changed)
        signal_bus.ui_state_changed.connect(self._on_ui_state)

        # 订阅抓取控制器专用信号
        signal_bus.grasp_state_changed.connect(self._on_grasp_state_changed)
        signal_bus.grasp_joint_state_changed.connect(self._on_joint_state_changed)
        signal_bus.grasp_contact_detected.connect(self._on_contact_detected)

    def _rebuild_finger_rows(self):
        # 清理旧行
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.finger_rows.clear()

        # 根据当前手部关节配置，决定行列表
        config = HAND_CONFIGS.get(self.hand_joint)
        if not config:
            return

        # 弯曲关节的索引通常为：O6 为 0,2,3,4,5；L10 等各不相同
        # 我们可以展示当前型号包含的所有关节
        for idx, name in enumerate(config.joint_names):
            # 过滤不需要的预留或不参与物理弯曲的控制轴（如侧摆），但在卡片里若需要也可以都展示
            # 为了紧凑性，我们把不需要闭合的关节（即侧摆）和需要闭合的关节做区分
            # 在这里，全部展现以便直观；方向为0的关节会自动判定为 FROZEN 冻结
            row = FingerRow(idx, name)
            self.list_layout.addWidget(row)
            self.finger_rows[idx] = row

    def _refresh_profiles(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        
        # 载入符合型号的
        profiles = grasp_profile_manager.get_profiles_for_model(self.hand_joint)
        for p in profiles:
            self.combo.addItem(p.name, p.id)
            
        self.combo.blockSignals(False)
        self._on_profile_changed()

    def _on_profile_changed(self):
        profile_id = self.combo.currentData()
        if not profile_id:
            self.settings_btn.setEnabled(False)
            return
        
        # 只要不是在抓取运动中，设置按钮就使能
        controller = AdaptiveGraspController.get_instance()
        self.settings_btn.setEnabled(controller.state == GraspState.IDLE)

    def _edit_parameters(self):
        profile_id = self.combo.currentData()
        p = grasp_profile_manager.get_profile(profile_id)
        if p:
            dlg = _ParamEditDialog(p, self)
            dlg.exec_()

    # ────── 控制交互触发 ──────

    def _reset_finger_ui(self):
        """重置清除各手指的接触评分进度条和状态。"""
        controller = AdaptiveGraspController.get_instance()
        for idx, row in self.finger_rows.items():
            row.update_score(0.0)
            row.update_state(GraspJointState.IDLE)
            # 方向为 0 的轴自动标记为 FROZEN
            if idx in controller.closing_directions and controller.closing_directions[idx] == 0:
                row.update_state(GraspJointState.FROZEN)

    def _start_grasp(self):
        profile_id = self.combo.currentData()
        if not profile_id:
            return

        # 开始新动作前，手动清空上次抓取的进度条与手指状态画面
        self._reset_finger_ui()

        controller = AdaptiveGraspController.get_instance()
        
        # 检查是否完成了标定，如果没有，询问是否切入试验模式
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if api and api.connected:
            hand_model = api.hand_joint or self.hand_joint
            firmware_version = "Virtual"
            if api.api is not None:
                try:
                    firmware_version = api.api.get_embedded_version()
                except Exception:
                    firmware_version = "unknown"
            
            has_calib = grasp_calibration_manager.is_calibrated(hand_model, api.hand_type, firmware_version)
            if not has_calib:
                # 弹窗询问
                reply = QMessageBox.warning(
                    self,
                    "标定文件缺失警告",
                    "当前硬件未发现有效的【空载标定基线】数据！\n为防止闭合过冲损坏设备，建议先完成标定。\n\n您是否要以【最低安全速度试验模式】强制闭合运行？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    controller.start_grasp(profile_id, force_test=True)
                return

        controller.start_grasp(profile_id)

    def _stop_grasp(self):
        AdaptiveGraspController.get_instance().stop_grasp("用户手动停止")

    def _release_grasp(self):
        AdaptiveGraspController.get_instance().release_grasp()

    def _run_calibration(self):
        reply = QMessageBox.information(
            self,
            "开始空载基线标定",
            "请注意标定安全确认：\n"
            "1. 确认机械手【完全悬空】，且没有遮挡任何手指的闭合动作；\n"
            "2. 确认【急停按钮】可随时用鼠标点击；\n"
            "3. 标定期间，手指将自动完全收缩并退回，请勿在机械手动作区摆放任何物体！\n\n"
            "点击“确定”开始扫描标定。",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply == QMessageBox.Ok:
            self._reset_finger_ui()
            AdaptiveGraspController.get_instance().start_calibration()

    # ────── 信号监听回调 ──────

    def _on_hand_changed(self, info: dict):
        self.hand_joint = info.get("hand_joint", self.hand_joint)
        self._rebuild_finger_rows()
        self._refresh_profiles()

    def _on_ui_state(self, snapshot):
        # 只要不是在自适应抓取和标定过程中，才允许切换配置
        controller = AdaptiveGraspController.get_instance()
        is_idle = (controller.state == GraspState.IDLE)
        
        self.combo.setEnabled(is_idle)
        self.settings_btn.setEnabled(is_idle)
        self.calib_btn.setEnabled(is_idle and snapshot.connection == ConnectionState.CONNECTED)

    def _on_grasp_state_changed(self, state: GraspState):
        # 更新总状态 Badge
        text, bg_color, fg_color = STATE_NAMES.get(state, ("空闲", "#F1F5F9", "#475569"))
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(f"""
            background: {bg_color};
            color: {fg_color};
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 10px;
        """)

        # 更新按钮使能
        is_running = (state not in (GraspState.IDLE, GraspState.SUCCESS))
        is_idle = (state == GraspState.IDLE)
        
        self.start_btn.setEnabled(is_idle)
        self.stop_btn.setEnabled(is_running)
        self.release_btn.setEnabled(state != GraspState.CALIBRATING and state != GraspState.RELEASING)
        self.custom_lock_btn.setEnabled(state == GraspState.SUCCESS)
        self.calib_btn.setEnabled(is_idle)
        self.combo.setEnabled(is_idle)
        self.settings_btn.setEnabled(is_idle)

    def _on_joint_state_changed(self, idx: int, state: GraspJointState):
        if idx in self.finger_rows:
            self.finger_rows[idx].update_state(state)

    def _on_contact_detected(self, idx: int, score: float):
        if idx in self.finger_rows:
            self.finger_rows[idx].update_score(score)

    def _custom_lock_pose(self):
        controller = AdaptiveGraspController.get_instance()
        if controller.state != GraspState.SUCCESS:
            return
            
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self,
            "定制抓取预设",
            "请输入当前锁定的自适应抓取姿态名称:",
            text="自适应抓取"
        )
        if not ok or not name.strip():
            return
            
        name = name.strip()
        
        from lhgui.core.custom_preset_store import custom_preset_store, CustomPreset
        if custom_preset_store.exists_name(self.hand_joint, name):
            QMessageBox.critical(self, "保存失败", f"预设动作 '{name}' 已存在，请输入其他名称。")
            return
            
        import uuid
        import datetime
        from lhgui.core.joint_state_cache import joint_state_cache
        
        snapshot = joint_state_cache.latest(self.hand_joint)
        if not snapshot:
            QMessageBox.critical(self, "保存失败", "获取手部当前关节实际位置失败。")
            return
            
        values = list(snapshot.values)
        
        new_preset = CustomPreset(
            id=str(uuid.uuid4()),
            name=name,
            category="custom",
            hand_model=self.hand_joint,
            values=tuple(values),
            created_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            editable_joint_indices=tuple(range(len(values)))
        )
        
        try:
            custom_preset_store.add(new_preset)
            signal_bus.custom_presets_changed.emit()
            QMessageBox.information(
                self,
                "定制成功",
                f"★★ 当前抓取姿态已成功保存为自定义预设：'{name}' ★★\n该姿态已在快捷动作中锁定，您可以通过动作卡片直接一键执行该姿态。"
            )
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存预设: {e}")
