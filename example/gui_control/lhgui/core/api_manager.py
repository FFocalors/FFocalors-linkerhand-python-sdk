#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手部 API 管理器。

职责：
1. 封装 LinkerHandApi 的生命周期——连接、断开、重连。
2. 连接失败不抛异常退出，改发信号通知 UI。
3. 把硬件指令（finger_move / set_speed / set_torque）转成对 API 的调用，
   并捕获一切异常，避免单次 CAN 失败拖垮整个界面。
4. 重连前主动回收旧实例（停接收线程 + 关 bus），防止 PCAN 通道占用。

不做的事：
- 不轮询实时数据（交给 core/data_source.py 在独立线程做）。
- 不录制回放（交给 core/recorder.py）。
"""
import threading
import traceback
from typing import Optional, List

from PyQt5.QtCore import QObject, pyqtSignal

from lhgui.utils.signal_bus import command_trace, sanitize_finger_pose, signal_bus
from lhgui.config.constants import HAND_CONFIGS
from LinkerHand.linker_hand_api import LinkerHandApi
from LinkerHand.utils.load_write_yaml import LoadWriteYaml


class ApiManager(QObject):
    _instance = None

    # 直接复用信号总线，额外补一个内部信号供 data_source 跟随生命周期
    api_ready = pyqtSignal(bool)   # True=可用, False=已断开

    def __init__(self):
        super().__init__()
        ApiManager._instance = self
        self.yaml = LoadWriteYaml()
        self.hand_joint: Optional[str] = None
        self.hand_type: Optional[str] = None
        self.is_touch: bool = False
        self.can: str = "PCAN_USBBUS1"
        self.modbus: str = "None"
        self.api: Optional[LinkerHandApi] = None
        self._lock = threading.Lock()
        self._connected = False
        self.saved_torque: Optional[List[int]] = None
        self._offline_mode = False
        self._consecutive_failures = 0

        self._read_config()
        self._wire_signals()

    # —— 配置 ——
    def _read_config(self):
        setting = self.yaml.load_setting_yaml()
        if not setting:
            signal_bus.connection_message.emit("error", "配置文件 setting.yaml 读取失败")
            return
        lh = setting["LINKER_HAND"]
        left = lh["LEFT_HAND"]
        right = lh["RIGHT_HAND"]
        # 与原 GUI 一致：双手都存在时优先左手
        if left["EXISTS"]:
            cfg = left
            self.hand_type = "left"
        elif right["EXISTS"]:
            cfg = right
            self.hand_type = "right"
        else:
            signal_bus.connection_message.emit("error", "setting.yaml 中左右手 EXISTS 均为 False")
            return
        self.hand_joint = cfg["JOINT"]
        self.is_touch = bool(cfg["TOUCH"])
        self.can = cfg["CAN"]
        self.modbus = cfg.get("MODBUS", "None")
        signal_bus.connection_message.emit(
            "info",
            f"当前配置：Linker Hand {self.hand_type} {self.hand_joint} "
            f"压感:{self.is_touch} modbus:{self.modbus} CAN:{self.can}",
        )
        command_trace(
            f"config hand_type={self.hand_type} hand_joint={self.hand_joint} "
            f"touch={self.is_touch} modbus={self.modbus} CAN={self.can}"
        )

    def _wire_signals(self):
        signal_bus.request_reconnect.connect(self.reconnect)
        signal_bus.finger_move_requested.connect(self.finger_move)
        signal_bus.speed_set_requested.connect(self.set_speed)
        signal_bus.torque_set_requested.connect(self.set_torque)

    # —— 连接管理 ——
    def connect(self):
        """首次连接（程序启动时调用）。失败不退出。"""
        if self.hand_joint is None:
            signal_bus.connection_changed.emit("error")
            return
        self._do_connect()

    def reconnect(self):
        """一键重连：先回收旧实例，再新建。"""
        signal_bus.connection_changed.emit("connecting")
        signal_bus.connection_message.emit("info", "正在重新连接…")
        self._dispose_api()
        self._do_connect()

    def _do_connect(self):
        signal_bus.connection_changed.emit("connecting")
        command_trace(
            f"connect start hand_type={self.hand_type} hand_joint={self.hand_joint} "
            f"modbus={self.modbus} CAN={self.can}"
        )
        with self._lock:
            api_instance = None
            version = None
            serial = None
            try:
                api_instance = LinkerHandApi(
                    hand_joint=self.hand_joint,
                    hand_type=self.hand_type,
                    modbus=self.modbus,
                    can=self.can,
                )
                
                # 初始化电机速度与扭矩（默认 255），避免手部固件默认状态为 0 导致不动
                try:
                    joint_count = len(HAND_CONFIGS[self.hand_joint].init_pos)
                    api_instance.set_speed([255] * joint_count)
                    api_instance.set_torque([255] * joint_count)
                except Exception as ex:
                    print(f"Failed to set initial speed/torque: {ex}")
                    
                # 校验物理硬件的真实在线可达性，读取版本与序列号，防范假在线
                try:
                    version = api_instance.get_embedded_version()
                    serial = api_instance.get_serial_number()
                except Exception as ex:
                    raise ConnectionError(f"读取设备参数失败: {ex}")
                
                if not version or serial in ("-1", "", None):
                    raise ConnectionError("未检测到有效的硬件版本或序列号，硬件可能未上电或未插入")
                
                self.api = api_instance
                self._connected = True
                self._offline_mode = False
                
                signal_bus.connection_changed.emit("connected")
                signal_bus.connection_message.emit("success", "已连接设备")
                command_trace(f"connect success version={version!r} serial={serial!r}")
            except Exception as e:
                command_trace(f"connect failed: {traceback.format_exc().strip()}")
                # 物理连接失败，若有 api_instance 必须彻底清理以释放 CAN 端口和线程！
                if api_instance is not None:
                    self.api = api_instance
                    self._dispose_api()
                
                self.api = None
                self._connected = False
                self._offline_mode = True
                
                config = HAND_CONFIGS.get(self.hand_joint)
                self._virtual_pose = list(config.init_pos) if config else [250] * 6
                
                signal_bus.connection_changed.emit("offline")
                signal_bus.connection_message.emit(
                    "warning", f"物理连接失败：{e}。已自动切入虚拟/离线调试模式。"
                )
                version = "Virtual"
                serial = "Virtual-Mode"
                command_trace("offline mode active; hardware commands will be skipped")

        signal_bus.hand_info_ready.emit({
            "hand_type": self.hand_type,
            "hand_joint": self.hand_joint,
            "is_touch": self.is_touch,
            "version": version,
            "serial": serial,
            "joint_count": len(HAND_CONFIGS[self.hand_joint].joint_names),
        })
        self.api_ready.emit(bool(self._connected and self.api is not None))

    def _dispose_api(self):
        """回收旧实例：停接收线程、关 bus。Windows 下 close_can 为空操作，需手动处理。"""
        api = self.api
        self.api = None
        self._connected = False
        self._offline_mode = False
        self.api_ready.emit(False)
        if api is None:
            return
        # 停底层接收线程
        hand = getattr(api, "hand", None)
        if hand is not None:
            try:
                hand.running = False
            except Exception:
                pass
            bus = getattr(hand, "bus", None)
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
        # Linux 下还有 open_can 需要关
        try:
            api.close_can()
        except Exception:
            pass

    def disconnect(self):
        self._dispose_api()
        signal_bus.connection_changed.emit("disconnected")
        signal_bus.connection_message.emit("info", "已断开连接")

    def shutdown(self):
        self._dispose_api()

    # —— 指令封装（捕获异常，失败只报错不崩） ——
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    def finger_move(self, pose: List[int]):
        expected_len = len(HAND_CONFIGS[self.hand_joint].init_pos) if self.hand_joint in HAND_CONFIGS else None
        command_trace(f"ApiManager received finger_move pose={pose!r}")
        safe_pose, changed, reason = sanitize_finger_pose(pose, expected_len=expected_len)
        if safe_pose is None:
            command_trace(f"invalid pose: {reason}; raw={pose!r}")
            signal_bus.connection_message.emit("error", f"非法关节位置，已忽略：{reason}")
            return
        if changed:
            command_trace(f"pose sanitized in ApiManager: raw={pose!r} safe={safe_pose}")
        # 虚拟/离线模式：直接向界面广播反馈，模拟手指运动
        if self._offline_mode and self.api is None:
            command_trace(f"skipped because demo/offline mode pose={safe_pose}")
            self._virtual_pose = list(safe_pose)
            signal_bus.joint_state_updated.emit(safe_pose)
            signal_bus.connection_message.emit("warning", "当前为离线调试模式，指令未下发到真实机械手")
            return
            
        if not self._ensure_api():
            return
        try:
            command_trace(f"calling api.finger_move pose={safe_pose}")
            result = self.api.finger_move(safe_pose)
            command_trace(f"api.finger_move returned: {result!r}")
            signal_bus.connection_message.emit("info", f"已发送关节位置: {safe_pose}")
        except Exception as e:
            command_trace(f"api.finger_move failed: {traceback.format_exc().strip()}")
            signal_bus.connection_message.emit("error", f"发送关节位置失败：{e}")

    def set_speed(self, speed: List[int]):
        if self._connected and self.api is None:
            return
        if not self._ensure_api():
            return
        try:
            self.api.set_speed(speed)
        except Exception as e:
            signal_bus.connection_message.emit("error", f"设置速度失败：{e}")

    def set_torque(self, torque: List[int]):
        self.saved_torque = list(torque)
        
        if self._connected and self.api is None:
            return
        if not self._ensure_api():
            return
        try:
            self.api.set_torque(torque)
        except Exception as e:
            signal_bus.connection_message.emit("error", f"设置扭矩失败：{e}")

    def set_temporary_torque(self, torque: List[int]):
        """在自适应抓握开始时临时限矩，不污染用户备份设定的全局扭矩。"""
        if self.saved_torque is None:
            self.saved_torque = [255] * len(torque)
        
        if self._connected and self.api is None:
            return
        if not self._ensure_api(silent=True):
            return
        try:
            self.api.set_torque(torque)
        except Exception:
            pass

    def restore_saved_torque(self):
        """退出自适应控制时，恢复先前设定的主界面全局扭矩。"""
        if self.saved_torque is None or (self._connected and self.api is None):
            return
        if not self._ensure_api(silent=True):
            return
        try:
            self.api.set_torque(self.saved_torque)
        except Exception:
            pass

    def _ensure_api(self, silent: bool = False) -> bool:
        if self.api is None or not self._connected:
            if not silent:
                signal_bus.connection_message.emit("warning", "设备未连接，操作被忽略")
            if self._offline_mode:
                command_trace("skipped because demo/offline mode")
            else:
                command_trace("skipped because api not connected")
            return False
        return True

    # —— 数据读取（供 data_source 在工作线程调用） ——
    def get_state(self):
        if not self._ensure_api(silent=True):
            # 虚拟/离线模式下，也可以给数据源提供默认全为 250 的虚拟快照以用于初始显示
            if self._connected:
                if not hasattr(self, "_virtual_pose") or not self._virtual_pose:
                    config = HAND_CONFIGS.get(self.hand_joint)
                    self._virtual_pose = list(config.init_pos) if config else [250] * 6
                
                return self._virtual_pose
            return None
        try:
            val = self.api.get_state()
            if val is not None:
                self._consecutive_failures = 0
                return val
            else:
                raise ValueError("Returned empty state")
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 5:
                self._consecutive_failures = 0
                self._handle_physical_disconnect(str(e))
            return None

    def _handle_physical_disconnect(self, reason: str):
        if not self._connected or self.api is None:
            return
        self._dispose_api()
        signal_bus.connection_changed.emit("disconnected")
        signal_bus.connection_message.emit("error", f"物理设备连接已断开: {reason}")

    def get_current(self):
        if not self._ensure_api(silent=True):
            if self._connected:
                return [0] * 6
            return None
        try:
            return self.api.get_current()
        except Exception:
            return None

    def get_speed(self):
        if not self._ensure_api(silent=True):
            if self._connected:
                return [100] * 6
            return None
        try:
            return self.api.get_speed()
        except Exception:
            return None

    def get_matrix_touch(self):
        if not self._ensure_api(silent=True) or not self.is_touch:
            return None
        try:
            return {
                "thumb_matrix": self.api.get_thumb_matrix_touch(),
                "index_matrix": self.api.get_index_matrix_touch(),
                "middle_matrix": self.api.get_middle_matrix_touch(),
                "ring_matrix": self.api.get_ring_matrix_touch(),
                "little_matrix": self.api.get_little_matrix_touch(),
            }
        except Exception:
            return None

