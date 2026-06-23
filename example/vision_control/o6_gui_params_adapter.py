#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
o6_gui_params_adapter.py - 只读复用 GUI constants.py 中已有的 O6 参数。
"""
import importlib.util
import os
import sys

_CONSTANTS_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "gui_control", "lhgui", "config", "constants.py"))

_FALLBACK_O6_CONFIG = {
    "joint_names": ["大拇指弯曲","大拇指横摆","食指弯曲","中指弯曲","无名指弯曲","小拇指弯曲"],
    "joint_names_en": ["thumb_bend","thumb_swing","index_bend","middle_bend","ring_bend","little_bend"],
    "init_pos": [250]*6,
    "preset_actions": {
        "张开":[250,250,250,250,250,250],"壹":[125,18,255,0,0,0],"贰":[92,87,255,255,0,0],
        "叁":[92,87,255,255,255,0],"肆":[92,87,255,255,255,255],"伍":[255,255,255,255,255,255],
        "OK":[96,100,118,250,250,250],"点赞":[250,79,0,0,0,0],"握拳":[102,18,0,0,0,0],
    },
}

_GESTURE_TO_ACTION = {"rock":"握拳","fist":"握拳","paper":"张开","open_palm":"张开",
                       "scissors":"贰","ok":"OK","pinch":"OK","thumb_up":"点赞"}

class O6GuiParamsAdapter:
    def __init__(self, constants_path=None):
        self._source_path = constants_path or _CONSTANTS_PATH
        self._config = self._load_o6_config()
        self._joint_names = self._config["joint_names"]
        self._init_pos = self._config["init_pos"]
        self._preset_actions = self._config.get("preset_actions",{})
        self._fallback_used = self._config is _FALLBACK_O6_CONFIG

    @property
    def source_path(self): return self._source_path
    @property
    def fallback_used(self): return self._fallback_used

    def _load_o6_config(self):
        if not os.path.isfile(self._source_path):
            print(f"[WARNING] constants.py not found, using fallback", file=sys.stderr)
            return _FALLBACK_O6_CONFIG
        try:
            spec = importlib.util.spec_from_file_location("gui_constants", self._source_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            hc = getattr(mod, "_HAND_CONFIGS", None)
            if hc is None: raise ValueError("_HAND_CONFIGS missing")
            o6 = hc.get("O6")
            if o6 is None: raise ValueError("O6 not in _HAND_CONFIGS")
            return {"joint_names": o6.joint_names, "joint_names_en": o6.joint_names_en,
                    "init_pos": o6.init_pos, "preset_actions": o6.preset_actions}
        except Exception as e:
            print(f"[WARNING] failed to load O6 config: {e}, using fallback", file=sys.stderr)
            return _FALLBACK_O6_CONFIG

    def get_joint_names(self): return list(self._joint_names)
    def get_joint_names_en(self): return ["thumb_bend","thumb_swing","index_bend","middle_bend","ring_bend","little_bend"]
    def get_init_pose(self): return self._validate(list(self._init_pos))
    def get_preset_actions(self): return {k:self._validate(list(v)) for k,v in self._preset_actions.items()}
    def list_actions(self): return list(self._preset_actions.keys())
    def get_pose_by_action(self, name):
        acts = self.get_preset_actions()
        if name not in acts: raise ValueError(f"action '{name}' not found. Available: {', '.join(self.list_actions())}")
        return self._validate(acts[name])
    def gesture_to_action(self, gesture):
        g = str(gesture).strip().lower()
        if g not in _GESTURE_TO_ACTION:
            raise ValueError(f"gesture '{g}' unmapped. Supported: {', '.join(sorted(_GESTURE_TO_ACTION))}")
        if g == "scissors":
            print("[INFO] gesture 'scissors' temporarily mapped to GUI preset action '贰'")
        return _GESTURE_TO_ACTION[g]
    def gesture_to_pose(self, gesture):
        return self.get_pose_by_action(self.gesture_to_action(gesture))
    def validate_pose(self, pose): return self._validate(pose)
    @staticmethod
    def _validate(pose, name="pose"):
        p = list(pose)
        if len(p) != 6: raise ValueError(f"{name} len must be 6, got {len(p)}")
        for i,v in enumerate(p):
            if not isinstance(v,(int,float)): raise ValueError(f"{name}[{i}] not numeric")
            if not 0<=int(v)<=255: raise ValueError(f"{name}[{i}]={v} out of [0,255]")
        return [int(v) for v in p]
