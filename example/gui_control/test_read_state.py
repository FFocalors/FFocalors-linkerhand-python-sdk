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
    print("Starting loop to poll state (position and current)...")
    
    for i in range(50):
        state = api.get_state()
        current = api.get_current()
        print(f"[{i}] State (positions): {state} | Current: {current}")
        time.sleep(0.1)

    print("Done. Closing CAN.")
    try:
        api.hand.close_can_interface()
    except Exception as e:
        print(f"Error closing: {e}")

if __name__ == "__main__":
    main()
