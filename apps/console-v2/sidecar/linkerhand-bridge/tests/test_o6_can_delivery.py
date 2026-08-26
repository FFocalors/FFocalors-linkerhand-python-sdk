import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import can
import pytest


SDK_PACKAGE = Path(__file__).resolve().parents[5] / "LinkerHand"
if str(SDK_PACKAGE) not in sys.path:
    sys.path.insert(0, str(SDK_PACKAGE))

from core.can.linker_hand_o6_can import LinkerHandO6Can  # noqa: E402


def _hand(bus):
    hand = LinkerHandO6Can.__new__(LinkerHandO6Can)
    hand.can_id = 0x28
    hand.can_channel = "TEST_CAN"
    hand.bus = bus
    hand._position_response = threading.Condition()
    hand._position_response_sequence = 0
    hand.x01 = [0] * 6
    return hand


def test_o6_status_requires_a_fresh_can_response():
    class SilentBus:
        def send(self, _message): pass

    with pytest.raises(TimeoutError, match="No O6 position response"):
        _hand(SilentBus()).get_current_status(timeout=0.01)


def test_o6_status_returns_response_received_after_query():
    hand = None

    class ReplyingBus:
        def send(self, _message):
            hand.process_response(
                SimpleNamespace(arbitration_id=0x28, data=bytearray([0x01, 1, 2, 3, 4, 5, 6]))
            )

    hand = _hand(ReplyingBus())
    assert hand.get_current_status(timeout=0.05) == [1, 2, 3, 4, 5, 6]


def test_o6_send_failure_crosses_the_sdk_boundary():
    class FailingBus:
        def send(self, _message):
            raise can.CanError("adapter unplugged")

    with pytest.raises(can.CanError, match="Failed to send CAN frame 0x01"):
        _hand(FailingBus()).set_joint_positions([10] * 6)
