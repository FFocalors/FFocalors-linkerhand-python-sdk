#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应抓取状态机控制器单元测试。

通过 FakeApiManager 屏蔽真实硬件，使用 QCoreApplication 提供 Qt 基础设施，
并手动调用控制器内部 _on_tick() 来驱动控制环，以此测试：
1. 状态机正常流转：PREPARING -> PREGRASP -> CLOSING_COARSE -> CLOSING_FINE -> PRELOADING -> HOLDING -> SUCCESS。
2. 独立冻结：当单个手指确认接触后，目标停止改变并被锁死。
3. 拓扑触发：拇指接触 + 其他两指接触 -> 触发预紧。
4. 紧急停止中止：触发紧急信号 -> ABORTED 中止。
5. 脏数据防护：通信数据过期 -> 触发 ABORTED 中止。
"""
import unittest
import sys
import os
import time

# 把项目根目录加进 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt5.QtCore import QCoreApplication
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ActionState
from lhgui.core.grasp_state import GraspState, GraspJointState
from lhgui.core.grasp_profile import GraspProfile, grasp_profile_manager
from lhgui.core.grasp_calibration import grasp_calibration_manager
from lhgui.core.joint_state_cache import joint_state_cache
from lhgui.core.adaptive_grasp_controller import AdaptiveGraspController


# 1. Mock API 管理器，模拟离线仿真状态
class FakeApiManager:
    def __init__(self):
        self.connected = True
        self.hand_joint = "O6"
        self.hand_type = "right"
        self.api = None  # 离线虚拟模式
        self._virtual_pose = [250, 80, 250, 250, 250, 250]

    def set_temporary_torque(self, torque):
        pass

    def restore_saved_torque(self):
        pass


class TestAdaptiveGraspController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 实例化控制台事件循环
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        from lhgui.core.api_manager import ApiManager
        ApiManager._instance = FakeApiManager()
        
        # 激活控制器
        self.controller = AdaptiveGraspController.get_instance()
        self.controller.timer.stop() # 防止测试期间真实定时器触发
        self.controller.state = GraspState.IDLE
        
        # 清空 cache
        joint_state_cache.clear()
        
        # 手动预写入标定数据，避免因缺少标定而拦截
        from lhgui.core.grasp_calibration import JointCalibrationData
        grasp_calibration_manager.save_calibration(
            hand_model="O6",
            hand_type="right",
            firmware_version="Virtual",
            joints=[JointCalibrationData(i, 10.0, 2.0, 2.0) for i in range(6)]
        )
        
        # 强制重置 Profile 内存数值，隔离用户 yaml 干扰
        p = grasp_profile_manager.get_profile("default_power_grasp_o6")
        if p:
            p.coarse_step = 4
            p.fine_step = 1
            p.preload_step = 1
            p.maximum_preload_steps = 1
            p.score_threshold = 0.65
            p.confirmation_windows = 3

    def test_initialization_to_closing(self):
        """测试从空闲到快速闭合的状态变迁。"""
        # 开始抓取
        self.controller.start_grasp("default_power_grasp_o6")
        
        # 应该进入 PREPARING，再由 QTimer 延迟触发进入 PREGRASP
        self.assertEqual(self.controller.state, GraspState.PREGRASP)
        self.assertEqual(ui_state.snapshot.action, ActionState.ACTION_RUNNING)

        # 手动模拟预就位完毕，触发进入 CLOSING_COARSE
        self.controller._start_control_loop()
        self.assertEqual(self.controller.state, GraspState.CLOSING_COARSE)
        self.assertEqual(self.controller.joint_states[0], GraspJointState.CLOSING_COARSE)
        self.assertEqual(self.controller.joint_states[1], GraspJointState.FROZEN) # 侧摆不动作

    def test_contact_and_preload_flow(self):
        """测试手指受阻触发接触、预紧并最终成功抓取的闭环流程。"""
        self.controller.start_grasp("default_power_grasp_o6")
        self.controller._start_control_loop()

        # 写入初始反馈值
        joint_state_cache.update("O6", [250, 80, 250, 250, 250, 250])
        
        # 1. 模拟运行，直到状态切换为 CLOSING_FINE
        ticks = 0
        while self.controller.state == GraspState.CLOSING_COARSE and ticks < 100:
            self.controller._on_tick()
            ticks += 1
        
        self.assertEqual(self.controller.state, GraspState.CLOSING_FINE)

        # 2. 模拟运行，直到状态切换为 PRELOADING
        ticks = 0
        while self.controller.state == GraspState.CLOSING_FINE and ticks < 100:
            self.controller._on_tick()
            ticks += 1

        self.assertEqual(self.controller.state, GraspState.PRELOADING)

        # 大拇指、食指、中指等应该已经确认接触并冻结
        self.assertEqual(self.controller.joint_states[0], GraspJointState.CONTACT_CONFIRMED)
        self.assertEqual(self.controller.joint_states[2], GraspJointState.CONTACT_CONFIRMED)
        self.assertEqual(self.controller.joint_states[3], GraspJointState.CONTACT_CONFIRMED)

        # 3. 驱动预紧 1 次 tick，此时完成第 1 步预紧，状态仍为 PRELOADING
        self.controller._on_tick()
        self.assertEqual(self.controller.preload_steps_taken, 1)
        self.assertEqual(self.controller.state, GraspState.PRELOADING)

        # 4. 再驱动 1 次 tick，因为已达到 maximum_preload_steps = 1，应该切换为 HOLDING 状态
        self.controller._on_tick()
        self.assertEqual(self.controller.state, GraspState.HOLDING)

        # 4. 改变其状态时间使其能够瞬间完成验证，免等 800ms
        self.controller.state_start_time = time.time() - 1.0
        self.controller._on_tick()

        # 验证通过，抓取成功，状态应当保持在 SUCCESS 锁定，且互斥锁依然保持 ACTION_RUNNING
        self.assertEqual(self.controller.state, GraspState.SUCCESS)
        self.assertEqual(ui_state.snapshot.action, ActionState.ACTION_RUNNING)

    def test_emergency_stop(self):
        """测试紧急停止的立即中止响应。"""
        self.controller.start_grasp("default_power_grasp_o6")
        self.controller._start_control_loop()
        self.assertEqual(self.controller.state, GraspState.CLOSING_COARSE)

        # 触发紧急停止信号
        signal_bus.playback_stopped.emit()

        # 应当立刻转为 IDLE
        self.assertEqual(self.controller.state, GraspState.IDLE)
        self.assertEqual(ui_state.snapshot.action, ActionState.IDLE)

    def test_data_expired(self):
        """测试底层通信断开，数据过期引发的安全中止保护。"""
        from lhgui.core.api_manager import ApiManager
        api_mgr = ApiManager._instance
        # 将 api 设为 non-None 对象，代表“物理在线”连接，由此跳过虚拟模式的自动跟随仿真更新，允许时间戳过期
        api_mgr.api = object()

        self.controller.start_grasp("default_power_grasp_o6")
        self.controller._start_control_loop()

        # 写入一帧新鲜数据
        joint_state_cache.update("O6", [250, 80, 250, 250, 250, 250])
        self.controller._on_tick()

        # 假装过了 2.0s，缓存数据过期 (timeout_ms = 300)
        # 我们手动修改最新快照的时间戳，使其成为一个旧的快照
        snapshot = joint_state_cache.latest("O6")
        object.__setattr__(snapshot, "timestamp", time.time() - 5.0)

        # 执行 tick，由于数据过期，应当触发中止退出
        self.controller._on_tick()
        self.assertEqual(self.controller.state, GraspState.IDLE)
        self.assertEqual(ui_state.snapshot.action, ActionState.IDLE)

    def test_safe_release_flow(self):
        """测试安全释放时的步进缓慢张开流程。"""
        self.controller.start_grasp("default_power_grasp_o6")
        self.controller._start_control_loop()
        
        # 强制将状态置为 SUCCESS 并锁定某些抓取位置（比如都停留在 140）
        self.controller.state = GraspState.SUCCESS
        self.controller.current_targets = [140] * 6
        
        # 启动安全释放
        self.controller.release_grasp()
        self.assertEqual(self.controller.state, GraspState.RELEASING)
        
        # O6 的 pregrasp 目标是 [250, 80, 250, 250, 250, 250]
        # coarse_step = 4
        # 轴 0 (弯曲轴): 从 140 往 250 释放，方向 open_dir = +1
        # 滴答一次，轴 0 目标应该变为 144
        self.controller._on_tick()
        self.assertEqual(self.controller.current_targets[0], 148)
        self.assertEqual(self.controller.state, GraspState.RELEASING)
        
        # 滴答多次直到完全释放到 250 以上
        ticks = 0
        while self.controller.state == GraspState.RELEASING and ticks < 100:
            self.controller._on_tick()
            ticks += 1
            
        # 完全释放后应当重置回 IDLE
        self.assertEqual(self.controller.state, GraspState.IDLE)
        self.assertEqual(ui_state.snapshot.action, ActionState.IDLE)

    def test_freeze_non_confirmed_joints_on_preloading(self):
        """测试在进入 PRELOADING 时，未确认接触的动作关节被自动冻结（FROZEN）。"""
        self.controller.start_grasp("default_power_grasp_o6")
        self.controller._start_control_loop()
        
        # 手动模拟关节状态：0, 2, 3 确认为 CONTACT_CONFIRMED，5 还是 CLOSING_FINE
        self.controller.joint_states[0] = GraspJointState.CONTACT_CONFIRMED
        self.controller.joint_states[2] = GraspJointState.CONTACT_CONFIRMED
        self.controller.joint_states[3] = GraspJointState.CONTACT_CONFIRMED
        self.controller.joint_states[5] = GraspJointState.CLOSING_FINE
        
        # 触发拓扑检查，应当满足拓扑切换至 PRELOADING 并冻结 5 号关节
        self.controller._check_closing_termination(time.time())
        self.assertEqual(self.controller.state, GraspState.PRELOADING)
        self.assertEqual(self.controller.joint_states[5], GraspJointState.FROZEN)


if __name__ == '__main__':
    unittest.main()
