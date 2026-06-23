#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新增预设管理、状态缓存和安全补位特性的自动化单元测试。"""
import os
import sys
import tempfile
import time
import shutil
import math
import unittest

# 确保导入可用
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)
parent_dir = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# 动态寻找 PyQt5 的 Qt 平台插件路径，解决 QPA 初始化失败的 Windows 环境问题
try:
    import PyQt5
    pyqt_dir = os.path.dirname(PyQt5.__file__)
    plugins_dir = os.path.join(pyqt_dir, "Qt5", "plugins")
    if os.path.exists(plugins_dir):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugins_dir
except Exception:
    pass

from PyQt5.QtWidgets import QApplication
from lhgui.core.custom_preset_store import CustomPresetStore, CustomPreset
from lhgui.core.joint_state_cache import JointStateCache, JointStateSnapshot
from lhgui.core.action_executor import ActionExecutor
from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState, ActionState


class TestCustomPresetStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.store = CustomPresetStore(config_dir_override=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_config(self):
        self.store.load_all()
        self.assertEqual(len(self.store.list_for_model("L6")), 0)

    def test_save_and_load(self):
        preset = CustomPreset(
            id="custom_test_001",
            name="测试预设",
            category="custom",
            hand_model="L6",
            values=(250, 250, 100, 100, 100, 100),
            created_at="2026-06-22T12:00:00+08:00"
        )
        self.store.add(preset)
        
        # 重新加载
        new_store = CustomPresetStore(config_dir_override=self.test_dir)
        loaded = new_store.list_for_model("L6")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "custom_test_001")
        self.assertEqual(loaded[0].name, "测试预设")
        self.assertEqual(loaded[0].values, (250, 250, 100, 100, 100, 100))

    def test_remove_preset(self):
        preset = CustomPreset(
            id="custom_test_001",
            name="测试预设",
            category="custom",
            hand_model="L6",
            values=(250, 250, 100, 100, 100, 100),
            created_at="2026-06-22T12:00:00+08:00"
        )
        self.store.add(preset)
        self.assertTrue(self.store.remove("custom_test_001"))
        self.assertFalse(self.store.remove("non_exist_id"))
        self.assertEqual(len(self.store.list_for_model("L6")), 0)

    def test_name_exists(self):
        preset = CustomPreset(
            id="custom_test_001",
            name="测试预设",
            category="custom",
            hand_model="L6",
            values=(250, 250, 100, 100, 100, 100),
            created_at="2026-06-22T12:00:00+08:00"
        )
        self.store.add(preset)
        self.assertTrue(self.store.exists_name("L6", " 测试预设 "))
        self.assertTrue(self.store.exists_name("L6", "测试预设"))
        self.assertFalse(self.store.exists_name("L6", "新名字"))
        
        # 内置名字检测
        self.assertTrue(self.store.exists_name("L6", "张开"))

    def test_corrupted_yaml_handling(self):
        # 强制写入损坏的 YAML
        with open(self.store.config_path, "w", encoding="utf-8") as f:
            f.write("models: { L6: [ { id: unclosed_bracket ")
            
        # 尝试加载，应该安全回退且生成备份
        self.store.load_all()
        self.assertEqual(len(self.store.list_for_model("L6")), 0)
        
        # 检查是否生成了 .corrupt 备份文件
        files = os.listdir(self.test_dir)
        corrupt_files = [f for f in files if "custom_presets.yaml.corrupt-" in f]
        self.assertEqual(len(corrupt_files), 1)

    def test_values_validation(self):
        # 带有非法 values (包含 NaN, Infinity, 越界)
        invalid_item = {
            "version": 1,
            "models": {
                "L6": [
                    {
                        "id": "invalid_001",
                        "name": "非法NaN",
                        "category": "custom",
                        "values": [250, float('nan'), 100, 100, 100, 100],
                        "created_at": "2026-06-22"
                    },
                    {
                        "id": "invalid_002",
                        "name": "越界负数",
                        "category": "custom",
                        "values": [250, -10, 100, 100, 100, 100],
                        "created_at": "2026-06-22"
                    }
                ]
            }
        }
        import yaml
        with open(self.store.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(invalid_item, f)
            
        self.store.load_all()
        # 两个非法预设都应该被安全过滤丢弃
        self.assertEqual(len(self.store.list_for_model("L6")), 0)


class TestJointStateCache(unittest.TestCase):
    def setUp(self):
        self.cache = JointStateCache()

    def test_valid_state(self):
        self.cache.update("L6", [250, 250, 100, 100, 100, 100])
        self.assertTrue(self.cache.is_fresh("L6", max_age_seconds=3.0))
        snapshot = self.cache.latest("L6")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.values, (250, 250, 100, 100, 100, 100))

    def test_invalid_state_filtering(self):
        # 数量不足
        self.cache.update("L6", [250, 250, 100])
        self.assertFalse(self.cache.is_fresh("L6"))
        
        # 越界 (0-255)
        self.cache.update("L6", [250, 250, 100, 100, 100, 256.0])
        self.assertFalse(self.cache.is_fresh("L6"))
        
        # NaN
        self.cache.update("L6", [250, 250, 100, float('nan'), 100, 100])
        self.assertFalse(self.cache.is_fresh("L6"))

    def test_state_expiration(self):
        self.cache.update("L6", [250, 250, 100, 100, 100, 100])
        # 瞬时新鲜
        self.assertTrue(self.cache.is_fresh("L6", max_age_seconds=1.0))
        # 模拟时间流逝或小 TTL
        self.assertFalse(self.cache.is_fresh("L6", max_age_seconds=-1.0))


