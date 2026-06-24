#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应抓取控制器的状态定义。

定义全局抓取状态机与单关节状态。
"""
from enum import Enum, auto


class GraspState(Enum):
    IDLE = auto()               # 空闲状态，未开始
    PREPARING = auto()          # 准备中（检查连接、型号、动作互斥、标定等）
    PREGRASP = auto()           # 预抓取姿态（拇指侧摆/横摆固定，其他手指就位）
    CLOSING_COARSE = auto()     # 快速接近（使用粗步长）
    CLOSING_FINE = auto()       # 精细逼近（检测到候选接触后，切换至细步长）
    FORMING_CONTACT = auto()    # 接触判定与单关节停止阶段
    PRELOADING = auto()         # 预紧阶段（多点接触满足后，施加小幅位置偏移）
    HOLDING = auto()            # 保持阶段
    VERIFYING = auto()          # 稳定性验证（监控漂移、丢接触和高频抖动）
    SUCCESS = auto()            # 抓取成功并保持
    CALIBRATING = auto()        # 空载标定中
    RELEASING = auto()          # 释放中（安全回缩到张开状态）
    FAILED = auto()             # 抓取失败（例如空抓、超时）
    ABORTED = auto()            # 异常中止（急停、数据过期、关节异常）


class GraspJointState(Enum):
    IDLE = auto()               # 空闲，不动作
    CLOSING_COARSE = auto()     # 快速接近（步长粗）
    CLOSING_FINE = auto()       # 精细逼近（步长细）
    CONTACT_CANDIDATE = auto()  # 疑似接触（达到局部接触评分）
    CONTACT_CONFIRMED = auto()  # 确认接触（连续窗口确认，目标位置被冻结在当前位置）
    FROZEN = auto()             # 冻结（已被强制固定在当前位置，不再改变）
    LIMIT_REACHED = auto()      # 运动到达了安全行程极限，未能发生接触
    ERROR = auto()              # 关节异常（跟踪误差过大、抖动过久或发生数值错误）
