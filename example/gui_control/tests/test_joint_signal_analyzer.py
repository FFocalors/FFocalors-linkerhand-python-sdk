#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关节信号分析器单元测试。

测试场景：
1. 匀速跟随：无停滞、无高频抖动、无大误差 -> 评分接近 0。
2. 物理受阻（停滞）：目标一直改变，反馈不动，误差增大 -> 评分逼近 1.0。
3. 异常抖动：高频波动标准差大 -> 评分增高。
4. 脏数据防护：包含 NaN, Infinity, 异常类型。
5. 过期校验：时间戳差值大。
"""
import unittest
import math
import sys
import os

# 把项目根目录加进 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lhgui.core.joint_signal_analyzer import JointSignalAnalyzer, math_std


class TestJointSignalAnalyzer(unittest.TestCase):
    def setUp(self):
        # 建立一个闭合负方向(-1)的分析器（数值减小为闭合）
        self.analyzer = JointSignalAnalyzer(joint_index=0, closing_direction=-1, window_size=10)
        # 设置默认标定阈值
        self.analyzer.update_thresholds(error_th=10.0, jitter_th=2.0, movement_th=2.0)

    def test_math_std(self):
        self.assertAlmostEqual(math_std([1, 2, 3]), 1.0)
        self.assertAlmostEqual(math_std([1, 1, 1]), 0.0)
        self.assertEqual(math_std([5]), 0.0)
        self.assertEqual(math_std([]), 0.0)

    def test_normal_following(self):
        """匀速跟随运动。"""
        t = 0.0
        pos = 250.0
        # 10帧的正常运动，误差为 1 左右
        for _ in range(10):
            self.analyzer.update(actual_pos=pos + 1.0, target_pos=pos, timestamp=t)
            t += 0.05
            pos -= 4.0  # 向闭合方向移动
        
        score = self.analyzer.calculate_contact_score()
        # 正常跟随下，误差小，无停滞无抖动，接触得分应非常低
        self.assertLess(score, 0.4)

    def test_stalled_contact(self):
        """物理阻碍导致关节停滞。"""
        t = 0.0
        pos_act = 200.0
        pos_cmd = 200.0

        # 前 5 帧正常跟随
        for _ in range(5):
            self.analyzer.update(actual_pos=pos_act, target_pos=pos_cmd, timestamp=t)
            t += 0.05
            pos_act -= 4.0
            pos_cmd -= 4.0
        
        # 后面 5 帧发生阻碍：实际关节不再改变，但控制指令仍在前移
        for _ in range(5):
            self.analyzer.update(actual_pos=pos_act, target_pos=pos_cmd, timestamp=t)
            t += 0.05
            pos_cmd -= 4.0

        score = self.analyzer.calculate_contact_score()
        # 控制指令在推进，实际关节停滞，且误差越来越大，接触得分应当超过 0.75 阈值
        self.assertGreater(score, 0.75)

    def test_jitter_detection(self):
        """模拟高频抖动干扰。"""
        t = 0.0
        # 实际位置发生高频正负剧烈振荡
        actuals = [150.0, 153.0, 147.0, 155.0, 145.0, 156.0, 144.0, 157.0, 143.0, 158.0]
        targets = [150.0] * 10

        for act, trg in zip(actuals, targets):
            self.analyzer.update(actual_pos=act, target_pos=trg, timestamp=t)
            t += 0.05
        
        # 抖动值应当很高
        self.assertGreater(self.analyzer.jitter_value, 2.0)
        score = self.analyzer.calculate_contact_score()
        # 仅抖动评分拉高，应能在一定程度上体现在总分中
        self.assertGreater(score, 0.1)

    def test_dirty_data_handling(self):
        """检查对 NaN, Infinity 和过期数据的处理。"""
        t = 100.0
        # 注入 NaN/Infinity 应该直接被 update 拦截，不改变 history
        self.analyzer.update(actual_pos=float('nan'), target_pos=150.0, timestamp=t)
        self.assertEqual(len(self.analyzer.history), 0)

        self.analyzer.update(actual_pos=150.0, target_pos=float('inf'), timestamp=t)
        self.assertEqual(len(self.analyzer.history), 0)

        # 正常注入一帧
        self.analyzer.update(actual_pos=150.0, target_pos=150.0, timestamp=t)
        self.assertEqual(len(self.analyzer.history), 1)

        # 过期检测：如果最新数据是 100s 的，当前时间是 101s (相差 1s = 1000ms > 300ms)
        self.assertTrue(self.analyzer.is_expired(current_time=101.0, timeout_ms=300.0))
        # 在 100.1s 时，未过期
        self.assertFalse(self.analyzer.is_expired(current_time=100.1, timeout_ms=300.0))


if __name__ == '__main__':
    unittest.main()
