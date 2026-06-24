#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应抓取配置 Profile 管理器。

定义抓取参数、动作预置、限位及自适应闭合参数的 Profile 结构，
并支持 YAML 持久化读写。
"""
import os
import yaml
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional


@dataclass
class GraspProfile:
    id: str
    name: str
    hand_model: str
    pregrasp: List[int]                 # 预抓取各关节初始目标
    close_limits: List[int]             # 抓取各关节安全闭合极限边界
    coarse_step: int = 6                # 粗闭合步长
    fine_step: int = 1                  # 精细闭合步长
    interval_ms: int = 50               # 控制循环定时器周期 (ms)
    timeout_ms: int = 5000              # 整体抓取超时时间 (ms)
    window_ms: int = 300                # 分析器滑动窗口跨度 (ms)
    stall_confirm_ms: int = 250         # 停滞检测确认时间 (ms)
    confirmation_windows: int = 3       # 连续多少个控制周期满足接触候选即确认接触
    score_threshold: float = 0.65       # 接触判定综合评分阈值
    thumb_required: bool = True         # 是否必须大拇指接触
    minimum_finger_contacts: int = 2    # 除大拇指外，最少需要多少个手指接触
    preload_step: int = 1               # 预紧时的步进追加量
    maximum_preload_steps: int = 1      # 最大预紧追加次数
    verify_ms: int = 800                # 抓取完成后稳定性验证保持时间 (ms)
    data_timeout_ms: int = 300          # 关节反馈数据过期判定阈值 (ms)


# 默认 Profile 出厂模板
_DEFAULT_PROFILES = [
    GraspProfile(
        id="default_power_grasp_o6",
        name="默认包络抓取 (O6)",
        hand_model="O6",
        pregrasp=[250, 80, 250, 250, 250, 250],
        close_limits=[20, 80, 10, 10, 10, 10],
        coarse_step=6,
        fine_step=1,
        interval_ms=50,
        timeout_ms=5000,
        score_threshold=0.65,
        thumb_required=True,
        minimum_finger_contacts=2,
        preload_step=1,
        maximum_preload_steps=1,
        verify_ms=800,
    ),
    GraspProfile(
        id="default_power_grasp_l6",
        name="默认包络抓取 (L6)",
        hand_model="L6",
        pregrasp=[250, 40, 250, 250, 250, 250],
        close_limits=[20, 40, 10, 10, 10, 10],
        coarse_step=6,
        fine_step=1,
        interval_ms=50,
        timeout_ms=5000,
        score_threshold=0.65,
        thumb_required=True,
        minimum_finger_contacts=2,
        preload_step=1,
        maximum_preload_steps=1,
        verify_ms=800,
    ),
    GraspProfile(
        id="default_power_grasp_l7",
        name="默认包络抓取 (L7)",
        hand_model="L7",
        pregrasp=[250, 15, 250, 250, 250, 250, 170],
        close_limits=[40, 15, 20, 20, 20, 20, 170],
        coarse_step=6,
        fine_step=1,
        interval_ms=50,
        timeout_ms=5000,
        score_threshold=0.65,
        thumb_required=True,
        minimum_finger_contacts=2,
        preload_step=1,
        maximum_preload_steps=1,
        verify_ms=800,
    ),
    GraspProfile(
        id="default_power_grasp_l10",
        name="默认包络抓取 (L10)",
        hand_model="L10",
        pregrasp=[255, 255, 255, 255, 255, 255, 128, 67, 89, 255],
        close_limits=[90, 255, 20, 20, 20, 20, 128, 67, 89, 255],
        coarse_step=6,
        fine_step=1,
        interval_ms=50,
        timeout_ms=5000,
        score_threshold=0.65,
        thumb_required=True,
        minimum_finger_contacts=2,
        preload_step=1,
        maximum_preload_steps=1,
        verify_ms=800,
    ),
    GraspProfile(
        id="default_power_grasp_l20",
        name="默认包络抓取 (L20)",
        hand_model="L20",
        pregrasp=[255, 255, 255, 255, 255, 255, 10, 100, 180, 240, 245, 255, 255, 255, 255, 255, 255, 255, 255, 255],
        close_limits=[40, 20, 20, 20, 20, 255, 10, 100, 180, 240, 130, 255, 255, 255, 255, 135, 20, 20, 20, 20],
        coarse_step=6,
        fine_step=1,
        interval_ms=50,
        timeout_ms=5000,
        score_threshold=0.65,
        thumb_required=True,
        minimum_finger_contacts=2,
        preload_step=1,
        maximum_preload_steps=1,
        verify_ms=800,
    ),
]


class GraspProfileManager:
    def __init__(self):
        self.config_dir = os.path.expanduser("~/.gemini/antigravity")
        self.profile_path = os.path.join(self.config_dir, "grasp_profiles.yaml")
        self.profiles: Dict[str, GraspProfile] = {}
        self.load_profiles()

    def load_profiles(self):
        """从用户配置目录载入 Profile，如果不存在则自动创建默认模板。"""
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir, exist_ok=True)
            except Exception as e:
                print(f"[GraspProfileManager] 创建配置目录失败: {e}")

        if not os.path.exists(self.profile_path):
            # 初始化默认文件
            data = {"version": 1, "profiles": [asdict(p) for p in _DEFAULT_PROFILES]}
            try:
                with open(self.profile_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, allow_unicode=True)
            except Exception as e:
                print(f"[GraspProfileManager] 写入默认配置模板失败: {e}")

        # 读取
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "profiles" in data:
                    for item in data["profiles"]:
                        try:
                            p = GraspProfile(**item)
                            self.profiles[p.id] = p
                        except Exception as ex:
                            print(f"[GraspProfileManager] 解析 Profile {item.get('id')} 发生异常: {ex}")
        except Exception as e:
            print(f"[GraspProfileManager] 读取配置文件失败: {e}")
            # 备用内存加载
            for p in _DEFAULT_PROFILES:
                self.profiles[p.id] = p

    def get_profiles_for_model(self, hand_model: str) -> List[GraspProfile]:
        """获取适用于特定型号的所有配置。"""
        return [p for p in self.profiles.values() if p.hand_model == hand_model]

    def get_profile(self, profile_id: str) -> Optional[GraspProfile]:
        """获取特定 ID 的配置。"""
        return self.profiles.get(profile_id)

    def save_profile(self, profile: GraspProfile):
        """保存或更新单个配置并持久化。"""
        self.profiles[profile.id] = profile
        data = {"version": 1, "profiles": [asdict(p) for p in self.profiles.values()]}
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True)
        except Exception as e:
            print(f"[GraspProfileManager] 写入配置失败: {e}")


# 单例
grasp_profile_manager = GraspProfileManager()
