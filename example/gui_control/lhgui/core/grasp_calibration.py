#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空载标定数据管理器。

职责：
1. 从用户配置目录加载/保存空载标定配置文件。
2. 标定结果区分型号、左右手和固件版本。
3. 根据标定数据为各关节自动生成位置误差和高频抖动判断阈值。
"""
import os
import yaml
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass
class JointCalibrationData:
    joint_index: int
    error_threshold: float
    jitter_threshold: float
    movement_threshold: float = 2.0


@dataclass
class HandCalibrationData:
    hand_model: str
    hand_type: str
    firmware_version: str
    joints: List[JointCalibrationData]


class GraspCalibrationManager:
    def __init__(self):
        self.config_dir = os.path.expanduser("~/.gemini/antigravity")
        self.calib_path = os.path.join(self.config_dir, "grasp_calibration.yaml")
        self.calibrations: Dict[str, HandCalibrationData] = {}
        self.load_calibrations()

    def _get_key(self, hand_model: str, hand_type: str, firmware_version: str) -> str:
        ver = firmware_version or "unknown"
        return f"{hand_model}_{hand_type}_{ver}".lower()

    def load_calibrations(self):
        """从持久化文件载入标定数据。"""
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir, exist_ok=True)
            except Exception as e:
                print(f"[GraspCalibrationManager] 创建配置目录失败: {e}")
                return

        if not os.path.exists(self.calib_path):
            return

        try:
            with open(self.calib_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "calibrations" in data:
                    for item in data["calibrations"]:
                        try:
                            # 提取 joints 并实例化
                            joints_list = []
                            for j_data in item["joints"]:
                                joints_list.append(JointCalibrationData(**j_data))
                            
                            c_data = HandCalibrationData(
                                hand_model=item["hand_model"],
                                hand_type=item["hand_type"],
                                firmware_version=item["firmware_version"],
                                joints=joints_list
                            )
                            key = self._get_key(c_data.hand_model, c_data.hand_type, c_data.firmware_version)
                            self.calibrations[key] = c_data
                        except Exception as ex:
                            print(f"[GraspCalibrationManager] 解析标定项失败: {ex}")
        except Exception as e:
            print(f"[GraspCalibrationManager] 读取标定文件失败: {e}")

    def is_calibrated(self, hand_model: str, hand_type: str, firmware_version: str) -> bool:
        """检查特定手部硬件是否已完成标定。"""
        key = self._get_key(hand_model, hand_type, firmware_version)
        return key in self.calibrations

    def get_calibration(self, hand_model: str, hand_type: str, firmware_version: str) -> Optional[HandCalibrationData]:
        """获取特定手部硬件的标定数据。"""
        key = self._get_key(hand_model, hand_type, firmware_version)
        return self.calibrations.get(key)

    def save_calibration(self, hand_model: str, hand_type: str, firmware_version: str, joints: List[JointCalibrationData]):
        """保存标定数据并写入 YAML。"""
        c_data = HandCalibrationData(
            hand_model=hand_model,
            hand_type=hand_type,
            firmware_version=firmware_version or "unknown",
            joints=joints
        )
        key = self._get_key(hand_model, hand_type, firmware_version)
        self.calibrations[key] = c_data

        # 写入文件
        serialized = []
        for item in self.calibrations.values():
            serialized.append({
                "hand_model": item.hand_model,
                "hand_type": item.hand_type,
                "firmware_version": item.firmware_version,
                "joints": [asdict(j) for j in item.joints]
            })
        
        data = {"version": 1, "calibrations": serialized}
        try:
            with open(self.calib_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True)
        except Exception as e:
            print(f"[GraspCalibrationManager] 保存标定配置文件失败: {e}")

    def calculate_and_save(self, hand_model: str, hand_type: str, firmware_version: str,
                           errors_by_joint: Dict[int, List[float]], jitters_by_joint: Dict[int, List[float]]):
        """核心阈值计算逻辑。
        
        根据标定运行期间采集的最大误差和抖动，施加安全裕度因子生成阈值，并保存。
        """
        # 参数因子
        error_factor = 1.5
        error_min_offset = 8.0
        
        jitter_factor = 2.0
        jitter_min_offset = 0.5

        joints = []
        for idx in errors_by_joint.keys():
            errs = errors_by_joint.get(idx, [])
            jits = jitters_by_joint.get(idx, [])

            max_err = max(errs) if errs else 5.0
            max_jit = max(jits) if jits else 0.2

            # 计算阈值
            err_th = max_err * error_factor + error_min_offset
            jit_th = max_jit * jitter_factor + jitter_min_offset

            # 设定保护性下限
            err_th = max(10.0, err_th)
            jit_th = max(1.0, jit_th)

            joints.append(JointCalibrationData(
                joint_index=idx,
                error_threshold=err_th,
                jitter_threshold=jit_th,
                movement_threshold=2.0
            ))

        self.save_calibration(hand_model, hand_type, firmware_version, joints)


# 单例
grasp_calibration_manager = GraspCalibrationManager()
