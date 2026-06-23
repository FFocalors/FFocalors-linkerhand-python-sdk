#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hardware_smoke_test.py

硬件冒烟测试：单次验证 O6 预设动作。默认 dry-run。

新增：--print-json, --no-countdown, --show-source
"""
import argparse
import json
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from o6_gui_params_adapter import O6GuiParamsAdapter
from o6_hardware_adapter import O6HardwareAdapter


def main():
    parser = argparse.ArgumentParser(description="O6 hardware smoke test")
    parser.add_argument("--action", type=str, default=None, help="预设动作名")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--enable-hardware", action="store_true", default=False)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--no-countdown", action="store_true",
                        help="Skip countdown (dry-run only)")
    parser.add_argument("--show-source", action="store_true",
                        help="Print pose parameter source info")
    args = parser.parse_args()

    enable_hw = args.enable_hardware
    if enable_hw:
        args.dry_run = False

    gui = O6GuiParamsAdapter()
    actions = gui.list_actions()

    # --list
    if args.list:
        if args.print_json:
            print(json.dumps({
                "actions": actions,
                "source": gui.source_path,
                "fallback": gui.fallback_used,
                "joint_order": "[thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]",
            }, ensure_ascii=False))
        else:
            print(f"\nO6 preset actions (source: {gui.source_path})")
            print(f"  fallback: {gui.fallback_used}")
            print(f"  joint order: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]\n")
            for name in sorted(actions):
                print(f"  {name:6s} -> {gui.get_pose_by_action(name)}")
        return

    if not args.action:
        print("ERROR: --action required (use --list to see actions)")
        print(f"Available: {', '.join(sorted(actions))}")
        sys.exit(1)

    if args.action.strip() not in actions:
        print(f"ERROR: action '{args.action}' not found. Available: {', '.join(sorted(actions))}")
        sys.exit(1)

    action_name = args.action.strip()
    pose = gui.get_pose_by_action(action_name)
    mode = "HARDWARE" if enable_hw else "DRY-RUN"

    if args.print_json:
        print(json.dumps({
            "action": action_name, "pose": pose, "mode": mode,
            "source": gui.source_path, "fallback": gui.fallback_used,
            "joint_order": ["thumb_bend", "thumb_swing", "index_bend", "middle_bend", "ring_bend", "little_bend"],
        }, ensure_ascii=False))
    else:
        print(f"\n{'='*60}")
        print(f"  O6 Hardware Smoke Test")
        print(f"{'='*60}")
        print(f"  Action name   : {action_name}")
        print(f"  O6 pose       : {pose}")
        print(f"  Joint order   : [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
        if args.show_source:
            print(f"  Param source  : {gui.source_path}")
            print(f"  Fallback used : {gui.fallback_used}")
        print(f"  Mode          : {mode}")
        print(f"{'='*60}")

    # dry-run
    if not enable_hw:
        if not args.print_json:
            print("\n[DRY-RUN] No hardware command sent. Use --enable-hardware for real control.")
        return

    # 安全提示
    if not args.print_json:
        print("\n" + "!" * 60)
        print("  SAFETY CONFIRMATION")
        print("!" * 60)
        print("  1. Ensure GUI is CLOSED.")
        print("  2. Workspace clear of obstacles.")
        print("  3. Keep fingers AWAY from gripping areas.")
        print(f"  4. Action: {action_name}  |  single execution only.")
        print("!" * 60)

    countdown = max(1.0, args.delay)
    if not args.print_json:
        print(f"\n  Executing in {int(countdown)} seconds...")
    for i in range(int(countdown), 0, -1):
        if not args.print_json:
            print(f"  {i}...")
        time.sleep(1.0)

    try:
        with O6HardwareAdapter(enable_hardware=True) as hw:
            hw.move_pose(pose, source=f"smoke_test:{action_name}")
            if not args.print_json:
                print(f"\n[HARDWARE] Action '{action_name}' sent. Smoke test PASSED.")
    except Exception as exc:
        msg = f"Smoke test FAILED: {exc}"
        if args.print_json:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        else:
            print(f"\n[ERROR] {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
