#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""o6_hardware_adapter.py - 默认 dry-run，可选硬件控制。只读 setting.yaml。"""
import os, sys
from o6_gui_params_adapter import O6GuiParamsAdapter

_SDK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LINKERHAND_PATH = os.path.join(_SDK_ROOT, "LinkerHand")

def _load_yaml_setting():
    yaml_path = os.path.join(_LINKERHAND_PATH, "config", "setting.yaml")
    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(f"setting.yaml not found: {yaml_path}")
    sys.path.insert(0, _LINKERHAND_PATH)
    try:
        from utils.load_write_yaml import LoadWriteYaml
        return LoadWriteYaml().load_setting_yaml()
    except Exception:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    finally:
        try: sys.path.remove(_LINKERHAND_PATH)
        except ValueError: pass

class O6HardwareAdapter:
    def __init__(self, enable_hardware=False):
        self.enable_hardware = bool(enable_hardware)
        self._hand_type = None; self._can = None; self._modbus = None
        self._api = None; self._gui_adapter = O6GuiParamsAdapter(); self._closed = False

    def _detect_o6_hand(self):
        config = _load_yaml_setting()
        lh = config.get("LINKER_HAND", {})
        for ht in ("LEFT_HAND", "RIGHT_HAND"):
            cfg = lh.get(ht, {})
            if cfg.get("EXISTS") and str(cfg.get("JOINT","")).upper() == "O6":
                self._hand_type = "left" if ht == "LEFT_HAND" else "right"
                self._can = cfg.get("CAN","PCAN_USBBUS1")
                self._modbus = cfg.get("MODBUS","None")
                return True
        return False

    def connect(self):
        if not self.enable_hardware:
            print("[INFO] dry-run mode. No hardware connection. No yaml/sdk loading.")
            return self
        if not self._detect_o6_hand():
            raise RuntimeError("O6 hand not found in setting.yaml")
        print(f"[INFO] detected O6 hand_type={self._hand_type}, CAN={self._can}")
        print("[SAFETY] ENABLE_HARDWARE=True. Hand will move.")
        try:
            sys.path.insert(0, _LINKERHAND_PATH)
            from linker_hand_api import LinkerHandApi
            self._api = LinkerHandApi(hand_type=self._hand_type, hand_joint="O6",
                                       modbus=self._modbus, can=self._can)
            print("[INFO] LinkerHandApi initialized.")
        except Exception as e:
            raise RuntimeError(f"Failed to init LinkerHandApi: {e}") from e
        finally:
            try: sys.path.remove(_LINKERHAND_PATH)
            except ValueError: pass
        return self

    def move_pose(self, pose, source="unknown"):
        pose = self._gui_adapter.validate_pose(pose)
        if not self.enable_hardware:
            print(f"[DRY-RUN] move_pose: source={source}, pose={pose}. No hardware.")
            return
        if self._api is None: raise RuntimeError("Not connected. Call connect() first.")
        print(f"[HARDWARE] move_pose: source={source}, pose={pose}")
        self._api.finger_move(pose)

    def run_gesture(self, gesture):
        action = self._gui_adapter.gesture_to_action(gesture)
        pose = self._gui_adapter.get_pose_by_action(action)
        self.move_pose(pose, source=f"gesture:{gesture}->{action}")

    def close(self):
        if self._closed: return
        if self._api and hasattr(self._api,"close_can"):
            try: self._api.close_can()
            except Exception as e: print(f"[WARNING] close: {e}", file=sys.stderr)
        self._closed = True
        print("[INFO] closed.")

    def __enter__(self): self.connect(); return self
    def __exit__(self,*a): self.close()
