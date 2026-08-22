import contextlib
import io
import sys
import types

from adapters.base import RealSdkAdapter


def test_real_adapter_uses_legacy_constructor_and_methods(monkeypatch):
    calls = []

    class FakeApi:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
            print("sdk constructor noise", flush=True)

        def get_state(self): calls.append(("get_state",)); print("state noise", flush=True); return [1]
        def get_current(self): calls.append(("get_current",)); return [2]
        def get_joint_speed(self): calls.append(("get_joint_speed",)); return [3]
        def get_touch(self): calls.append(("get_touch",)); return [4]
        def finger_move(self, values): calls.append(("finger_move", values))
        def set_speed(self, values): calls.append(("set_speed", values))
        def set_torque(self, values): calls.append(("set_torque", values))
        def close_can(self): calls.append(("close_can",))

    package = types.ModuleType("LinkerHand")
    package.__path__ = []
    module = types.ModuleType("LinkerHand.linker_hand_api")
    module.LinkerHandApi = FakeApi
    monkeypatch.setitem(sys.modules, "LinkerHand", package)
    monkeypatch.setitem(sys.modules, "LinkerHand.linker_hand_api", module)

    captured = []
    adapter = RealSdkAdapter("L10", "right", {"type": "can", "channel": "PCAN_TEST"}, output=captured.append)
    with contextlib.redirect_stdout(io.StringIO()) as protocol_stdout:
        adapter.connect()
        assert adapter.get_position() == [1]
        assert adapter.get_speed() == [3]
        adapter.set_position([9] * 10)
        adapter.set_speed([8] * 10)
        adapter.set_torque([7] * 10)
        adapter.disconnect()
    assert protocol_stdout.getvalue() == ""
    assert ("init", {"hand_type": "right", "hand_joint": "L10", "can": "PCAN_TEST"}) in calls
    assert ("get_joint_speed",) in calls
    assert ("close_can",) in calls
    assert any("sdk constructor noise" in text for text in captured)
    assert any("state noise" in text for text in captured)


def test_real_adapter_rs485_uses_modbus_constructor(monkeypatch):
    calls = []

    class FakeApi:
        def __init__(self, **kwargs): calls.append(kwargs)

    package = types.ModuleType("LinkerHand")
    package.__path__ = []
    module = types.ModuleType("LinkerHand.linker_hand_api")
    module.LinkerHandApi = FakeApi
    monkeypatch.setitem(sys.modules, "LinkerHand", package)
    monkeypatch.setitem(sys.modules, "LinkerHand.linker_hand_api", module)
    adapter = RealSdkAdapter("L6", "left", {"type": "rs485", "port": "COM7"})
    adapter.connect()
    assert calls == [{"hand_type": "left", "hand_joint": "L6", "modbus": "COM7"}]
