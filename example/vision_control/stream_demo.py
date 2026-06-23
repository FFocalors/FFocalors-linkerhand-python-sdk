#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_demo.py

模拟前端向 custom11_server.py POST 关键点。

新增: --fps, --trajectory smooth
"""
import argparse
import json
import math
import os
import random
import sys
import time
import urllib.request

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_samples(path):
    with open(path, "r", encoding="utf-8") as f: return json.load(f)


def _interpolate(src, dst, t):
    """在两组 11 点之间线性插值。"""
    return [{"x": s["x"] + t * (d["x"] - s["x"]), "y": s["y"] + t * (d["y"] - s["y"])}
            for s, d in zip(src, dst)]


def _jittered(kps, jitter):
    if jitter <= 0: return kps
    return [{"x": p["x"] + random.uniform(-jitter, jitter),
             "y": p["y"] + random.uniform(-jitter, jitter)} for p in kps]


def _send(url, hand, kps):
    payload = json.dumps({"source": "stream_demo", "timestamp": time.time(),
                          "hand": hand, "keypoints": kps}).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.getcode(), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8") if exc.fp else str(exc)
    except Exception as exc:
        return 0, str(exc)


def main():
    parser = argparse.ArgumentParser(description="Send sample keypoints to custom11_server")
    parser.add_argument("--url", default="http://127.0.0.1:8765/keypoints")
    parser.add_argument("--keypoints-file", default=os.path.join(_SCRIPT_DIR, "sample_keypoints_11.json"))
    parser.add_argument("--groups", type=str, default=None)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--fps", type=float, default=0, help="FPS (overrides --interval)")
    parser.add_argument("--jitter", type=float, default=0.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--hand", default="left")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--trajectory", choices=["smooth", "step"], default="step",
                        help="smooth=interpolate between groups, step=discrete")
    args = parser.parse_args()

    samples = _load_samples(args.keypoints_file)
    all_names = list(samples.keys())

    if args.groups:
        groups = [g.strip() for g in args.groups.split(",") if g.strip()]
        for g in groups:
            if g not in samples:
                print(f"[ERROR] group '{g}' not found. Available: {all_names}", file=sys.stderr)
                sys.exit(1)
    else:
        groups = all_names

    delay = 1.0 / args.fps if args.fps > 0 else args.interval
    traj = args.trajectory

    print(f"[stream_demo] groups: {groups} | delay: {delay:.3f}s | traj: {traj} | jitter: {args.jitter}")

    sent = 0; idx = 0
    # For smooth trajectory, cache last frame
    last_kps = None
    prev_name = None

    while True:
        name = groups[idx % len(groups)]

        if traj == "smooth" and last_kps is not None:
            # Interpolate over 'steps' frames
            steps = max(1, int(1.0 / max(delay, 0.01)))
            target_kps = samples[name]
            for s in range(steps):
                t = (s + 1) / steps
                kps = _interpolate(last_kps, target_kps, t)
                kps = _jittered(kps, args.jitter)
                status, body = _send(args.url, args.hand, kps)
                if args.print_json:
                    print(json.dumps({"group": name, "phase": f"{t:.2f}", "status": status}, ensure_ascii=False))
                else:
                    print(f"[stream_demo] sent group={name}@{t:.2f}, status={status}")
                sent += 1
                if args.count > 0 and sent >= args.count: break
                time.sleep(delay)
            if args.count > 0 and sent >= args.count: break
            last_kps = samples[name]
        else:
            kps = _jittered(samples[name], args.jitter)
            status, body = _send(args.url, args.hand, kps)
            if args.print_json:
                print(json.dumps({"group": name, "status": status, "response": body}, ensure_ascii=False))
            else:
                print(f"[stream_demo] sent group={name}, status={status}")
            last_kps = samples[name]
            sent += 1
            time.sleep(delay)

        if args.count > 0 and sent >= args.count: break
        if not args.loop and idx >= len(groups) - 1: break
        idx += 1

    print("[stream_demo] done.")


if __name__ == "__main__":
    main()