class TestPresetSafetyPadding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.executor = ActionExecutor()

    def setUp(self):
        self.cache = JointStateCache()
        
        # 全局状态劫持
        ui_state.set_connection_state(ConnectionState.CONNECTED)
        ui_state.set_action_state(ActionState.IDLE)
        
        # 连接信号收集
        self.sent_positions = None
        signal_bus.finger_move_requested.connect(self._on_move)

    def tearDown(self):
        try:
            signal_bus.finger_move_requested.disconnect(self._on_move)
        except Exception:
            pass

    def _on_move(self, pos):
        self.sent_positions = pos

    def test_non_l6_padding(self):
        # 模拟 L10 (10 关节设备)
        from lhgui.core.api_manager import ApiManager
        class DummyApi:
            def __init__(self):
                self.hand_joint = "L10"
        ApiManager._instance = DummyApi()
        
        # 1. 注入 10 关节的最新鲜活硬件反馈
        from lhgui.core.joint_state_cache import joint_state_cache
        joint_state_cache.clear()
        joint_state_cache.update("L10", [240, 240, 90, 90, 90, 90, 80, 80, 80, 80])
        
        # 2. 模拟从 custom_preset_store 获取自定义预设 (ID 为 custom_l10_01)
        from lhgui.core.custom_preset_store import custom_preset_store
        preset = CustomPreset(
            id="custom_l10_01",
            name="自定义L10",
            category="custom",
            hand_model="L10",
            # 前 6 维是编辑过的
            values=(250, 250, 100, 100, 100, 100, 80, 80, 80, 80),
            created_at="2026-06-22"
        )
        custom_preset_store.add(preset)
        
        # 3. 实时硬件反馈变化：隐藏的后 4 维在物理上变成了 120, 120, 120, 120
        joint_state_cache.update("L10", [240, 240, 90, 90, 90, 90, 120, 120, 120, 120])
        
        # 4. 执行该自定义预设 (前 6 个编辑主要关节是 250, 250, 100, 100, 100, 100)
        # 执行前，ActionExecutor 应该根据最新的 [..., 120, 120, 120, 120] 实时反馈补全，防止隐藏关节误动！
        self.executor.execute("custom_l10_01", [250, 250, 100, 100, 100, 100])
        
        self.assertIsNotNone(self.sent_positions)
        self.assertEqual(len(self.sent_positions), 10)
        # 前 6 维是预设编辑的值
        self.assertEqual(list(self.sent_positions[:6]), [250, 250, 100, 100, 100, 100])
        # 后 4 维必须保持执行前当前的最新实时状态 120，而不是预设保存时的 80！
        self.assertEqual(list(self.sent_positions[6:]), [120, 120, 120, 120])

    def test_padding_refused_when_expired(self):
        # 模拟 L10 状态过期
        from lhgui.core.api_manager import ApiManager
        class DummyApi:
            def __init__(self):
                self.hand_joint = "L10"
        ApiManager._instance = DummyApi()
        
        from lhgui.core.joint_state_cache import joint_state_cache
        joint_state_cache.clear()
        
        self.sent_positions = None
        # 执行预设，因为没有鲜活状态反馈，应该被 ActionExecutor 拒绝执行
        self.executor.execute("custom_l10_01", [250, 250, 100, 100, 100, 100])
        self.assertIsNone(self.sent_positions)


if __name__ == "__main__":
    unittest.main()
