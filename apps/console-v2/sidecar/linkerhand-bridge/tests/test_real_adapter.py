import contextlib
import io
import sys
import types

import pytest

from adapters.base import AdapterError, RealSdkAdapter


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


def test_real_adapter_requires_physical_probe_when_sdk_exposes_it(monkeypatch):
    class FakeApi:
        def __init__(self, **_kwargs): pass
        def probe_connection(self): return False

    package = types.ModuleType("LinkerHand")
    package.__path__ = []
    module = types.ModuleType("LinkerHand.linker_hand_api")
    module.LinkerHandApi = FakeApi
    monkeypatch.setitem(sys.modules, "LinkerHand", package)
    monkeypatch.setitem(sys.modules, "LinkerHand.linker_hand_api", module)

    adapter = RealSdkAdapter("O6", "left", {"type": "can", "channel": "PCAN_TEST"})
    with pytest.raises(AdapterError) as error:
        adapter.connect()
    assert error.value.code == "DEVICE_NOT_RESPONDING"
    assert not adapter.connected


def test_real_adapter_sanitizes_negative_no_data_markers(monkeypatch):
    """O6 legacy drivers cache -1 for channels the hand does not answer
    (e.g. current). Those placeholders must not leak into the byte-vector
    NDJSON contract or the Rust client rejects the whole telemetry packet."""
    captured = []

    class FakeApi:
        def __init__(self, **_kwargs): pass
        def get_state(self): return [1, 2, 3, 4, 5, 6]
        def get_current(self): return [-1] * 6
        def get_joint_speed(self): return [0] * 6
        def get_touch(self): return [-1, -1, -1, -1, -1, 0]

    package = types.ModuleType("LinkerHand")
    package.__path__ = []
    module = types.ModuleType("LinkerHand.linker_hand_api")
    module.LinkerHandApi = FakeApi
    monkeypatch.setitem(sys.modules, "LinkerHand", package)
    monkeypatch.setitem(sys.modules, "LinkerHand.linker_hand_api", module)

    adapter = RealSdkAdapter("O6", "left", {"type": "can", "channel": "PCAN_TEST"}, output=captured.append)
    adapter.connect()
    assert adapter.get_position() == [1, 2, 3, 4, 5, 6]
    assert adapter.get_current() == [0] * 6
    assert adapter.get_speed() == [0] * 6
    assert adapter.get_touch() == [0, 0, 0, 0, 0, 0]
    assert any("no-data markers" in text for text in captured)
    # A real error is preserved, only negative placeholders are mapped.
    assert adapter.get_current() == [0] * 6


def test_real_adapter_rejects_false_position_result(monkeypatch):
    class FakeApi:
        def __init__(self, **_kwargs): pass
        def probe_connection(self): return True
        def finger_move(self, _values): return False

    package = types.ModuleType("LinkerHand")
    package.__path__ = []
    module = types.ModuleType("LinkerHand.linker_hand_api")
    module.LinkerHandApi = FakeApi
    monkeypatch.setitem(sys.modules, "LinkerHand", package)
    monkeypatch.setitem(sys.modules, "LinkerHand.linker_hand_api", module)

    adapter = RealSdkAdapter("O6", "left", {"type": "can", "channel": "PCAN_TEST"})
    adapter.connect()
    with pytest.raises(AdapterError) as error:
        adapter.set_position([128] * 6)
    assert error.value.code == "COMMAND_REJECTED"
