import io
import json

import pytest

from main import run
from protocol.schema import ProtocolError, validate_request
from protocol.writer import EnvelopeWriter
from adapters.base import FakeAdapter


def test_schema_and_unknown_field_rejected():
    with pytest.raises(ProtocolError) as exc:
        validate_request({"schemaVersion": 1, "requestId": "a", "operation": "capabilities", "payload": {}, "oops": 1})
    assert exc.value.code == "UNKNOWN_FIELD"
    with pytest.raises(ProtocolError) as exc:
        validate_request({"schemaVersion": 2, "requestId": "a", "operation": "capabilities", "payload": {}})
    assert exc.value.code == "SCHEMA_UNSUPPORTED"


def test_writer_sequence_and_monotonic_time():
    output = io.StringIO()
    writer = EnvelopeWriter(output, io.StringIO())
    writer.emit(request_id="a", message_type="response", operation="x", payload={})
    writer.emit(request_id="b", message_type="response", operation="x", payload={})
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[1]["monotonicTimeMs"] >= rows[0]["monotonicTimeMs"]
    assert rows[0]["requestId"] == "a" and rows[1]["requestId"] == "b"


def test_cli_fake_telemetry_and_protocol_purity():
    incoming = "\n".join([
        json.dumps({"schemaVersion": 1, "requestId": "c", "operation": "connect", "payload": {"model": "L7", "hand": "right", "transport": {"type": "can", "channel": "fake"}, "mode": "fake"}}),
        json.dumps({"schemaVersion": 1, "requestId": "p", "operation": "setPosition", "payload": {"positions": list(range(7))}}),
        json.dumps({"schemaVersion": 1, "requestId": "t", "operation": "getTelemetry", "payload": {}}),
        json.dumps({"schemaVersion": 1, "requestId": "z", "operation": "close", "payload": {}}),
    ]) + "\n"
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(io.StringIO(incoming), stdout, stderr) == 0
    rows = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(rows) == 4
    assert [r["requestId"] for r in rows] == ["c", "p", "t", "z"]
    assert rows[2]["payload"]["position"] == list(range(7))
    assert stderr.getvalue() == ""


def test_invalid_schema_returns_error_envelope():
    incoming = json.dumps({"schemaVersion": 99, "requestId": "bad", "operation": "close", "payload": {}}) + "\n"
    stdout = io.StringIO()
    run(io.StringIO(incoming), stdout, io.StringIO())
    row = json.loads(stdout.getvalue())
    assert row["messageType"] == "error"
    assert row["payload"]["error"]["code"] == "SCHEMA_UNSUPPORTED"


def test_fake_sdk_prints_are_forwarded_to_stderr():
    stdout, stderr = io.StringIO(), io.StringIO()
    writer = EnvelopeWriter(stdout, stderr)
    adapter = FakeAdapter(noise=True, output=writer.sdk_output)
    adapter.connect()
    assert stdout.getvalue() == ""
    assert "fake-sdk:connect" in stderr.getvalue()
