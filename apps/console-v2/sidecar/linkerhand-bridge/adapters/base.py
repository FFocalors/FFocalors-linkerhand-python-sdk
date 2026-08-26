"""SDK adapters.  The service depends on this narrow interface, never on SDK internals."""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class AdapterError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.details = code, message, retryable, details or {}


@dataclass(frozen=True)
class ModelSpec:
    model: str
    position_length: int
    speed_length: int
    current_length: int
    speed_command_length: int
    current_command_length: int | None
    torque_command_length: int | None
    transports: tuple[str, ...]
    write_capabilities: tuple[str, ...]


MODEL_SPECS: dict[str, ModelSpec] = {
    "O6": ModelSpec("O6", 6, 6, 6, 6, None, 6, ("can", "rs485"), ("setPosition", "setSpeed", "setTorque")),
    "L6": ModelSpec("L6", 6, 6, 6, 6, None, 6, ("can", "rs485"), ("setPosition", "setSpeed", "setTorque")),
    "L7": ModelSpec("L7", 7, 7, 7, 7, None, 7, ("can", "rs485"), ("setPosition", "setSpeed", "setTorque")),
    "L10": ModelSpec("L10", 10, 10, 10, 10, None, 10, ("can", "rs485"), ("setPosition", "setSpeed", "setTorque")),
    "L20": ModelSpec("L20", 20, 20, 5, 5, 5, None, ("can",), ("setPosition", "setSpeed", "setCurrent")),
    "G20": ModelSpec("G20", 20, 20, 20, 5, None, 5, ("can",), ("setPosition", "setSpeed", "setTorque")),
    "L21": ModelSpec("L21", 25, 25, 21, 25, None, 5, ("can",), ("setPosition", "setSpeed", "setTorque")),
    "L25": ModelSpec("L25", 25, 25, 21, 25, None, 5, ("can",), ("setPosition", "setSpeed", "setTorque")),
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return str(value)


class BaseAdapter:
    def __init__(self, model: str, hand: str, transport: dict[str, Any]):
        self.model = model
        self.hand = hand
        self.transport = transport
        self.spec = MODEL_SPECS[model]
        self.connected = False
        self.last_position = [255] * self.spec.position_length

    def capabilities(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "hand": self.hand,
            "positionLength": self.spec.position_length,
            "speedLength": self.spec.speed_length,
            "currentLength": self.spec.current_length,
            "speedCommandLength": self.spec.speed_command_length,
            "currentCommandLength": self.spec.current_command_length,
            "torqueCommandLength": self.spec.torque_command_length,
            "positionRange": {"min": 0, "max": 255},
            "speedRange": {"min": 0, "max": 255},
            "currentRange": {"min": 0, "max": 255},
            "transports": list(self.spec.transports),
            "readCapabilities": ["position", "current", "speed", "touch"],
            "writeCapabilities": list(self.spec.write_capabilities),
        }

    def _require_connected(self) -> None:
        if not self.connected:
            raise AdapterError("NOT_CONNECTED", "device is not connected", retryable=True)

    def connect(self) -> dict[str, Any]:
        self.connected = True
        return self.capabilities()

    def disconnect(self) -> None:
        self.connected = False

    def close(self) -> None:
        self.disconnect()

    def get_position(self) -> Any: raise NotImplementedError
    def get_current(self) -> Any: raise NotImplementedError
    def get_speed(self) -> Any: raise NotImplementedError
    def get_touch(self) -> Any: raise NotImplementedError
    def set_position(self, values: list[int | float]) -> None: raise NotImplementedError
    def set_speed(self, values: list[int | float]) -> None: raise NotImplementedError
    def set_current(self, values: list[int | float]) -> None: raise NotImplementedError
    def set_torque(self, values: list[int | float]) -> None: raise NotImplementedError


class FakeAdapter(BaseAdapter):
    """Deterministic adapter used by tests and ``--fake`` development mode."""
    def __init__(self, model: str = "L10", hand: str = "left", transport: dict[str, Any] | None = None, noise: bool = False, output: Callable[[str], None] | None = None):
        super().__init__(model, hand, transport or {"type": "can", "channel": "fake"})
        self.position = [255] * self.spec.position_length
        self.speed = [100] * self.spec.speed_length
        self.current = [0] * self.spec.current_length
        self.touch = [0] * self.spec.position_length
        self.calls: list[str] = []
        self.noise = noise
        self.output = output or (lambda _text: None)
        self._lock = threading.Lock()

    def _call(self, name: str) -> None:
        with self._lock:
            self.calls.append(name)
        if self.noise:
            self.output(f"fake-sdk:{name}\n")

    def connect(self) -> dict[str, Any]: self._call("connect"); return super().connect()
    def disconnect(self) -> None: self._call("disconnect"); super().disconnect()
    def close(self) -> None: self._call("close"); super().close()
    def get_position(self) -> Any: self._require_connected(); self._call("getPosition"); return list(self.position)
    def get_current(self) -> Any: self._require_connected(); self._call("getCurrent"); return list(self.current)
    def get_speed(self) -> Any: self._require_connected(); self._call("getSpeed"); return list(self.speed)
    def get_touch(self) -> Any: self._require_connected(); self._call("getTouch"); return list(self.touch)
    def set_position(self, values): self._require_connected(); self._call("setPosition"); self.position = list(values)
    def set_speed(self, values): self._require_connected(); self._call("setSpeed"); self.speed = list(values)
    def set_current(self, values): self._require_connected(); self._call("setCurrent"); self.current = list(values)
    def set_torque(self, values): self._require_connected(); self._call("setTorque")


class RealSdkAdapter(BaseAdapter):
    def __init__(self, model: str, hand: str, transport: dict[str, Any], sdk_root: str | None = None, output: Callable[[str], None] | None = None):
        super().__init__(model, hand, transport)
        self.sdk_root = sdk_root
        self.output = output or (lambda _text: None)
        self.sdk: Any = None

    def _dispose_sdk(self) -> None:
        sdk, self.sdk = self.sdk, None
        self.connected = False
        if sdk is None:
            return
        method = "close" if hasattr(sdk, "close") else "close_can"
        if hasattr(sdk, method):
            try:
                self._capture(lambda: getattr(sdk, method)())
            except AdapterError:
                # Preserve the connect/command error that triggered cleanup.
                pass

    def _capture(self, fn: Callable[[], Any]) -> Any:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                return fn()
        except Exception as exc:
            if isinstance(exc, AdapterError): raise
            raise AdapterError("SDK_ERROR", str(exc), retryable=True) from exc
        finally:
            text = captured.getvalue()
            if text: self.output(text)

    def connect(self) -> dict[str, Any]:
        if self.connected: return self.capabilities()
        transport_type = self.transport["type"]
        root = Path(self.sdk_root).resolve() if self.sdk_root else Path(__file__).resolve().parents[5]
        for path in (root, root / "LinkerHand"):
            if str(path) not in sys.path: sys.path.insert(0, str(path))
        try:
            api_class = importlib.import_module("LinkerHand.linker_hand_api").LinkerHandApi
            kwargs = {"hand_type": self.hand, "hand_joint": self.model}
            if transport_type == "can": kwargs["can"] = self.transport["channel"]
            else: kwargs["modbus"] = self.transport["port"]
            self.sdk = self._capture(lambda: api_class(**kwargs))
            probe = getattr(self.sdk, "probe_connection", None)
            if probe is not None and not self._capture(probe):
                raise AdapterError(
                    "DEVICE_NOT_RESPONDING",
                    "USB-CAN opened, but the configured hand did not answer a probe",
                    retryable=True,
                )
            self.connected = True
            return self.capabilities()
        except AdapterError:
            self._dispose_sdk()
            raise
        except Exception as exc:
            self._dispose_sdk()
            raise AdapterError("SDK_UNAVAILABLE", f"could not load or connect SDK: {exc}", retryable=True) from exc

    def _invoke(self, method: str, *args, **kwargs) -> Any:
        self._require_connected()
        if not hasattr(self.sdk, method):
            raise AdapterError("UNSUPPORTED_CAPABILITY", f"SDK does not provide {method}")
        return _jsonable(self._capture(lambda: getattr(self.sdk, method)(*args, **kwargs)))

    def get_position(self): return self._invoke("get_state")
    def get_current(self): return self._invoke("get_current")
    def get_speed(self): return self._invoke("get_joint_speed")
    def get_touch(self): return self._invoke("get_touch")
    def set_position(self, values):
        accepted = self._invoke("finger_move", values)
        if accepted is False:
            raise AdapterError("COMMAND_REJECTED", "SDK rejected the position command", retryable=False)
        self.last_position = list(values)
    def set_speed(self, values): self._invoke("set_speed", values)
    def set_current(self, values): self._invoke("set_current", values)
    def set_torque(self, values): self._invoke("set_torque", values)
    def disconnect(self):
        self._dispose_sdk()
    def close(self): self.disconnect()


def build_adapter(model: str, hand: str, transport: dict[str, Any], *, mode: str = "real", sdk_root: str | None = None, output: Callable[[str], None] | None = None) -> BaseAdapter:
    if mode == "fake": return FakeAdapter(model, hand, transport, output=output)
    return RealSdkAdapter(model, hand, transport, sdk_root=sdk_root, output=output)
