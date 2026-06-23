#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_demo.py

用 sample_keypoints_11.json 模拟前端，向 custom11_server.py 发送实时关键点。

不依赖 requests，只使用标准库 urllib/urllib.request。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_samples(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _send(url, hand, group_name, keypoints):
    payload = json.dumps({
        "source": "stream_demo",
        "timestamp": time.time(),
        "hand": hand,
        "keypoints": keypoints,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8") if exc.fp else str(exc)
    except Exception as exc:
        status = 0
        body = str(exc)
    return status, body


def main():
    parser = argparse.ArgumentParser(description="stream_demo - send sample keypoints to server")
    parser.add_argument("--url", default="http://127.0.0.1:8765/keypoints", help="POST endpoint")
    parser.add_argument("--keypoints-file",
                        default=os.path.join(_SCRIPT_DIR, "sample_keypoints_11.json"),
                        help="Path to sample keypoints JSON")
    parser.add_argument("--interval", type=float, default=1.0, help="Interval between sends (sec)")
    parser.add_argument("--loop", action="store_true", help="Loop infinitely")
    parser.add_argument("--hand", default="left", help="hand side (left/right)")
    args = parser.parse_args()

    samples = _load_samples(args.keypoints_file)
    names = list(samples.keys())
    print(f"[stream_demo] loaded groups: {names}")
    print(f"[stream_demo] target: {args.url}")
    print(f"[stream_demo] interval: {args.interval}s, hand={args.hand}")

    idx = 0
    while True:
        name = names[idx % len(names)]
        kps = samples[name]
        status, body = _send(args.url, args.hand, name, kps)
        print(f"[stream_demo] sent group={name}, kps={len(kps)}, "
              f"status={status}, response={body[:120]}")
        if not args.loop and idx >= len(names) - 1:
            break
        idx += 1
        time.sleep(args.interval)

    print("[stream_demo] done.")


if __name__ == "__main__":
    main()
