import json
from pathlib import Path

import pytest

from adapters.base import FakeAdapter, MODEL_SPECS


@pytest.mark.parametrize("model,spec", MODEL_SPECS.items())
def test_model_vectors_and_order(model, spec):
    adapter = FakeAdapter(model=model)
    adapter.connect()
    position = list(range(spec.position_length))
    speed = [100] * spec.speed_length
    current = [5] * spec.current_length
    adapter.set_position(position)
    adapter.set_speed(speed)
    if "setCurrent" in spec.write_capabilities:
        adapter.set_current(current)
    assert adapter.get_position() == position
    assert adapter.get_speed() == speed
    assert len(adapter.get_current()) == spec.current_length
    assert adapter.calls[:3] == ["connect", "setPosition", "setSpeed"]


def test_fake_sdk_exception_boundary():
    adapter = FakeAdapter()
    with pytest.raises(Exception):
        adapter.get_position()


def test_raw_capability_fixture_matches_python_specs():
    fixture_path = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "raw-capabilities.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert set(fixture["models"]) == set(MODEL_SPECS)
    for model, spec in MODEL_SPECS.items():
        expected = fixture["models"][model]
        assert expected["positionLength"] == spec.position_length
        assert expected["speedCommandLength"] == spec.speed_command_length
        assert expected["currentCommandLength"] == spec.current_command_length
        assert expected["torqueCommandLength"] == spec.torque_command_length
