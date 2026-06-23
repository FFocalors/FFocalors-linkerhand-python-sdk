#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
left_hand_teleop.py - custom_11 -> O6 左手实时同像动态控制。

模式:
    --control-mode pose       : 连续姿态匹配（默认，任意姿态实时跟随）
    --control-mode gesture    : 手势识别 + 预设动作

输入:
    --input-mode sample       : 离线样例
    --input-mode stream       : 实时帧（custom11_server）

默认: control-mode=pose, mirror-mode=same, preset=balanced_realtime, dry-run
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
from hand_pose_mapper import Custom11ToO6PoseMapper, PRESETS
from o6_gui_params_adapter import O6GuiParamsAdapter
from o6_hardware_adapter import O6HardwareAdapter


def _load_sample_keypoints(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name, pts in data.items():
        validate_keypoints(pts, name=name)
    return data


def _fetch_stream_frame(url, timeout=2):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return None, {"error": str(exc)}
    if not body.get("ok") or not body.get("fresh"):
        return None, body
    return body.get("frame"), body


def _print_pose_json(frame_count, result, mode, age_sec, latency_sec, frame_info):
    out = {
        "frame_id": frame_count, "mode": mode,
        "age_sec": age_sec, "latency_sec": latency_sec,
        "pose": result.get("pose"), "valid": result.get("valid", True),
        "debug": result.get("debug", {}),
    }
    print(json.dumps(out, ensure_ascii=False))


def _print_pose_readable(frame_count, result, mode, age_sec):
    dbg = result.get("debug", {})
    print(f"\n{'─'*50} Frame {frame_count} ({mode})")
    print(f"  frame age        : {age_sec:.3f}s" if age_sec else "  frame age: N/A")
    if not result.get("valid", True):
        print(f"  WARNING          : {result['reason']}")
        return
    print(f"  curl_scores      : index={dbg.get('curl_scores',{}).get('index',0):.3f} "
          f"middle={dbg.get('curl_scores',{}).get('middle',0):.3f} "
          f"ring={dbg.get('curl_scores',{}).get('ring',0):.3f} "
          f"little={dbg.get('curl_scores',{}).get('little',0):.3f}")
    print(f"  thumb_swing      : {dbg.get('thumb_swing_score',0):.3f}"
          f" (raw={dbg.get('thumb_swing_raw',0):.3f}, inverted={dbg.get('thumb_swing_inverted',False)})")
    print(f"  thumb_bend       : {dbg.get('thumb_bend_score',0):.3f}")
    print(f"  raw_pose         : {dbg.get('raw_pose',[])}")
    print(f"  smoothed_pose    : {dbg.get('smoothed_pose',[])}")
    print(f"  O6 pose (6-dim)  : {result['pose']}")
    print(f"  O6 order         : [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")


def run_teleop(hw, mapper, gui, args):
    enable_hw = args.enable_hardware
    mode = "HARDWARE" if enable_hw else "DRY-RUN"
    print_json = args.print_json
    control_is_pose = (args.control_mode == "pose")

    if not print_json:
        print(f"\n[INFO] control_mode={args.control_mode}, mirror={args.mirror_mode}, "
              f"preset={args.preset}, input={args.input_mode}")
        print(f"[INFO] O6 param source: {gui.source_path}")
        print(f"[INFO] O6 vector: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
        if control_is_pose:
            print("[INFO] pose mode: continuous finger curl -> O6 pose mapping")
        print(f"[INFO] MODE: {mode}\n")

    if args.explain and not print_json and control_is_pose:
        # Explain mapping for a test set
        samples = _load_sample_keypoints(args.keypoints_file)
        first = list(samples.values())[0]
        exp = mapper.explain_mapping(first)
        for d in exp["o6_dimensions"]:
            print(f"  dim {d['dim']}: {d['name']} ({d['中文']}) curl={d.get('curl_score',0):.3f} "
                  f"lerp-> final={d.get('final_value')}")

    # Latency / FPS tracking
    receive_times = []
    emit_times = []

    frame_count = 0
    while True:
        if args.max_frames and frame_count >= args.max_frames:
            break

        now = time.time()

        # ---- 获取帧 ----
        if args.input_mode == "stream":
            frame, resp_body = _fetch_stream_frame(args.stream_url)
            if frame is None:
                if not print_json:
                    print("[stream] No fresh frame. Skip.")
                time.sleep(args.interval)
                if not args.loop: break
                continue
            kps = frame.get("keypoints", [])
            age_sec = resp_body.get("age_sec", -1)
            latency_sec = resp_body.get("latency_sec", -1)
            client_ts = frame.get("timestamp", now)
            server_recv = resp_body.get("server_receive_time", now)
        else:
            samples = _load_sample_keypoints(args.keypoints_file)
            names = list(samples.keys())
            name = names[frame_count % len(names)] if args.loop else names[min(frame_count, len(names)-1)]
            kps = samples[name]
            age_sec = 0.0
            latency_sec = 0.0
            client_ts = server_recv = now

        try:
            validate_keypoints(kps)
        except Exception:
            frame_count += 1
            continue

        # ---- 映射 ----
        t0 = time.time()
        if control_is_pose:
            result = mapper.map_keypoints(kps)
        else:
            from gesture_recognizer import Custom11GestureRecognizer
            rec = Custom11GestureRecognizer()
            gres = rec.recognize(kps)
            gesture = gres["gesture"]
            action = gui.gesture_to_action(gesture) if gesture in ["rock","paper","scissors","ok","pinch","thumb_up"] else gesture
            pose = gui.get_pose_by_action(action) if action in gui.list_actions() else gui.get_pose_by_action("张开")
            result = {"valid": True, "pose": pose, "debug": {"gesture": gesture, "action": action}}
        map_time = time.time() - t0

        if not result.get("valid", True) and not print_json:
            print(f"[WARN] Frame {frame_count}: {result.get('reason','invalid')}. Skip.")
            frame_count += 1
            time.sleep(args.interval)
            if not args.loop: break
            continue

        # ---- 输出 ----
        if print_json:
            _print_pose_json(frame_count, result, mode, age_sec, latency_sec, frame)
        else:
            _print_pose_readable(frame_count, result, mode, age_sec)
            if control_is_pose:
                print(f"  mapping_time     : {map_time*1000:.1f}ms")

        # ---- 控制 ----
        hw.move_pose(result["pose"], source=f"teleop:{args.control_mode}")

        # ---- 跟踪 ----
        receive_times.append(client_ts)
        emit_times.append(now)

        if args.latency_log and not print_json:
            print(f"  [latency] client={client_ts:.3f} server_recv={server_recv:.3f} "
                  f"now={now:.3f} age={age_sec:.3f}s map={map_time*1000:.1f}ms")

        if args.fps_log and not print_json and len(receive_times) >= 2:
            rec_fps = (len(receive_times) - 1) / max(receive_times[-1] - receive_times[0], 0.001)
            emt_fps = (len(emit_times) - 1) / max(emit_times[-1] - emit_times[0], 0.001)
            print(f"  [fps] receive_est={rec_fps:.1f} emit_est={emt_fps:.1f}")

        frame_count += 1
        time.sleep(args.interval)
        if not args.loop and args.input_mode == "sample" and frame_count >= len(_load_sample_keypoints(args.keypoints_file)):
            break

    if not print_json:
        print("\n[INFO] teleop finished.")


def main():
    parser = argparse.ArgumentParser(description="Left hand custom_11 -> O6 teleop (real-time pose)")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--enable-hardware", action="store_true", default=False)
    parser.add_argument("--input-mode", choices=["sample", "stream"], default="sample")
    parser.add_argument("--control-mode", choices=["pose", "gesture"], default="pose",
                        help="pose=continuous mapping, gesture=preset actions")
    parser.add_argument("--preset", choices=["fast_realtime", "balanced_realtime", "stable_precise"],
                        default="balanced_realtime")
    parser.add_argument("--mirror-mode", choices=["same"], default="same")
    parser.add_argument("--stream-url", default="http://127.0.0.1:8765/latest")
    parser.add_argument("--stream-max-age-sec", type=float, default=1.0)
    parser.add_argument("--keypoints-file",
                        default=os.path.join(os.path.dirname(__file__), "sample_keypoints_11.json"))
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--latency-log", action="store_true")
    parser.add_argument("--fps-log", action="store_true")
    parser.add_argument("--no-smoothing", action="store_true")
    parser.add_argument("--deadzone", type=float, default=None)
    args = parser.parse_args()

    enable_hw = args.enable_hardware
    if enable_hw: args.dry_run = False

    gui = O6GuiParamsAdapter()
    mapper = Custom11ToO6PoseMapper(preset=args.preset, mirror_mode=args.mirror_mode)
    if args.no_smoothing:
        mapper.smoothing_alpha = 1.0
        mapper.deadzone = 0
    if args.deadzone is not None:
        mapper.deadzone = args.deadzone

    with O6HardwareAdapter(enable_hardware=enable_hw) as hw:
        run_teleop(hw, mapper, gui, args)


if __name__ == "__main__":
    main()
