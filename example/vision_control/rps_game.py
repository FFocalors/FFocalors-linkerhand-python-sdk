#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rps_game.py

视觉猜拳（Rock-Paper-Scissors）。

输入模式：
    --input-mode sample   : 从 sample_keypoints_11.json 读取离线样例（默认）
    --input-mode stream   : 从 custom11_server.py GET /latest 获取实时帧

默认 dry-run，只有 --enable-hardware 时才控制机械手。
scissors 临时映射为 GUI 预设动作"贰"。
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError: pass

from custom11_keypoints import validate_keypoints
from gesture_recognizer import Custom11GestureRecognizer
from o6_gui_params_adapter import O6GuiParamsAdapter
from o6_hardware_adapter import O6HardwareAdapter

_GESTURES = ["rock", "paper", "scissors"]


def _load_sample_keypoints(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name in _GESTURES:
        if name not in data:
            raise ValueError(f"Keypoints file missing '{name}' group")
        validate_keypoints(data[name], name=name)
    return data


def _fetch_stream_frame(url, timeout=2):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[stream] failed to fetch {url}: {exc}", file=sys.stderr)
        return None
    if not body.get("ok") or not body.get("fresh"):
        return None
    return body.get("frame")


def _judge(human, robot):
    if human == robot:
        return "draw", "平局"
    rules = {("rock","scissors"):("win","人类胜"), ("scissors","paper"):("win","人类胜"),
             ("paper","rock"):("win","人类胜")}
    return rules.get((human, robot), ("lose", "机器人胜"))


def run_sample_round(round_idx, samples, recognizer, gui, hardware, human_gesture=None, seed=None):
    if human_gesture and human_gesture in samples:
        chosen = human_gesture
    else:
        chosen = random.choice(_GESTURES)
    kps = samples[chosen]
    res = recognizer.recognize(kps)
    human = res["gesture"] if res["gesture"] in _GESTURES else chosen
    if res["gesture"] not in _GESTURES:
        print(f"[ROUND {round_idx}] keypoints labelled '{chosen}', recognizer returned '{res['gesture']}' -> fallback")
    return _play_round(round_idx, human, gui, hardware)


def run_stream_round(round_idx, recognizer, gui, hardware, stream_url):
    frame = _fetch_stream_frame(stream_url)
    if frame is None:
        print(f"[ROUND {round_idx}] No fresh custom_11 frame. Skip this round. No hardware command sent.")
        return None
    kps = frame.get("keypoints", [])
    print(f"[ROUND {round_idx}] stream frame: kps={len(kps)}, "
          f"hand={frame.get('hand','n/a')}, source={frame.get('source','n/a')}")
    try:
        validate_keypoints(kps)
    except Exception as exc:
        print(f"[ROUND {round_idx}] invalid keypoints: {exc}", file=sys.stderr)
        return None
    res = recognizer.recognize(kps)
    human = res["gesture"] if res["gesture"] in _GESTURES else "unknown"
    if human == "unknown":
        print(f"[ROUND {round_idx}] recognizer returned unknown. Skip. No hardware command sent.")
        return None
    print(f"[ROUND {round_idx}] recognizer: gesture={human}, confidence={res['confidence']:.2f}")
    return _play_round(round_idx, human, gui, hardware)


def _play_round(round_idx, human, gui, hardware):
    robot = random.choice(_GESTURES)
    robot_action = gui.gesture_to_action(robot)
    robot_pose = gui.gesture_to_pose(robot)
    outcome, desc = _judge(human, robot)
    mode = "HARDWARE" if hardware.enable_hardware else "DRY-RUN"
    print(f"\n========== ROUND {round_idx} | MODE: {mode} ==========")
    print(f"Human gesture : {human}")
    print(f"Robot gesture : {robot}")
    print(f"Robot action  : {robot_action}")
    print(f"Robot pose    : {robot_pose}  (O6 6-dim, source=GUI constants.py)")
    print(f"Result        : {desc} ({outcome})")
    if robot == "scissors":
        print("[NOTICE] 'scissors' temporarily mapped to GUI preset action '贰'")
    hardware.run_gesture(robot)
    return outcome


def main():
    parser = argparse.ArgumentParser(description="Vision Rock-Paper-Scissors with O6")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--enable-hardware", action="store_true", default=False)
    parser.add_argument("--input-mode", choices=["sample","stream"], default="sample",
                        help="Input mode: sample (default) or stream")
    parser.add_argument("--stream-url", default="http://127.0.0.1:8765/latest",
                        help="GET /latest URL for stream mode")
    parser.add_argument("--stream-max-age-sec", type=float, default=1.0,
                        help="Max frame age for stream mode")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--keypoint-format", default="custom_11", choices=["custom_11"])
    parser.add_argument("--keypoints-file",
                        default=os.path.join(os.path.dirname(__file__), "sample_keypoints_11.json"))
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    enable_hardware = args.enable_hardware
    if enable_hardware: args.dry_run = False
    if args.seed is not None: random.seed(args.seed)

    recognizer = Custom11GestureRecognizer()
    gui = O6GuiParamsAdapter()

    print(f"\n[INFO] RPS game | input_mode={args.input_mode}")
    print(f"[INFO] O6 param source: {gui.source_path} | fallback={gui.fallback_used}")
    print(f"[INFO] Hardware: {'ENABLED' if enable_hardware else 'DRY-RUN'}")
    print("[INFO] O6 vector: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
    print("[INFO] thumb_swing (idx 1) is NOT wrist.\n")

    if args.input_mode == "sample":
        samples = _load_sample_keypoints(args.keypoints_file)

    with O6HardwareAdapter(enable_hardware=enable_hardware) as hardware:
        stats = {"win": 0, "lose": 0, "draw": 0, "skip": 0}
        for i in range(1, args.rounds + 1):
            if args.input_mode == "stream":
                outcome = run_stream_round(i, recognizer, gui, hardware, args.stream_url)
                if outcome is None:
                    stats["skip"] += 1
                    print()
                    continue
            else:
                outcome = run_sample_round(i, samples, recognizer, gui, hardware)
            stats[outcome] += 1
            if i < args.rounds:
                time.sleep(0.5)

    print(f"\n[INFO] Game over. Stats: win={stats['win']}, lose={stats['lose']}, "
          f"draw={stats['draw']}, skip={stats['skip']}")


if __name__ == "__main__":
    main()
