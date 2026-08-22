import pytest

from adapters.base import FakeAdapter, MODEL_SPECS
from protocol.schema import ProtocolError
from services.service import SidecarService


def connected(model="L10"):
    service = SidecarService()
    service.execute("connect", {"deviceId": "test", "model": model, "hand": "left", "transport": {"type": "can", "channel": "fake"}, "mode": "fake"})
    return service


@pytest.mark.parametrize("model,spec", MODEL_SPECS.items())
def test_connect_capabilities_lengths(model, spec):
    service = connected(model)
    result = service.execute("capabilities", {})
    assert result["positionLength"] == spec.position_length
    assert result["speedLength"] == spec.speed_length
    service.shutdown()


def test_exact_length_and_range_are_errors():
    service = connected("L10")
    with pytest.raises(ProtocolError) as exc:
        service.execute("setPosition", {"positions": [0]})
    assert exc.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ProtocolError) as exc:
        service.execute("setPosition", {"positions": [0] * 9 + [256]})
    assert exc.value.code == "INVALID_ARGUMENT"
    service.shutdown()


def test_unsupported_transport_and_capability():
    service = SidecarService()
    with pytest.raises(ProtocolError) as exc:
        service.execute("connect", {"deviceId": "test", "model": "L20", "hand": "left", "transport": {"type": "rs485", "port": "COM3"}, "mode": "fake"})
    assert exc.value.code == "UNSUPPORTED_TRANSPORT"
    service = connected("L10")
    with pytest.raises(ProtocolError) as exc:
        service.execute("setCurrent", {"currents": [1] * 10})
    assert exc.value.code == "UNSUPPORTED_CAPABILITY"
    service.shutdown()


def test_sdk_command_lengths_and_unsupported_l20_torque():
    service = connected("L20")
    assert service.execute("setSpeed", {"speeds": [1] * 5})["accepted"]
    assert service.execute("setCurrent", {"currents": [1] * 5})["accepted"]
    with pytest.raises(ProtocolError) as exc:
        service.execute("setSpeed", {"speeds": [1] * 20})
    assert exc.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ProtocolError) as exc:
        service.execute("setTorque", {"torques": [1] * 5})
    assert exc.value.code == "UNSUPPORTED_CAPABILITY"
    service.shutdown()


def test_shutdown_closes_worker_and_rejects_commands():
    service = connected()
    service.shutdown()
    assert service.closing
    with pytest.raises(RuntimeError):
        service.worker.submit(lambda: None)


def test_disconnect_is_recoverable_boundary():
    service = connected("L6")
    assert service.execute("disconnect", {})["disconnected"]
    with pytest.raises(ProtocolError) as exc:
        service.execute("getPosition", {})
    assert exc.value.code == "NOT_CONNECTED"
    service.shutdown()


def test_stop_is_a_write_barrier_until_explicit_unlock():
    service = connected("L10")
    assert service.execute("stop", {}) == {"stopped": True, "softwareLocked": True}
    with pytest.raises(ProtocolError) as exc:
        service.execute("setPosition", {"positions": [1] * 10})
    assert exc.value.code == "STOPPED"
    assert service.execute("unlock", {}) == {"unlocked": True, "softwareLocked": False}
    assert service.execute("setPosition", {"positions": [1] * 10})["accepted"]
    service.shutdown()
