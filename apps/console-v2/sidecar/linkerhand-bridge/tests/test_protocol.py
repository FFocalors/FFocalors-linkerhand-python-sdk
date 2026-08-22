import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from main import run
from protocol.schema import ProtocolError, validate_request
from protocol.writer import EnvelopeWriter
from adapters.base import FakeAdapter


def envelope(request_id, operation, payload, sequence):
    return {"schemaVersion": 1, "messageType": "command", "requestId": request_id, "sequence": sequence, "monotonicTimeMs": 1, "operation": operation, "payload": payload}


def test_schema_and_unknown_field_rejected():
    with pytest.raises(ProtocolError) as exc:
        validate_request({"schemaVersion": 1, "requestId": "a", "operation": "capabilities", "payload": {}, "oops": 1})
    assert exc.value.code == "UNKNOWN_FIELD"
    with pytest.raises(ProtocolError) as exc:
        validate_request({"schemaVersion": 2, "requestId": "a", "operation": "capabilities", "payload": {}})
    assert exc.value.code == "SCHEMA_UNSUPPORTED"
    with pytest.raises(ProtocolError) as exc:
        validate_request({"schemaVersion": 1, "requestId": "a", "operation": "capabilities", "payload": {}})
    assert exc.value.code == "INVALID_REQUEST"


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
        json.dumps(envelope("c", "connect", {"model": "L7", "hand": "right", "transport": {"type": "can", "channel": "fake"}, "mode": "fake"}, 1)),
        json.dumps(envelope("p", "setPosition", {"positions": list(range(7))}, 2)),
        json.dumps(envelope("t", "getTelemetry", {}, 3)),
        json.dumps(envelope("z", "close", {}, 4)),
    ]) + "\n"
    stdout, stderr = io.StringIO(), io.StringIO()
    assert run(io.StringIO(incoming), stdout, stderr) == 0
    rows = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(rows) == 4
    assert [r["requestId"] for r in rows] == ["c", "p", "t", "z"]
    assert rows[2]["payload"]["position"] == list(range(7))
    assert stderr.getvalue() == ""


def test_invalid_schema_returns_error_envelope():
    incoming = json.dumps(envelope("bad", "close", {}, 1) | {"schemaVersion": 99}) + "\n"
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


def test_cli_subprocess_bad_json_continues_and_close_exits():
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    rows = [
        "not-json",
        json.dumps(envelope("c", "connect", {"model": "O6", "hand": "left", "transport": {"type": "can", "channel": "fake"}, "mode": "fake"}, 1)),
        json.dumps(envelope("t", "getTelemetry", {}, 2)),
        json.dumps(envelope("z", "close", {}, 3)),
        json.dumps(envelope("after", "capabilities", {}, 4)),
    ]
    proc = subprocess.Popen([sys.executable, str(main_path), "--fake"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate("\n".join(rows) + "\n", timeout=5)
    output = [json.loads(line) for line in stdout.splitlines()]
    assert proc.returncode == 0
    assert output[0]["messageType"] == "error"
    assert output[0]["payload"]["error"]["code"] == "INVALID_JSON"
    assert [row["requestId"] for row in output[1:]] == ["c", "t", "z"]
    assert stderr == ""
