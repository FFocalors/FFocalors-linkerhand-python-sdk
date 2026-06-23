#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时关节反馈状态的本地安全缓存组件。

避免直接让 SignalBus 充当状态持有者，提供线程安全且带生命周期（DPR/TTL）的状态快照。
"""
import time
import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class JointStateSnapshot:
    hand_model: str
    values: Tuple[float, ...]
    timestamp: float


class JointStateCache:
    def __init__(self):
        self._snapshots = {}  # hand_model -> JointStateSnapshot

    def update(self, hand_model: str, values: list):
        """缓存并验证最新的关节状态，过滤一切非法或越界数据。"""
        if not hand_model:
            return
        
        # 延迟导入以防止循环依赖
        from lhgui.config.constants import HAND_CONFIGS
        if hand_model not in HAND_CONFIGS:
            return
            
        config = HAND_CONFIGS[hand_model]
        expected_len = len(config.init_pos)
        
        # 1. 数量检查
        if not isinstance(values, (list, tuple)) or len(values) < expected_len:
            return
            
        vals = values[:expected_len]
        
        # 2. 类型、NaN、Infinity、关节范围检查（范围采用配置为准，默认0-255）
        checked_vals = []
        for v in vals:
            try:
                n = float(v)
            except (TypeError, ValueError):
                return
            if not math.isfinite(n):
                return
            # 默认关节控制范围在 0.0 到 255.0 之间
            if not (0.0 <= n <= 255.0):
                return
            checked_vals.append(n)
            
        # 3. 创建不可变副本快照
        self._snapshots[hand_model] = JointStateSnapshot(
            hand_model=hand_model,
            values=tuple(checked_vals),
            timestamp=time.time()
        )

    def latest(self, hand_model: str = None) -> Optional[JointStateSnapshot]:
        """获取指定手型的最新状态快照副本。"""
        if hand_model is None:
            return None
        return self._snapshots.get(hand_model)

    def is_fresh(self, hand_model: str, max_age_seconds: float = 3.0) -> bool:
        """检查指定手型的快照数据是否依然鲜活且未过期。"""
        snapshot = self.latest(hand_model)
        if snapshot is None:
            return False
        return (time.time() - snapshot.timestamp) <= max_age_seconds

    def clear(self):
        self._snapshots.clear()


# 全局单例
joint_state_cache = JointStateCache()
