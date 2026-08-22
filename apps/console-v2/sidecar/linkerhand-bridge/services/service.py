"""Command handling and stable error mapping for the sidecar bridge."""
from __future__ import annotations

import time
from typing import Any, Callable

from adapters.base import AdapterError, BaseAdapter, MODEL_SPECS, build_adapter
from protocol.schema import ProtocolError, validate_vector
from .worker import CommandWorker


_CONNECT_FIELDS = {"model", "hand", "transport", "mode", "sdkRoot"}
_TRANSPORT_FIELDS = {"can": {"type", "channel"}, "rs485": {"type", "port", "baudrate"}}


class SidecarService:
    def __init__(self, adapter_factory: Callable[..., BaseAdapter] = build_adapter, *, timeout: float = 10.0, worker: CommandWorker | None = None, output: Callable[[str], None] | None = None):
        self.adapter_factory = adapter_factory
        self.timeout = timeout
        self.worker = worker or CommandWorker()
        self.output = output or (lambda _text: None)
        self.adapter: BaseAdapter | None = None
        self.config: dict[str, Any] | None = None
        self.closing = False

    def _strict(self, payload: dict[str, Any], allowed: set[str], name: str) -> None:
        unknown = sorted(set(payload) - allowed)
        if unknown: raise ProtocolError("UNKNOWN_FIELD", f"unknown {name} field(s)", details={"fields": unknown})

    def _connected(self) -> BaseAdapter:
        if self.adapter is None or not self.adapter.connected:
            raise ProtocolError("NOT_CONNECTED", "device is not connected", retryable=True)
        return self.adapter

    def _run(self, fn: Callable[[], Any]) -> Any:
        try:
            return self.worker.submit(fn, timeout=self.timeout)
        except TimeoutError as exc:
            raise ProtocolError("TIMEOUT", "SDK command timed out", retryable=True) from exc
        except AdapterError as exc:
            raise ProtocolError(exc.code, exc.message, exc.retryable, exc.details) from exc
        except (RuntimeError, OSError) as exc:
            raise ProtocolError("SDK_ERROR", str(exc), retryable=True) from exc
        except ProtocolError: raise
        except Exception as exc:
            raise ProtocolError("SDK_ERROR", str(exc), retryable=True) from exc

    def _connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._strict(payload, _CONNECT_FIELDS, "connect")
        model = payload.get("model")
        if not isinstance(model, str) or model.upper() not in MODEL_SPECS: raise ProtocolError("INVALID_ARGUMENT", "unsupported model")
        model = model.upper()
        hand = payload.get("hand", "left")
        if hand not in ("left", "right"): raise ProtocolError("INVALID_ARGUMENT", "hand must be left or right")
        transport = payload.get("transport")
        if not isinstance(transport, dict) or transport.get("type") not in _TRANSPORT_FIELDS: raise ProtocolError("INVALID_ARGUMENT", "transport.type must be can or rs485")
        transport_type = transport["type"]
        unknown = sorted(set(transport) - _TRANSPORT_FIELDS[transport_type])
        if unknown: raise ProtocolError("UNKNOWN_FIELD", "unknown transport field(s)", details={"fields": unknown})
        spec = MODEL_SPECS[model]
        if transport_type not in spec.transports: raise ProtocolError("UNSUPPORTED_TRANSPORT", f"{model} does not support {transport_type}")
        if transport_type == "can" and (not isinstance(transport.get("channel"), str) or not transport["channel"]): raise ProtocolError("INVALID_ARGUMENT", "CAN channel is required")
        if transport_type == "rs485":
            if not isinstance(transport.get("port"), str) or not transport["port"]: raise ProtocolError("INVALID_ARGUMENT", "RS485 port is required")
            if not isinstance(transport.get("baudrate", 115200), int) or transport.get("baudrate", 115200) <= 0: raise ProtocolError("INVALID_ARGUMENT", "RS485 baudrate must be a positive integer")
            transport = {**transport, "baudrate": transport.get("baudrate", 115200)}
        mode = payload.get("mode", "real")
        if mode not in ("real", "fake"): raise ProtocolError("INVALID_ARGUMENT", "mode must be real or fake")
        sdk_root = payload.get("sdkRoot")
        if sdk_root is not None and not isinstance(sdk_root, str): raise ProtocolError("INVALID_ARGUMENT", "sdkRoot must be a string")
        if self.adapter is not None:
            self._run(lambda: self.adapter.close())
        self.adapter = self.adapter_factory(model, hand, transport, mode=mode, sdk_root=sdk_root, output=self.output)
        self.config = {"model": model, "hand": hand, "transport": transport, "mode": mode}
        return self._run(lambda: self.adapter.connect())

    def _read(self, operation: str) -> Any:
        adapter = self._connected()
        methods = {"getPosition": adapter.get_position, "getCurrent": adapter.get_current, "getSpeed": adapter.get_speed, "getTouch": adapter.get_touch}
        return {operation[3:].lower(): self._run(methods[operation])}

    def _telemetry(self) -> dict[str, Any]:
        adapter = self._connected()
        return {"position": self._run(adapter.get_position), "current": self._run(adapter.get_current), "speed": self._run(adapter.get_speed), "touch": self._run(adapter.get_touch)}

    def _write(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        adapter = self._connected()
        fields = {"setPosition": ("positions", adapter.spec.position_length, adapter.set_position), "setSpeed": ("speeds", adapter.spec.speed_command_length, adapter.set_speed), "setCurrent": ("currents", adapter.spec.current_command_length, adapter.set_current), "setTorque": ("torques", adapter.spec.torque_command_length, adapter.set_torque)}
        field, size, method = fields[operation]
        self._strict(payload, {field}, operation)
        if operation not in adapter.spec.write_capabilities: raise ProtocolError("UNSUPPORTED_CAPABILITY", f"{operation} is not supported by {adapter.model}")
        if size is None: raise ProtocolError("UNSUPPORTED_CAPABILITY", f"{operation} is not supported by {adapter.model}")
        values = validate_vector(payload.get(field), size, field)
        self._run(lambda: method(values))
        return {"accepted": True, field: values}

    def execute(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "connect": return self._connect(payload)
        if operation == "capabilities":
            self._strict(payload, set(), operation)
            if self.adapter is None: raise ProtocolError("NOT_CONNECTED", "connect before querying capabilities", retryable=True)
            return self.adapter.capabilities()
        if operation in {"getPosition", "getCurrent", "getSpeed", "getTouch"}: return self._read(operation)
        if operation == "getTelemetry":
            self._strict(payload, set(), operation); return self._telemetry()
        if operation in {"setPosition", "setSpeed", "setCurrent", "setTorque"}: return self._write(operation, payload)
        if operation == "disconnect":
            self._strict(payload, set(), operation)
            if self.adapter is not None: self._run(self.adapter.disconnect)
            return {"disconnected": True}
        if operation == "stop":
            self._strict(payload, set(), operation)
            return {"stopped": True}
        if operation == "close":
            self._strict(payload, set(), operation)
            if self.adapter is not None: self._run(self.adapter.close)
            self.closing = True
            return {"closed": True}
        raise ProtocolError("UNKNOWN_OPERATION", f"unsupported operation: {operation}")

    def submit(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.execute(operation, payload)

    def shutdown(self) -> None:
        try:
            if self.adapter is not None and self.adapter.connected: self._run(self.adapter.close)
        finally:
            self.worker.shutdown()
            self.closing = True
