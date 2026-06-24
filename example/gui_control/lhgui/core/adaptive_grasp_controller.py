#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应抓取核心控制器。

职责：
1. 运行自适应抓取的有限状态机。
2. 以配置的步长和间隔，定时执行增量闭合下发。
3. 校验关节反馈数据新鲜度，对通信异常执行中止。
4. 综合各关节分析器的判定评分，控制单指独立停止/冻结。
5. 判断多点接触拓扑是否满足，并控制预紧与保持。
6. 仿真模式：在离线/虚拟模式下，模拟关节跟随及接触力停滞。
"""
import time
from typing import List, Dict, Tuple, Optional

from PyQt5.QtCore import QObject, QTimer

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState
from lhgui.config.constants import HAND_CONFIGS
from lhgui.core.grasp_state import GraspState, GraspJointState
from lhgui.core.grasp_profile import GraspProfile, grasp_profile_manager
from lhgui.core.grasp_calibration import grasp_calibration_manager
from lhgui.core.joint_signal_analyzer import JointSignalAnalyzer
from lhgui.core.joint_state_cache import joint_state_cache


class AdaptiveGraspController(QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        AdaptiveGraspController._instance = self

        self.state = GraspState.IDLE
        self.profile: Optional[GraspProfile] = None
        self.analyzers: Dict[int, JointSignalAnalyzer] = {}
        self.joint_states: Dict[int, GraspJointState] = {}
        
        # 当前控制目标
        self.current_targets: List[int] = []
        # 各关节闭合方向
        self.closing_directions: Dict[int, int] = {}
        
        # 抓取控制定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)

        # 过程变量
        self.start_time = 0.0
        self.state_start_time = 0.0
        self.preload_steps_taken = 0
        self.contact_positions: Dict[int, float] = {}
        self.candidate_counters: Dict[int, int] = {}
        self.fine_tick_counter = 0

        # 是否强制测试模式（无标定文件时退化执行）
        self.force_test_mode = False

        # 订阅紧急停止
        signal_bus.playback_stopped.connect(self._on_emergency_stop)

    @classmethod
    def get_instance(cls) -> "AdaptiveGraspController":
        if cls._instance is None:
            cls._instance = AdaptiveGraspController()
        return cls._instance

    # ────── 控制接口 ──────

    def start_grasp(self, profile_id: str, force_test: bool = False):
        """启动自适应抓取过程。"""
        if self.state != GraspState.IDLE:
            signal_bus.connection_message.emit("warning", "自适应抓取任务已在运行中，请勿重复操作")
            return

        # 1. 载入 Profile
        self.profile = grasp_profile_manager.get_profile(profile_id)
        if not self.profile:
            signal_bus.connection_message.emit("error", f"未找到指定的抓取 Profile: {profile_id}")
            return

        # 2. 动作互斥锁死
        ui_state.set_action_state(ActionState.ACTION_RUNNING)
        self.force_test_mode = force_test
        self._change_state(GraspState.PREPARING)

        # 3. 获取 API 信息与标定
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if not api or not api.connected:
            self._abort("设备未连接，无法开始自适应抓取")
            return

        hand_model = api.hand_joint or self.profile.hand_model
        hand_type = api.hand_type or "right"
        
        # 获取固件版本用于标定匹配
        firmware_version = "Virtual"
        if api.api is not None:
            try:
                firmware_version = api.api.get_embedded_version()
            except Exception:
                firmware_version = "unknown"

        # 4. 校验空载标定
        has_calib = grasp_calibration_manager.is_calibrated(hand_model, hand_type, firmware_version)
        calib_data = grasp_calibration_manager.get_calibration(hand_model, hand_type, firmware_version)
        
        if not has_calib and not self.force_test_mode:
            self._abort("未完成空载标定！为防止损坏硬件，已禁止进入正式抓取。请先在空载下完成标定。")
            return
        
        if self.force_test_mode and not has_calib:
            signal_bus.connection_message.emit("warning", "标定不存在，当前切入【低速试验模式】运行！")

        # 5. 初始化关节状态与分析器
        config = HAND_CONFIGS.get(hand_model)
        if not config:
            self._abort(f"未找到手部型号 {hand_model} 的常量配置")
            return

        total_joints = len(config.init_pos)
        self.current_targets = list(self.profile.pregrasp)
        if len(self.current_targets) < total_joints:
            self.current_targets.extend(list(config.init_pos[len(self.current_targets):]))

        self.analyzers.clear()
        self.joint_states.clear()
        self.closing_directions.clear()
        self.contact_positions.clear()
        self.candidate_counters.clear()
        self.preload_steps_taken = 0
        self.fine_tick_counter = 0

        # 判断关节闭合方向，并初始化分析器
        for idx in range(total_joints):
            pre = self.current_targets[idx]
            lim = self.profile.close_limits[idx] if idx < len(self.profile.close_limits) else pre
            
            # 计算方向：数值减小为闭合(-1)，增大为闭合(1)，相同则不动作(0)
            if lim < pre:
                direction = -1
            elif lim > pre:
                direction = 1
            else:
                direction = 0

            self.closing_directions[idx] = direction

            if direction == 0:
                self.joint_states[idx] = GraspJointState.FROZEN
            else:
                self.joint_states[idx] = GraspJointState.IDLE
                # 建立信号分析器
                # 计算滑动窗口点数
                w_size = int(self.profile.window_ms / self.profile.interval_ms)
                w_size = max(5, w_size)
                
                analyzer = JointSignalAnalyzer(idx, direction, window_size=w_size)
                
                # 加载标定阈值
                if calib_data:
                    # 匹配对应关节
                    j_cal = next((j for j in calib_data.joints if j.joint_index == idx), None)
                    if j_cal:
                        analyzer.update_thresholds(
                            error_th=j_cal.error_threshold,
                            jitter_th=j_cal.jitter_threshold,
                            movement_th=j_cal.movement_threshold
                        )
                
                # 如果是试验模式，使用较低的灵敏度兜底
                if self.force_test_mode and not has_calib:
                    analyzer.update_thresholds(error_th=15.0, jitter_th=2.0, movement_th=2.0)

                self.analyzers[idx] = analyzer
                self.candidate_counters[idx] = 0
                signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.IDLE)

        # 5.5 自动生成并下发临时的低扭矩物理限制（大拇指 0 轴设为极微力 40，其余轴设为 80），保护脆弱水瓶
        temp_torques = [255] * total_joints
        for idx in range(total_joints):
            if idx == 0:
                temp_torques[idx] = 40
            elif idx in self.closing_directions and self.closing_directions[idx] != 0:
                temp_torques[idx] = 80
            else:
                temp_torques[idx] = 255
        api.set_temporary_torque(temp_torques)

        # 6. 进入 PREGRASP 预抓取定位状态
        self._change_state(GraspState.PREGRASP)
        signal_bus.connection_message.emit("info", f"正在下发预抓取姿态目标: {self.current_targets}")
        signal_bus.finger_move_requested.emit(self.current_targets)

        # 延时 500ms 等待电机到位，然后开始定时控制循环
        QTimer.singleShot(500, self._start_control_loop)

    def stop_grasp(self, reason: str = "用户主动停止"):
        """停止当前抓取任务并保持当前位置不动。"""
        if self.state == GraspState.IDLE:
            return
        
        self.timer.stop()
        
        # 如果当前硬件连接，我们需要合并当前实际位置反馈更新目标，实现物理位置冻结
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if api and api.connected:
            snapshot = joint_state_cache.latest(api.hand_joint)
            if snapshot:
                self.current_targets = list(snapshot.values)
                signal_bus.finger_move_requested.emit(self.current_targets)

        self._change_state(GraspState.ABORTED)
        signal_bus.grasp_aborted.emit(reason)
        signal_bus.connection_message.emit("warning", f"抓取动作中止：{reason}")
        
        # 恢复状态机与 UI 锁
        self._cleanup()

    def release_grasp(self):
        """安全释放：缓慢步进张开手部，返回到预抓取姿态。"""
        if self.state in (GraspState.RELEASING, GraspState.CALIBRATING):
            return
        
        self.timer.stop()
        self._change_state(GraspState.RELEASING)
        signal_bus.connection_message.emit("info", "自适应抓取：正在安全张开释放手指…")
        
        # 1. 确保 profile 存在
        if not self.profile:
            from lhgui.core.api_manager import ApiManager
            api = ApiManager._instance
            hand_model = (api.hand_joint if api else None) or "O6"
            profiles = grasp_profile_manager.get_profiles_for_model(hand_model)
            self.profile = profiles[0] if profiles else grasp_profile_manager.get_profile("default_power_grasp_o6")
            
        # 2. 如果 closing_directions 为空，自动初始化
        if not self.closing_directions and self.profile:
            from lhgui.config.constants import HAND_CONFIGS
            config = HAND_CONFIGS.get(self.profile.hand_model)
            if config:
                total_joints = len(config.init_pos)
                pregrasp = list(self.profile.pregrasp)
                if len(pregrasp) < total_joints:
                    pregrasp.extend(list(config.init_pos[len(pregrasp):]))
                for idx in range(total_joints):
                    pre = pregrasp[idx]
                    lim = self.profile.close_limits[idx] if idx < len(self.profile.close_limits) else pre
                    if lim < pre:
                        self.closing_directions[idx] = -1
                    elif lim > pre:
                        self.closing_directions[idx] = 1
                    else:
                        self.closing_directions[idx] = 0
                        
        # 3. 确保有当前目标位置作为张开起点
        if (not self.current_targets or len(self.current_targets) == 0) and self.profile:
            from lhgui.core.api_manager import ApiManager
            api = ApiManager._instance
            snapshot = joint_state_cache.latest(api.hand_joint if api else None)
            if snapshot:
                self.current_targets = list(snapshot.values)
            else:
                self.current_targets = list(self.profile.pregrasp)
                
        # 启动定时控制环，用于步进释放张开
        self.timer.start(self.profile.interval_ms if self.profile else 50)

    def start_calibration(self):
        """开始空载标定任务。"""
        if self.state != GraspState.IDLE:
            signal_bus.connection_message.emit("warning", "当前有任务运行中，请勿重复操作")
            return

        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if not api or not api.connected:
            signal_bus.connection_message.emit("error", "设备未连接，无法开始标定")
            return

        hand_model = api.hand_joint
        config = HAND_CONFIGS.get(hand_model)
        if not config:
            signal_bus.connection_message.emit("error", f"未找到手部 {hand_model} 的配置")
            return

        # 锁死动作
        ui_state.set_action_state(ActionState.ACTION_RUNNING)
        self._change_state(GraspState.CALIBRATING)

        total_joints = len(config.init_pos)
        self.current_targets = list(config.init_pos)
        
        # 初始化闭合方向，大拇指侧摆等方向为0，不参与闭合
        self.closing_directions.clear()
        self.analyzers.clear()
        
        profiles = grasp_profile_manager.get_profiles_for_model(hand_model)
        default_profile = profiles[0] if profiles else None
        self.profile = default_profile
        
        close_lims = list(default_profile.close_limits) if default_profile else [10] * total_joints
        if len(close_lims) < total_joints:
            close_lims.extend([10] * (total_joints - len(close_lims)))

        self.calib_close_limits = close_lims
        self.calib_errors = {idx: [] for idx in range(total_joints)}
        self.calib_jitters = {idx: [] for idx in range(total_joints)}

        for idx in range(total_joints):
            pre = self.current_targets[idx]
            lim = self.calib_close_limits[idx]
            
            if lim < pre:
                self.closing_directions[idx] = -1
            elif lim > pre:
                self.closing_directions[idx] = 1
            else:
                self.closing_directions[idx] = 0

            # 建立标定时所需的临时分析器
            if self.closing_directions[idx] != 0:
                self.analyzers[idx] = JointSignalAnalyzer(idx, self.closing_directions[idx], window_size=10)

        signal_bus.connection_message.emit("info", "空载标定：正在复位到初始位置…")
        signal_bus.finger_move_requested.emit(self.current_targets)

        # 延时 600ms 后开启定时器慢速闭合
        QTimer.singleShot(600, self._start_calibration_loop)

    def _start_calibration_loop(self):
        if self.state != GraspState.CALIBRATING:
            return
        self.timer.start(50)  # 以 50ms 周期慢速推进
        signal_bus.connection_message.emit("success", "开始执行全行程空载闭合扫描，请保持静止...")

    def _process_calibration_tick(self):
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        hand_model = api.hand_joint
        
        is_virtual = (api.api is None)
        if is_virtual:
            self._simulate_feedback()
            
        snapshot = joint_state_cache.latest(hand_model)
        now_time = time.time()
        
        if not snapshot or (now_time - snapshot.timestamp) * 1000.0 > 300.0:
            self._abort("标定过程中底层通信数据卡死，已安全退出")
            return

        actual_positions = list(snapshot.values)
        target_updated = False
        all_finished = True

        for idx, direction in self.closing_directions.items():
            if direction == 0:
                continue
            
            actual = actual_positions[idx]
            target = self.current_targets[idx]
            limit = self.calib_close_limits[idx]
            
            # 如果尚未到达极限，继续闭合
            if direction * (target - limit) < 0:
                all_finished = False
                # 标定扫描使用平稳且较快的步进增量（设为 4）
                next_target = target + direction * 4
                if direction * (next_target - limit) > 0:
                    next_target = limit
                
                self.current_targets[idx] = int(next_target)
                target_updated = True
                
                # 记录跟踪误差与抖动值
                analyzer = self.analyzers[idx]
                analyzer.update(actual, target, now_time)
                
                error = analyzer.position_error
                jitter = analyzer.jitter_value
                
                if is_virtual:
                    import random
                    error += random.uniform(0.5, 2.0)
                    jitter += random.uniform(0.1, 0.4)
                
                self.calib_errors[idx].append(error)
                self.calib_jitters[idx].append(jitter)

        if target_updated:
            signal_bus.finger_move_requested.emit(self.current_targets)

        if all_finished:
            # 行程结束，完成标定
            self.timer.stop()
            signal_bus.connection_message.emit("info", "行程扫描已完成，正在计算并保存标定数据…")
            
            firmware_version = "Virtual"
            if api.api is not None:
                try:
                    firmware_version = api.api.get_embedded_version()
                except Exception:
                    firmware_version = "unknown"
                    
            grasp_calibration_manager.calculate_and_save(
                hand_model, api.hand_type, firmware_version, self.calib_errors, self.calib_jitters
            )
            
            signal_bus.connection_message.emit("success", "★★ 空载标定成功，阈值参数已持久化保存！ ★★")
            
            # 复位到张开位置
            config = HAND_CONFIGS.get(hand_model)
            self.current_targets = list(config.init_pos)
            signal_bus.finger_move_requested.emit(self.current_targets)
            
            QTimer.singleShot(800, self._on_release_finished)

    # ────── 内部控制 ──────

    def _start_control_loop(self):
        if self.state != GraspState.PREGRASP:
            return
        
        self.start_time = time.time()
        self._change_state(GraspState.CLOSING_COARSE)
        
        # 激活各动作关节为 COARSE 闭合
        for idx, state in self.joint_states.items():
            if state == GraspJointState.IDLE:
                self.joint_states[idx] = GraspJointState.CLOSING_COARSE
                signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.CLOSING_COARSE)

        # 启动定时器
        self.timer.start(self.profile.interval_ms)
        signal_bus.connection_message.emit("success", "开始自适应增量闭合阶段。")

    def _cleanup(self):
        self.state = GraspState.IDLE
        signal_bus.grasp_state_changed.emit(GraspState.IDLE)
        ui_state.set_action_state(ActionState.IDLE)
        
        # 恢复先前备份的用户全局扭矩设定
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if api:
            api.restore_saved_torque()

    def _on_release_finished(self):
        self._change_state(GraspState.IDLE)
        signal_bus.connection_message.emit("info", "设备释放完毕，已就绪。")
        self._cleanup()

    def _change_state(self, new_state: GraspState):
        self.state = new_state
        self.state_start_time = time.time()
        
        # 一旦切出闭合逼近阶段（即进入预紧、保持、成功、失败或中止空闲等状态），将所有未确认接触的运动关节置为 FROZEN
        if new_state not in (GraspState.PREPARING, GraspState.PREGRASP, GraspState.CLOSING_COARSE, GraspState.CLOSING_FINE):
            for idx, direction in self.closing_directions.items():
                if direction != 0:
                    if self.joint_states.get(idx) in (GraspJointState.IDLE, GraspJointState.CLOSING_COARSE, GraspJointState.CLOSING_FINE, GraspJointState.CONTACT_CANDIDATE):
                        self.joint_states[idx] = GraspJointState.FROZEN
                        signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.FROZEN)
                        
        signal_bus.grasp_state_changed.emit(new_state)

    def _abort(self, reason: str):
        self.stop_grasp(reason)

    def _fail(self, reason: str):
        self.timer.stop()
        self._change_state(GraspState.FAILED)
        signal_bus.grasp_failed.emit(reason)
        signal_bus.connection_message.emit("error", f"自适应抓取失败: {reason}")
        self._cleanup()

    def _on_emergency_stop(self):
        if self.state != GraspState.IDLE:
            self.stop_grasp("紧急停止触发")

    # ────── 控制循环（核心状态机 tick） ──────

    def _on_tick(self):
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        if not api or not api.connected:
            self._abort("物理设备连接中断")
            return

        hand_model = api.hand_joint or self.profile.hand_model

        # 1. 检查通信数据新鲜度（硬件看门狗）
        # 如果是离线/虚拟模式，则使用自制的模拟器更新反馈以实现仿真
        is_virtual = (api.api is None)
        
        if is_virtual:
            # 仿真反馈更新：实际位置缓慢跟着目标位置运动，并提供摩擦阻力模拟
            self._simulate_feedback()
        
        snapshot = joint_state_cache.latest(hand_model)
        now_time = time.time()
        
        timeout_ms = self.profile.data_timeout_ms if self.profile else 300.0
        if not snapshot or (now_time - snapshot.timestamp) * 1000.0 > timeout_ms:
            self._abort("底层通信数据卡顿或已停止更新")
            return

        # 2. 定时器驱动状态流转
        actual_positions = list(snapshot.values)

        if self.state == GraspState.CALIBRATING:
            self._process_calibration_tick()
        elif self.state in (GraspState.CLOSING_COARSE, GraspState.CLOSING_FINE):
            self._process_closing_tick(actual_positions, now_time)
            
        elif self.state == GraspState.PRELOADING:
            self._process_preloading_tick()
            
        elif self.state == GraspState.HOLDING:
            self._process_holding_tick(actual_positions, now_time)
            
        elif self.state == GraspState.RELEASING:
            self._process_releasing_tick()

        # 3. 针对夹紧相关状态，实施大拇指零刚度柔性退让随动，消除被顶退引起的位置跟踪过载力矩
        if self.state in (GraspState.CLOSING_COARSE, GraspState.CLOSING_FINE, GraspState.PRELOADING, GraspState.HOLDING):
            if self.joint_states.get(0) == GraspJointState.CONTACT_CONFIRMED:
                actual_thumb = actual_positions[0]
                target_thumb = self.current_targets[0]
                if actual_thumb > target_thumb:
                    self.current_targets[0] = int(actual_thumb)
                    signal_bus.finger_move_requested.emit(self.current_targets)

    def _simulate_feedback(self):
        """虚拟/离线模式反馈仿真机。
        
        模拟手部跟随目标动作。当手指闭合值减小到 150 以下时，
        模拟产生突然阻碍（即实际位置不再跟进目标位置），触发跟踪误差与停滞得分。
        """
        from lhgui.core.api_manager import ApiManager
        api = ApiManager._instance
        
        # 模拟产生关节新反馈
        simulated_pose = list(api._virtual_pose)
        
        for idx in range(len(simulated_pose)):
            target = self.current_targets[idx]
            current = simulated_pose[idx]
            
            # 如果到达 150 以下且闭合方向是负向，模拟发生接触物理阻挡
            # （大拇指弯曲：0，食指：2，中指：3 等，侧摆 1 固定不挡）
            if current < 150.0 and self.closing_directions.get(idx, 0) == -1 and idx != 1:
                # 模拟碰触物体后完全静止
                pass
            else:
                # 正常跟随，带有一点一阶时滞惯性
                diff = target - current
                simulated_pose[idx] = current + diff * 0.6
                
        # 塞入 cache 中，模拟真实上报
        api._virtual_pose = [int(v) for v in simulated_pose]
        joint_state_cache.update(api.hand_joint, api._virtual_pose)

    def _process_closing_tick(self, actual_positions: List[float], now_time: float):
        # 步长选取
        step_size = self.profile.coarse_step if self.state == GraspState.CLOSING_COARSE else self.profile.fine_step
        
        # 累积精细步进 tick 计数，用以支持隔帧推进，降低逼近速度
        if self.state == GraspState.CLOSING_FINE:
            self.fine_tick_counter += 1
            
        target_updated = False
        any_candidate_found = False
        
        for idx, direction in self.closing_directions.items():
            if direction == 0 or self.joint_states[idx] in (GraspJointState.FROZEN, GraspJointState.CONTACT_CONFIRMED, GraspJointState.LIMIT_REACHED):
                continue
            
            # 获取关节最新反馈
            actual = actual_positions[idx]
            target = self.current_targets[idx]
            
            # 更新信号分析器
            analyzer = self.analyzers[idx]
            analyzer.update(actual, target, now_time)
            
            # 计算接触综合评分
            score = analyzer.calculate_contact_score()
            signal_bus.grasp_contact_detected.emit(idx, score)

            # 异常检查：最大误差限额保护（电机卡死或堵转）
            if analyzer.position_error > 120.0:
                self.joint_states[idx] = GraspJointState.ERROR
                signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.ERROR)
                self._abort(f"关节 {idx} 位置跟踪误差过大，触发保护")
                return

            # 一、接触判定逻辑
            if score >= self.profile.score_threshold:
                # 进入接触候选状态
                self.candidate_counters[idx] += 1
                any_candidate_found = True
                
                if self.joint_states[idx] != GraspJointState.CONTACT_CANDIDATE:
                    self.joint_states[idx] = GraspJointState.CONTACT_CANDIDATE
                    signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.CONTACT_CANDIDATE)
                    signal_bus.grasp_curve_event.emit({
                        "timestamp": now_time, "joint_index": idx, "event_type": "contact_candidate", "value": actual
                    })

                # 连续确认窗口判断 -> 确认接触
                if self.candidate_counters[idx] >= self.profile.confirmation_windows:
                    self.joint_states[idx] = GraspJointState.CONTACT_CONFIRMED
                    signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.CONTACT_CONFIRMED)
                    
                    # 捕获位置并冻结
                    self.contact_positions[idx] = actual
                    self.current_targets[idx] = int(actual)
                    target_updated = True
                    
                    signal_bus.connection_message.emit("info", f"关节 {idx} 确认接触，当前位置已冻结: {int(actual)}")
                    signal_bus.grasp_curve_event.emit({
                        "timestamp": now_time, "joint_index": idx, "event_type": "contact_confirmed", "value": actual
                    })
                    continue
            else:
                # 没达到判定得分，清空计数器，回退至 CLOSING 状态
                self.candidate_counters[idx] = 0
                if self.joint_states[idx] == GraspJointState.CONTACT_CANDIDATE:
                    self.joint_states[idx] = GraspJointState.CLOSING_FINE if self.state == GraspState.CLOSING_FINE else GraspJointState.CLOSING_COARSE
                    signal_bus.grasp_joint_state_changed.emit(idx, self.joint_states[idx])

            # 二、行程极限判断
            limit = self.profile.close_limits[idx]
            # 计算是否越过极限
            if direction * (target - limit) >= 0:
                self.joint_states[idx] = GraspJointState.LIMIT_REACHED
                signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.LIMIT_REACHED)
                self.current_targets[idx] = limit
                target_updated = True
                
                signal_bus.grasp_curve_event.emit({
                    "timestamp": now_time, "joint_index": idx, "event_type": "limit_reached", "value": float(limit)
                })
                continue

            # 三、继续增量推进目标位置
            # 精细逼近时，每 3 次 tick (150ms) 才真正向下发累增 1 步，以极低微动进给速度保护瓶体
            is_fine_move_tick = True
            if self.state == GraspState.CLOSING_FINE and (self.fine_tick_counter % 3 != 0):
                is_fine_move_tick = False

            if is_fine_move_tick:
                next_target = target + direction * step_size
                # 防越界保护
                if direction * (next_target - limit) > 0:
                    next_target = limit
                    self.joint_states[idx] = GraspJointState.LIMIT_REACHED
                    signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.LIMIT_REACHED)
                    signal_bus.grasp_curve_event.emit({
                        "timestamp": now_time, "joint_index": idx, "event_type": "limit_reached", "value": float(limit)
                    })

                self.current_targets[idx] = int(next_target)
                target_updated = True

        # 全局步长切换
        if self.state == GraspState.CLOSING_COARSE and any_candidate_found:
            self._change_state(GraspState.CLOSING_FINE)
            for idx, state in self.joint_states.items():
                if state == GraspJointState.CLOSING_COARSE:
                    self.joint_states[idx] = GraspJointState.CLOSING_FINE
                    signal_bus.grasp_joint_state_changed.emit(idx, GraspJointState.CLOSING_FINE)
            signal_bus.connection_message.emit("info", "检测到疑似接触，降速切入精细逼近。")

        # 下发运动目标
        if target_updated:
            signal_bus.finger_move_requested.emit(self.current_targets)

        # 四、接触拓扑和超时检查
        self._check_closing_termination(now_time)

    def _check_closing_termination(self, now_time: float):
        # 1. 检查接触拓扑
        # 大拇指弯曲：在 O6/L6/L7 索引一般为 0，在 L10 也是 0。我们可以默认检查 0 号关节
        thumb_idx = 0
        thumb_ok = True
        if self.profile.thumb_required:
            thumb_state = self.joint_states.get(thumb_idx, GraspJointState.FROZEN)
            # 大拇指若不闭合则是 frozen（视为合法通过），若闭合必须确认接触
            if thumb_state != GraspJointState.FROZEN and thumb_state != GraspJointState.CONTACT_CONFIRMED:
                thumb_ok = False

        # 四指至少有 minimum_finger_contacts 个接触
        other_finger_idxs = [idx for idx in self.closing_directions.keys() if idx != thumb_idx and self.closing_directions[idx] != 0]
        other_contacts = sum(1 for idx in other_finger_idxs if self.joint_states[idx] == GraspJointState.CONTACT_CONFIRMED)

        # 成功判定
        if thumb_ok and other_contacts >= self.profile.minimum_finger_contacts:
            self._change_state(GraspState.PRELOADING)
            self.preload_steps_taken = 0
            signal_bus.connection_message.emit("success", "满足有效多点接触拓扑，进入预紧阶段。")
            return

        # 2. 空抓判定：所有运动关节都已经冻结或到达极限，但未满足上述接触拓扑
        all_done = True
        for idx, direction in self.closing_directions.items():
            if direction == 0:
                continue
            if self.joint_states[idx] not in (GraspJointState.CONTACT_CONFIRMED, GraspJointState.LIMIT_REACHED):
                all_done = False
                break
        
        if all_done:
            self._fail("未能触及物体，到达行程安全极限（空抓）")
            return

        # 3. 整体超时判定
        if (now_time - self.start_time) * 1000.0 > self.profile.timeout_ms:
            self._fail("抓取时间超时")

    def _process_preloading_tick(self):
        """执行有限步数的微幅位置预紧。"""
        if self.preload_steps_taken >= self.profile.maximum_preload_steps:
            # 预紧完成，切入保持验证阶段
            self._change_state(GraspState.HOLDING)
            signal_bus.connection_message.emit("success", "预紧结束，开启稳定性保持验证。")
            return

        target_updated = False
        
        # 仅对已确认接触的关节追加偏移（排除大拇指 0 号弯曲轴）
        for idx, direction in self.closing_directions.items():
            if direction == 0 or self.joint_states[idx] != GraspJointState.CONTACT_CONFIRMED:
                continue
            if idx == 0:  # 大拇指作为主对撑面，不执行预紧收紧
                continue
            
            limit = self.profile.close_limits[idx]
            target = self.current_targets[idx]
            
            # 追加 preload_step 偏移
            next_target = target + direction * self.profile.preload_step
            # 保护性限幅
            if direction * (next_target - limit) > 0:
                next_target = limit
                
            self.current_targets[idx] = int(next_target)
            target_updated = True

        self.preload_steps_taken += 1
        
        if target_updated:
            signal_bus.finger_move_requested.emit(self.current_targets)

    def _process_holding_tick(self, actual_positions: List[float], now_time: float):
        """保持阶段：停止推进目标值，开启稳定性与滑脱校验。"""
        # 持续验证时长
        elapsed_ms = (now_time - self.state_start_time) * 1000.0
        
        # 对已确认接触的关节实施稳定性滑动监控
        for idx, direction in self.closing_directions.items():
            if direction == 0 or self.joint_states[idx] != GraspJointState.CONTACT_CONFIRMED:
                continue
            
            actual = actual_positions[idx]
            target = self.current_targets[idx]
            
            # 1. 位置漂移校验：如果实际位置反向回退（表示打滑或物体滑脱）
            contact_pos = self.contact_positions.get(idx, actual)
            # 反向偏移差
            backward_slip = (contact_pos - actual) * direction
            # 如果向张开方向滑脱超过 6.0，判定为失稳
            if backward_slip < -6.0:
                self._fail(f"关节 {idx} 发生明显反向漂移({backward_slip:.1f})，判定抓取失稳滑脱")
                return

            # 2. 位置误差突变保护
            error = abs(target - actual)
            analyzer = self.analyzers.get(idx)
            if analyzer:
                analyzer.update(actual, target, now_time)
                # 若跟踪误差大于空载基线的大幅上限，说明发生了某种物理逃逸
                if error > analyzer.error_threshold * 2.0:
                    self._fail(f"关节 {idx} 跟踪误差突增，可能发生脱落")
                    return

        if elapsed_ms >= self.profile.verify_ms:
            self.timer.stop()
            self._change_state(GraspState.SUCCESS)
            signal_bus.grasp_completed.emit("自适应抓取成功并已锁定")
            signal_bus.connection_message.emit("success", "★★ 抓取状态验证通过，保持夹紧中 ★★")

    def _process_releasing_tick(self):
        """分步缓慢释放张开。"""
        if not self.profile:
            self.timer.stop()
            self._on_release_finished()
            return

        target_updated = False
        all_released = True
        
        # 释放张开使用更敏捷的较大步长（设为 8）以加速复位
        step_size = 8
        
        for idx, direction in self.closing_directions.items():
            if direction == 0:
                continue
                
            current_t = self.current_targets[idx]
            pregrasp_t = self.profile.pregrasp[idx]
            
            # 张开的方向是闭合方向的反向
            open_dir = -direction
            
            # 检查当前轴是否还未完全张开到达 pregrasp 初始位置
            if open_dir * (current_t - pregrasp_t) < 0:
                all_released = False
                next_t = current_t + open_dir * step_size
                # 越限保护
                if open_dir * (next_t - pregrasp_t) > 0:
                    next_t = pregrasp_t
                self.current_targets[idx] = int(next_t)
                target_updated = True
                
        if target_updated:
            signal_bus.finger_move_requested.emit(self.current_targets)
            
        if all_released:
            self.timer.stop()
            self._on_release_finished()
