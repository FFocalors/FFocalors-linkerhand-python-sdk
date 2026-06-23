#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
if TARGET_DIR not in sys.path:
    sys.path.append(TARGET_DIR)

from LinkerHand.linker_hand_api import LinkerHandApi

def main():
    print("Initializing LinkerHandApi...")
    try:
        api = LinkerHandApi(
            hand_type="left",
            hand_joint="O6",
            modbus="None",
            can="PCAN_USBBUS1"
        )
    except Exception as e:
        print(f"Failed to initialize: {e}")
        return

    print("Successfully initialized API.")
    
    # 读初始位置
    init_state = api.get_state()
    print(f"Initial positions: {init_state}")
    
    # 尝试设置速度为 150
    print("Setting joint speed to 150...")
    api.set_speed([150] * 6)
    time.sleep(0.5)

    # 尝试控制五个手指弯曲到 150
    target_pos = [150] * 6
    print(f"Sending finger move command: {target_pos}")
    api.finger_move(target_pos)
    
    print("Waiting 3 seconds for hand to move and polling state...")
    for i in range(30):
        state = api.get_state()
        print(f"[{i * 0.1:.1f}s] Positions: {state}")
        time.sleep(0.1)
        
    # 尝试将手指恢复张开 (250)
    print("Sending finger move command to open (250)...")
    api.finger_move([250] * 6)
    
    print("Waiting 2 seconds and polling state...")
    for i in range(20):
        state = api.get_state()
        print(f"[{i * 0.1:.1f}s] Positions: {state}")
        time.sleep(0.1)

    print("Closing CAN interface.")
    try:
        api.hand.close_can_interface()
    except Exception as e:
        print(f"Error closing: {e}")

if __name__ == "__main__":
    main()
