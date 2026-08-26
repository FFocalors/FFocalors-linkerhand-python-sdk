"""Verify real LinkerHand USB-CAN without intentionally changing its pose.

The default run sends only read queries. ``--send-hold`` reads a fresh joint
position and sends that exact byte vector back once, exercising the same action
path as Console V2 while requesting no displacement.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


CONSOLE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_ROOT = CONSOLE_ROOT / "sidecar" / "linkerhand-bridge"
sys.path.insert(0, str(BRIDGE_ROOT))

from adapters.base import RealSdkAdapter  # noqa: E402


def _position(values: object, expected: int) -> list[int]:
    if not isinstance(values, list) or len(values) != expected:
        raise RuntimeError(f"expected {expected} position bytes, got {values!r}")
    if any(not isinstance(value, (int, float)) or not 0 <= value <= 255 for value in values):
        raise RuntimeError(f"invalid position response: {values!r}")
    return [int(value) for value in values]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real LinkerHand CAN command path")
    parser.add_argument("--model", default="O6", choices=("O6", "L6", "L7", "L10", "L20", "G20", "L21", "L25"))
    parser.add_argument("--hand", default="left", choices=("left", "right"))
    parser.add_argument("--channel", default="PCAN_USBBUS1", help="PCAN_USBBUS1 for PCAN; usually 0 for candle")
    parser.add_argument("--send-hold", action="store_true", help="send the freshly read position back once")
    parser.add_argument("--tolerance", type=int, default=3, help="maximum post-write raw position delta (default: 3)")
    args = parser.parse_args()
    if args.tolerance < 0:
        parser.error("--tolerance must be non-negative")

    adapter = RealSdkAdapter(
        args.model,
        args.hand,
        {"type": "can", "channel": args.channel},
        sdk_root=str(REPOSITORY_ROOT),
        output=lambda text: print(text, end="", file=sys.stderr),
    )
    try:
        capabilities = adapter.connect()
        expected = capabilities["positionLength"]
        before = _position(adapter.get_position(), expected)
        print(f"PASS connect: {args.hand} {args.model} answered on {args.channel}")
        print(f"PASS fresh position ({expected} bytes): {before}")
        if args.send_hold:
            adapter.set_position(before)
            after = _position(adapter.get_position(), expected)
            maximum_delta = max(abs(current - target) for current, target in zip(after, before))
            if maximum_delta > args.tolerance:
                raise RuntimeError(
                    f"post-write readback delta {maximum_delta} exceeds tolerance {args.tolerance}: {after}"
                )
            print(f"PASS action path: write accepted and readback delta <= {args.tolerance}")
            print(f"PASS post-write position: {after}")
        else:
            print("READ-ONLY: no action command was sent; add --send-hold for the no-displacement write check")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
