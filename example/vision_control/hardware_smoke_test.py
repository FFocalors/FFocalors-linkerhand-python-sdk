#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hardware_smoke_test.py

硬件冒烟测试：单次安全验证 O6HardwareAdapter 是否能通过 LinkerHandApi.finger_move(pose)
控制机械手执行指定预设动作。

默认 dry-run，只有 --enable-hardware 才真实控制机械手。
"""
import argparse
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
    parser = argparse.ArgumentParser(description="O6 hardware smoke test - single action verify")
    parser.add_argument("--action", type=str, default=None,
                        help="预设动作名，例如: 张开 / 握拳 / 贰 / OK / 点赞")
    parser.add_argument("--list", action="store_true", default=False,
                        help="列出 GUI constants.py 中可用的 O6 预设动作")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="默认 dry-run 模式")
    parser.add_argument("--enable-hardware", action="store_true", default=False,
                        help="启用真实硬件控制（需确认安全）")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="硬件模式下执行前的等待时间（秒），默认 2.0")
    args = parser.parse_args()

    enable_hw = args.enable_hardware
    if enable_hw:
        args.dry_run = False

    # ---- 初始化适配器 ----
    gui = O6GuiParamsAdapter()
    actions = gui.list_actions()

    # ---- --list 模式 ----
    if args.list:
        print(f"\nO6 preset actions (source: {gui.source_path}):")
        print(f"  fallback used: {gui.fallback_used}")
        print(f"  O6 joint order: [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]\n")
        for name in sorted(actions):
            pose = gui.get_pose_by_action(name)
            print(f"  {name:6s} -> {pose}")
        return

    # ---- --action 必填 ----
    if not args.action:
        print("ERROR: --action is required (or use --list to see available actions).")
        print(f"Available actions: {', '.join(sorted(actions))}")
        sys.exit(1)

    action_name = args.action.strip()
    if action_name not in actions:
        print(f"ERROR: action '{action_name}' not found.")
        print(f"Available actions: {', '.join(sorted(actions))}")
        sys.exit(1)

    pose = gui.get_pose_by_action(action_name)
    mode = "HARDWARE" if enable_hw else "DRY-RUN"

    # ---- 输出信息 ----
    print(f"\n{'='*60}")
    print(f"  O6 Hardware Smoke Test")
    print(f"{'='*60}")
    print(f"  Action name   : {action_name}")
    print(f"  O6 pose       : {pose}")
    print(f"  Pose dims     : {len(pose)} (O6 = 6)")
    print(f"  Joint order   : [thumb_bend, thumb_swing, index_bend, middle_bend, ring_bend, little_bend]")
    print(f"  Param source  : {gui.source_path}")
    print(f"  Fallback used : {gui.fallback_used}")
    print(f"  Mode          : {mode}")
    print(f"{'='*60}")

    # ---- dry-run ----
    if not enable_hw:
        print("\n[DRY-RUN] pose printed above. No hardware command sent.")
        print("To control real hardware, use: --enable-hardware")
        return

    # ---- 安全提示 + 倒计时 ----
    print("\n" + "!"*60)
    print("  SAFETY CONFIRMATION REQUIRED")
    print("!"*60)
    print("  1. Please ensure the GUI (gui_control/main.py) is CLOSED.")
    print("  2. Ensure the O6 hand workspace is clear of obstacles.")
    print("  3. Keep fingers and objects AWAY from gripping areas.")
    print("  4. The hand will execute action: {}".format(action_name))
    print("  5. This is a SINGLE action - no loop, no continuous control.")
    print("!"*60)

    countdown = max(1.0, args.delay)
    print(f"\n  Executing in {int(countdown)} seconds...")
    for i in range(int(countdown), 0, -1):
        print(f"  {i}...")
        time.sleep(1.0)

    # ---- 连接硬件 + 执行 ----
    print("\n[HARDWARE] Connecting to O6 hand...")
    try:
        with O6HardwareAdapter(enable_hardware=True) as hw:
            print(f"[HARDWARE] Connected. Sending action '{action_name}', pose={pose}")
            hw.move_pose(pose, source=f"smoke_test:{action_name}")
            print(f"[HARDWARE] Action '{action_name}' sent successfully.")
            time.sleep(0.5)
    except Exception as exc:
        print(f"\n[ERROR] Hardware smoke test FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n[HARDWARE] Smoke test PASSED. No errors during execution.")
    print("[INFO] You may now proceed to dynamic teleop tests with --enable-hardware.")


if __name__ == "__main__":
    main()
