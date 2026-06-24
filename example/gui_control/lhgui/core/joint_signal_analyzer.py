#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关节反馈信号分析器。

职责：
1. 维护每个关节的滑动历史窗口数据（包括目标位置、反馈位置和时间戳）。
2. 计算关节的跟踪误差、抖动值、目标进度及实际移动量。
3. 根据标定的阈值，输出 0.0-1.0 之间的接触判定评分。
4. 校验信号数据的合法性（非有限值、NaN、数据过期检测）。
"""
import time
from collections import deque
from typing import List, Tuple, Dict, Any


def math_std(values: List[float]) -> float:
    """计算列表的标准差（无偏估计）。"""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return variance ** 0.5


class JointSignalAnalyzer:
    def __init__(self, joint_index: int, closing_direction: int, window_size: int = 10):
        """
        :param joint_index: 关节索引
        :param closing_direction: 闭合方向 (1 或 -1)
        :param window_size: 滑动窗口最大长度
        """
        self.joint_index = joint_index
        self.closing_direction = closing_direction
        self.window_size = max(5, window_size)

        # 双端队列缓存：(timestamp, actual_position, target_position)
        self.history = deque(maxlen=self.window_size)

        # 实时检测特征值
        self.latest_actual = 0.0
        self.latest_target = 0.0
        self.latest_timestamp = 0.0
        
        self.position_error = 0.0
        self.actual_progress = 0.0
        self.command_progress = 0.0
        self.jitter_value = 0.0
        
        # 默认判断阈值（在未加载标定时做为保守兜底）
        self.error_threshold = 15.0
        self.jitter_threshold = 2.0
        self.movement_threshold = 2.0

    def update_thresholds(self, error_th: float, jitter_th: float, movement_th: float):
        """更新分析器的检测阈值（通常在标定或加载配置时调用）。"""
        self.error_threshold = max(5.0, error_th)
        self.jitter_threshold = max(0.5, jitter_th)
        self.movement_threshold = max(0.5, movement_th)

    def update(self, actual_pos: float, target_pos: float, timestamp: float):
        """塞入最新的采样点并更新所有物理指标。"""
        # 数据合法性校验
        try:
            actual_pos = float(actual_pos)
            target_pos = float(target_pos)
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            return

        import math
        if not math.isfinite(actual_pos) or not math.isfinite(target_pos) or not math.isfinite(timestamp):
            return

        self.latest_actual = actual_pos
        self.latest_target = target_pos
        self.latest_timestamp = timestamp

        self.history.append((timestamp, actual_pos, target_pos))
        self._calculate_features()

    def _calculate_features(self):
        """核心特征计算：位置误差、一阶位移、二阶差分抖动。"""
        if not self.history:
            return

        # 1. 跟踪误差
        self.position_error = abs(self.latest_target - self.latest_actual)

        n = len(self.history)
        if n < 2:
            self.actual_progress = 0.0
            self.command_progress = 0.0
            self.jitter_value = 0.0
            return

        # 2. 闭合进度量（采用 200ms/4帧 的短窗口以提高停滞检测的灵敏度）
        short_w = min(4, n)
        old_item = self.history[-short_w]
        # target_now - target_old
        self.command_progress = self.latest_target - old_item[2]
        # actual_now - actual_old
        self.actual_progress = self.latest_actual - old_item[1]

        # 3. 高频抖动值（去趋势残差标准差，用二阶差分的标准差来表示）
        if n >= 3:
            # 计算一阶差分
            diff1 = []
            for i in range(1, n):
                diff1.append(self.history[i][1] - self.history[i-1][1])
            # 计算二阶差分
            diff2 = []
            for i in range(1, len(diff1)):
                diff2.append(diff1[i] - diff1[i-1])
            # 求标准差作为抖动能量指标
            self.jitter_value = math_std(diff2)
        else:
            self.jitter_value = 0.0

    def is_expired(self, current_time: float, timeout_ms: float = 300.0) -> bool:
        """检查数据是否过期。"""
        if not self.history:
            return True
        age_ms = (current_time - self.latest_timestamp) * 1000.0
        return age_ms > timeout_ms

    def calculate_contact_score(self) -> float:
        """根据跟踪误差、停滞、抖动特征，计算接触综合得分 (0.0 - 1.0)。"""
        if len(self.history) < 5:
            # 数据点太少时，判定为 0 分
            return 0.0

        # 计算即时停滞（使用滑动历史中最近 3 个点，约 100-150ms 窗口，计算其实际位移最大跨度）
        instant_stall = False
        if len(self.history) >= 3:
            recent_actuals = [self.history[-i][1] for i in range(1, 4)]
            span = max(recent_actuals) - min(recent_actuals)
            # 如果最近 3 个点的实际位置波动的最大跨度小于 1.0 且目标相较实际更靠前
            # 2.0 代表指令领先实际至少 2 个单位，表明电机确实在出力压紧
            pos_lead = (self.latest_target - self.latest_actual) * self.closing_direction
            if span < 1.0 and pos_lead >= 2.0:
                instant_stall = True

        # 一、停滞判定得分 Stall Score
        if instant_stall:
            stall_score = 1.0
        else:
            # 回退到传统的滑动窗口位移差检测作为备用
            command_moved = self.command_progress * self.closing_direction
            actual_moved = self.actual_progress * self.closing_direction
            if command_moved > 3.0 and actual_moved < self.movement_threshold:
                stall_score = 1.0
            else:
                stall_score = 0.0

        # 二、跟踪误差得分 Error Score
        # 超出阈值即为 1.0，线性平滑
        error_score = min(1.0, self.position_error / self.error_threshold)

        # 三、抖动得分 Jitter Score
        jitter_score = min(1.0, self.jitter_value / self.jitter_threshold)

        # 权重分配：增大停滞权重以实现轻触即停灵敏抓握 (停滞70% + 误差20% + 抖动10%)
        w_stall = 0.7
        w_error = 0.2
        w_jitter = 0.1

        score = w_stall * stall_score + w_error * error_score + w_jitter * jitter_score
        return score
