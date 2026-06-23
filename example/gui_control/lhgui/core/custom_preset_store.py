#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义动作预设数据持久化管理层。

支持多手型版本化配置、原子安全写入、损坏配置自动备份及以唯一 UUID 作为删除/定位主键。
"""
import os
import sys
import uuid
import datetime
import shutil
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import yaml

from PyQt5.QtCore import QStandardPaths

logger = logging.getLogger("CustomPresetStore")


@dataclass(frozen=True)
class CustomPreset:
    id: str
    name: str
    category: str
    hand_model: str
    values: tuple
    created_at: str
    editable_joint_indices: tuple = (0, 1, 2, 3, 4, 5)


class CustomPresetStore:
    def __init__(self, config_dir_override: str = None):
        if config_dir_override:
            self.config_dir = config_dir_override
        else:
            self.config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
            # 在某些多平台下，如果 writableLocation 为空，提供一个安全备用位置
            if not self.config_dir:
                self.config_dir = os.path.join(os.path.expanduser("~"), ".LinkerHandConsole")
        
        self.config_path = os.path.join(self.config_dir, "custom_presets.yaml")
        self._presets: Dict[str, List[CustomPreset]] = {}  # hand_model -> list of CustomPreset
        self._ensure_dir()
        self.load_all()

    def _ensure_dir(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"无法创建用户配置目录: {e}")

    def load_all(self) -> dict:
        """加载本地 YAML 数据。如果文件损坏，自动备份为 corrupt，内存中使用空结构启动。"""
        self._presets.clear()
        if not os.path.exists(self.config_path):
            return {}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"配置文件损坏，无法加载 YAML: {e}")
            self._backup_corrupted_file()
            return {}

        if not isinstance(data, dict):
            logger.error("配置文件根节点必须是 dict，格式错误！")
            self._backup_corrupted_file()
            return {}

        # 检查版本（如果遇到未来高版本，提示并忽略）
        ver = data.get("version", 1)
        if ver > 1:
            logger.warning(f"检测到未来配置文件版本 {ver}，可能不支持部分结构，尝试读取。")

        models_data = data.get("models", {})
        if not isinstance(models_data, dict):
            logger.error("配置文件 models 必须为字典。")
            self._backup_corrupted_file()
            return {}

        # 逐个模型解析
        for hand_model, presets_list in models_data.items():
            if not isinstance(presets_list, list):
                continue
            valid_list = []
            for item in presets_list:
                if not isinstance(item, dict):
                    continue
                p_id = item.get("id")
                name = item.get("name")
                values = item.get("values")
                
                # 校验必要字段
                if not p_id or not name or not isinstance(values, list):
                    continue
                    
                # 校验 values 的合法性（去除任何可能包含 NaN/Infinity 的非法数值）
                import math
                valid_values = []
                has_invalid = False
                for v in values:
                    try:
                        n = float(v)
                    except (TypeError, ValueError):
                        has_invalid = True
                        break
                    if not math.isfinite(n) or not (0.0 <= n <= 255.0):
                        has_invalid = True
                        break
                    valid_values.append(int(round(n)))
                if has_invalid:
                    continue

                category = item.get("category", "custom")
                created_at = item.get("created_at", "")
                editable_idx = item.get("editable_joint_indices", [0, 1, 2, 3, 4, 5])

                preset = CustomPreset(
                    id=str(p_id),
                    name=str(name),
                    category=str(category),
                    hand_model=str(hand_model),
                    values=tuple(valid_values),
                    created_at=str(created_at),
                    editable_joint_indices=tuple(editable_idx)
                )
                valid_list.append(preset)
            self._presets[hand_model] = valid_list

        return self._presets

    def _backup_corrupted_file(self):
        """将损坏的文件备份，防止直接覆盖丢失用户手势。"""
        if not os.path.exists(self.config_path):
            return
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{self.config_path}.corrupt-{ts}"
        try:
            shutil.copy2(self.config_path, backup_path)
            logger.info(f"已将损坏的配置文件备份到: {backup_path}")
            # 删掉损坏的，以便后面重新写入，但保留了备份
            os.remove(self.config_path)
        except Exception as e:
            logger.error(f"备份损坏配置文件失败: {e}")

    def list_for_model(self, hand_model: str) -> List[CustomPreset]:
        return self._presets.get(hand_model, [])

    def exists_name(self, hand_model: str, name: str) -> bool:
        """检查同型号下是否重名（不敏感比对，防止 Unicode 表达差异）。"""
        import unicodedata
        normalized_name = unicodedata.normalize("NFKC", name).strip().lower()
        
        # 内置预设也防重名
        from lhgui.config.constants import HAND_CONFIGS
        if hand_model in HAND_CONFIGS:
            builtins = HAND_CONFIGS[hand_model].preset_actions or {}
            for k in builtins.keys():
                if unicodedata.normalize("NFKC", k).strip().lower() == normalized_name:
                    return True

        for p in self.list_for_model(hand_model):
            if unicodedata.normalize("NFKC", p.name).strip().lower() == normalized_name:
                return True
        return False

    def get(self, preset_id: str) -> Optional[CustomPreset]:
        for lst in self._presets.values():
            for p in lst:
                if p.id == preset_id:
                    return p
        return None

    def add(self, preset: CustomPreset):
        """添加新预设并持久化。"""
        lst = self._presets.setdefault(preset.hand_model, [])
        # 移除已有相同 ID
        lst = [p for p in lst if p.id != preset.id]
        lst.append(preset)
        self._presets[preset.hand_model] = lst
        self._save_to_disk()

    def remove(self, preset_id: str) -> bool:
        """根据 ID 移除预设。"""
        found = False
        for hand_model, lst in self._presets.items():
            filtered = [p for p in lst if p.id != preset_id]
            if len(filtered) != len(lst):
                self._presets[hand_model] = filtered
                found = True
                break
        if found:
            self._save_to_disk()
        return found

    def _save_to_disk(self):
        """原子写入 YAML，防损坏。"""
        self._ensure_dir()
        data = {
            "version": 1,
            "models": {}
        }
        for hand_model, lst in self._presets.items():
            model_presets = []
            for p in lst:
                d = asdict(p)
                # 转换 tuple 方便写入 yaml 数组
                d["values"] = list(p.values)
                d["editable_joint_indices"] = list(p.editable_joint_indices)
                model_presets.append(d)
            data["models"][hand_model] = model_presets

        tmp_path = self.config_path + ".tmp"
        try:
            # 显式 UTF-8 写入
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
                f.flush()
                # 尝试强制同步磁盘数据
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            # 原子替换
            os.replace(tmp_path, self.config_path)
        except Exception as e:
            logger.error(f"原子写入自定义预设失败: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise IOError(f"无法保存自定义预设文件: {e}")


# 全局单例
custom_preset_store = CustomPresetStore()
