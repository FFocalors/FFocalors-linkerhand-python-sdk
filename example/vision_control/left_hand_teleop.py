#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
left_hand_teleop.py

custom_11 -> O6 左手动态控制。

输入模式：
    --input-mode sample   : 从 sample_keypoints_11.json 读取离线样例（默认）
    --input-mode stream   : 从 custom11_server.py GET /latest 获取实时帧

默认 dry-run，只有 --enable-hardware 时才控制机械手。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError: pass

from custom11_keypoints import validate_keypoints
from hand_pose_mapper import Custom11ToO6PoseMapper
from o6_gui_params_adapter import O6GuiParamsAdapter
from o6_hardware_adapter import O6HardwareAdapter


def _load_sample_keypoints(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name, pts in data.items():
        validate_keypoints(pts, name=name)
    return data


def _fetch_stream_frame(url, timeout=2):
    """从 /latest 获取最新帧。返回 (frame_dict, age_sec) 或 (None, None)。"""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[stream] failed to fetch {url}: {exc}", file=sys.stderr)
        return None, None
    if not body.get("ok") or not body.get("fresh"):
        return None, None
    return body.get("frame"), body.get("age_sec", -1)


def run_sample_mode(hardware, mapper, keypoints_file, loop, interval, enable_hardware):
    samples = _load_sample_keypoints(keypoints_file)
    names = list(samples.keys())
    mode = "HARDWARE" if enable_hardware else "DRY-RUN"
    print(f"\n[INFO] sample mode | groups: {names} | MODE: {mode}")
    print("[INFO] No live camera; using sample_keypoints_11.json for demonstration.")
    print("[INFO] O6 vector: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
    print("[INFO] thumb_swing (idx 1) is NOT wrist.\n")

    while True:
        for name in names:
            pts = samples[name]
            result = mapper.map(pts)
            final = result["final_pose"]
            print(f"\n---------- Group: {name} ----------")
            print(f"curl_scores       : {result['curl_scores']}")
            print(f"thumb_swing_score : {result['thumb_swing_score']}")
            print(f"thumb_bend_score  : {result['thumb_bend_score']}")
            print(f"raw_pose          : {result['raw_pose']}")
            print(f"smoothed_pose     : {result['smoothed_pose']}")
            print(f"mapped O6 pose    : {final}  (6-dim, source=GUI constants.py)")
            print(f"MODE              : {mode}")
            hardware.move_pose(final, source=f"teleop:{name}")
            time.sleep(interval)
        if not loop:
            break
    print("\n[INFO] sample teleop finished.")


def run_stream_mode(hardware, mapper, stream_url, stream_max_age, loop, interval, enable_hardware):
    mode = "HARDWARE" if enable_hardware else "DRY-RUN"
    print(f"\n[INFO] stream mode | url={stream_url} | max_age={stream_max_age}s | MODE: {mode}")
    print("[INFO] O6 vector: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
    print("[INFO] thumb_swing (idx 1) is NOT wrist.\n")

    while True:
        frame, age_sec = _fetch_stream_frame(stream_url)
        if frame is None:
            print("[stream] No fresh custom_11 frame. Skip this step. No hardware command sent.")
            time.sleep(interval)
            if not loop:
                break
            continue

        kps = frame.get("keypoints", [])
        print(f"\n[stream] received frame: kps={len(kps)}, age={age_sec}s, "
              f"hand={frame.get('hand','n/a')}, source={frame.get('source','n/a')}")

        try:
            validate_keypoints(kps)
        except Exception as exc:
            print(f"[stream] invalid keypoints: {exc}", file=sys.stderr)
            time.sleep(interval)
            if not loop:
                break
            continue

        result = mapper.map(kps)
        final = result["final_pose"]
        print(f"curl_scores       : {result['curl_scores']}")
        print(f"thumb_swing_score : {result['thumb_swing_score']}")
        print(f"thumb_bend_score  : {result['thumb_bend_score']}")
        print(f"raw_pose          : {result['raw_pose']}")
        print(f"smoothed_pose     : {result['smoothed_pose']}")
        print(f"mapped O6 pose    : {final}  (6-dim, source=GUI constants.py)")
        print(f"MODE              : {mode}")

        hardware.move_pose(final, source=f"teleop:stream")
        time.sleep(interval)
        if not loop:
            break

    print("\n[INFO] stream teleop finished.")


def main():
    parser = argparse.ArgumentParser(description="Left hand custom_11 -> O6 teleop")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--enable-hardware", action="store_true", default=False)
    parser.add_argument("--input-mode", choices=["sample","stream"], default="sample",
                        help="Input mode: sample (default) or stream")
    parser.add_argument("--stream-url", default="http://127.0.0.1:8765/latest",
                        help="GET /latest URL for stream mode")
    parser.add_argument("--stream-max-age-sec", type=float, default=1.0,
                        help="Max frame age for stream mode")
    parser.add_argument("--keypoint-format", default="custom_11", choices=["custom_11"])
    parser.add_argument("--keypoints-file",
                        default=os.path.join(os.path.dirname(__file__), "sample_keypoints_11.json"))
    parser.add_argument("--smoothing-alpha", type=float, default=0.3)
    parser.add_argument("--max-delta", type=int, default=50)
    parser.add_argument("--min-interval", type=float, default=0.05)
    parser.add_argument("--loop", action="store_true", default=False)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    enable_hardware = args.enable_hardware
    if enable_hardware: args.dry_run = False

    gui = O6GuiParamsAdapter()
    mapper = Custom11ToO6PoseMapper(
        smoothing_alpha=args.smoothing_alpha,
        max_delta=args.max_delta,
        min_interval=args.min_interval,
    )

    print(f"[INFO] left_hand_teleop | input_mode={args.input_mode}")
    print(f"[INFO] O6 param source: {gui.source_path} | fallback={gui.fallback_used}")
    print(f"[INFO] Hardware: {'ENABLED' if enable_hardware else 'DRY-RUN'}")

    with O6HardwareAdapter(enable_hardware=enable_hardware) as hardware:
        if args.input_mode == "stream":
            run_stream_mode(hardware, mapper, args.stream_url, args.stream_max_age_sec,
                            args.loop, args.interval, enable_hardware)
        else:
            run_sample_mode(hardware, mapper, args.keypoints_file, args.loop, args.interval,
                            enable_hardware)


if __name__ == "__main__":
    main()
