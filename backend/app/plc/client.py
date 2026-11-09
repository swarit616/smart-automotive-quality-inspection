"""Modbus TCP client with retry, timeout and event logging.

Two interchangeable low-level transports:
  * SocketModbus      - dependency-free implementation (default; used by the tests)
  * PyModbusAdapter   - wraps `pymodbus` (optional; see requirements-optional.txt)
`PlcClient` adds retry/backoff, reconnection and event reporting on top of either.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .modbus_protocol import mbap, pack_bits, unpack_bits
from .registers import (NO_DEFECT_CLASS, Coil, ComponentStatus, MachineState, Reg, ResultCode)

log = logging.getLogger("plc.client")
LOOPBACK_NAMES = {"localhost"}


class PlcError(Exception):
    """Base class for PLC communication problems."""


class PlcCommunicationError(PlcError):
    """Connection refused/reset or retries exhausted."""


class PlcTimeoutError(PlcCommunicationError):
    """No response within the configured timeout."""


class PlcProtocolError(PlcError):
    """The PLC answered with a Modbus exception (not retried)."""

    def __init__(self, function: int, code: int):
        super().__init__(f"modbus exception code {code} for function 0x{function:02X}")
        self.function, self.code = function, code


def validate_plc_target(host: str, allow_non_local: bool) -> None:
    """Never connect to arbitrary machines by default: only loopback unless explicitly allowed."""
    if allow_non_local:
        return
    if host in LOOPBACK_NAMES:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(
        f"refusing to connect to {host!r}: only loopback targets are allowed unless PLC_ALLOW_NON_LOCAL_HOST=true. "
        "Only enable this for a simulator or a test PLC you own; see docs/PLC_INTEGRATION.md (safety)."
    )


class SocketModbus:
    def __init__(self, host: str, port: int, unit_id: int = 1, timeout_s: float = 2.0):
        self.host, self.port, self.unit_id, self.timeout_s = host, port, unit_id, timeout_s
        self._sock: socket.socket | None = None
        self._tid = 0
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        except socket.timeout as exc:
            raise PlcTimeoutError(f"connect to {self.host}:{self.port} timed out") from exc
        except OSError as exc:
            raise PlcCommunicationError(f"cannot connect to {self.host}:{self.port}: {exc}") from exc
        s.settimeout(self.timeout_s)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _recv(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise PlcCommunicationError("connection closed by PLC")
            buf += chunk
        return buf

    def _txn(self, pdu: bytes) -> bytes:
        with self._lock:
            if self._sock is None:
                raise PlcCommunicationError("not connected")
            self._tid = (self._tid + 1) & 0xFFFF
            try:
                self._sock.sendall(mbap(self._tid, self.unit_id, pdu))
                head = self._recv(7)
                tid, proto, length, _unit = struct.unpack(">HHHB", head)
                body = self._recv(length - 1)
            except socket.timeout as exc:
                self.close()
                raise PlcTimeoutError(f"no response within {self.timeout_s}s") from exc
            except PlcCommunicationError:
                self.close()
                raise
            except OSError as exc:
                self.close()
                raise PlcCommunicationError(f"socket error: {exc}") from exc
            if tid != self._tid or proto != 0:
                self.close()
                raise PlcCommunicationError("mismatched transaction/protocol id in response")
            if body[0] & 0x80:
                raise PlcProtocolError(body[0] & 0x7F, body[1] if len(body) > 1 else 0)
            if body[0] != pdu[0]:
                self.close()
                raise PlcCommunicationError("unexpected function code in response")
            return body

    def read_coils(self, address: int, count: int) -> list[bool]:
        body = self._txn(struct.pack(">BHH", 0x01, address, count))
        return unpack_bits(body[2 : 2 + body[1]], count)

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        body = self._txn(struct.pack(">BHH", 0x03, address, count))
        return list(struct.unpack(f">{count}H", body[2 : 2 + body[1]]))

    def write_coil(self, address: int, value: bool) -> None:
        self._txn(struct.pack(">BHH", 0x05, address, 0xFF00 if value else 0))

    def write_register(self, address: int, value: int) -> None:
        self._txn(struct.pack(">BHH", 0x06, address, value & 0xFFFF))

    def write_registers(self, address: int, values: list[int]) -> None:
        self._txn(struct.pack(f">BHHB{len(values)}H", 0x10, address, len(values), len(values) * 2, *[v & 0xFFFF for v in values]))

    def write_coils(self, address: int, values: list[bool]) -> None:
        self._txn(struct.pack(">BHHB", 0x0F, address, len(values), (len(values) + 7) // 8) + pack_bits(values))


class PyModbusAdapter:  # pragma: no cover - optional dependency, not exercised by the offline test suite
    """Same interface as SocketModbus, implemented with pymodbus 3.x (tested API: pymodbus==3.7.4)."""

    def __init__(self, host: str, port: int, unit_id: int = 1, timeout_s: float = 2.0):
        from pymodbus.client import ModbusTcpClient  # lazy import

        self._c = ModbusTcpClient(host, port=port, timeout=timeout_s)
        self.unit_id = unit_id

    @property
    def connected(self) -> bool:
        return bool(self._c.connected)

    def connect(self) -> None:
        if not self._c.connect():
            raise PlcCommunicationError("pymodbus could not connect")

    def close(self) -> None:
        self._c.close()

    def _ok(self, rsp):
        if rsp is None or rsp.isError():
            raise PlcCommunicationError(f"pymodbus error: {rsp}")
        return rsp

    def read_coils(self, address: int, count: int) -> list[bool]:
        return list(self._ok(self._c.read_coils(address, count=count, slave=self.unit_id)).bits[:count])

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return list(self._ok(self._c.read_holding_registers(address, count=count, slave=self.unit_id)).registers)

    def write_coil(self, address: int, value: bool) -> None:
        self._ok(self._c.write_coil(address, value, slave=self.unit_id))

    def write_register(self, address: int, value: int) -> None:
        self._ok(self._c.write_register(address, value, slave=self.unit_id))

    def write_registers(self, address: int, values: list[int]) -> None:
        self._ok(self._c.write_registers(address, values, slave=self.unit_id))

    def write_coils(self, address: int, values: list[bool]) -> None:
        self._ok(self._c.write_coils(address, values, slave=self.unit_id))


@dataclass
class PlcSnapshot:
    coils: dict[str, bool]
    registers: dict[str, int]
    taken_at: float = field(default_factory=time.time)

    @property
    def trigger(self) -> bool:
        return self.coils["TRIGGER"]

    @property
    def estop(self) -> bool:
        return self.coils["ESTOP"]

    @property
    def machine_state(self) -> str:
        v = self.registers["MACHINE_STATE"]
        return MachineState(v).name if v in iter(MachineState) else f"UNKNOWN({v})"

    def to_dict(self) -> dict:
        r = self.registers
        return {
            "coils": self.coils,
            "registers": r,
            "machine_state": self.machine_state,
            "conveyor_running": self.coils["CONVEYOR_RUN"],
            "estop": self.estop,
            "trigger": self.trigger,
            "pass_signal": self.coils["PASS_SIGNAL"],
            "reject_signal": self.coils["REJECT_SIGNAL"],
            "reject_actuator": self.coils["REJECT_ACTUATOR"],
            "inspection_result": ResultCode(r["INSPECTION_RESULT"]).name if r["INSPECTION_RESULT"] in iter(ResultCode) else str(r["INSPECTION_RESULT"]),
            "component_status": ComponentStatus(r["COMPONENT_STATUS"]).name if r["COMPONENT_STATUS"] in iter(ComponentStatus) else str(r["COMPONENT_STATUS"]),
            "counters": {"components": r["COMPONENT_COUNTER"], "passed": r["PASS_COUNTER"], "rejected": r["REJECT_COUNTER"]},
            "heartbeat": r["HEARTBEAT"],
            "cycle_id": r["CYCLE_ID"],
            "taken_at": self.taken_at,
        }


EventSink = Callable[[dict], None]


class PlcClient:
    """High-level PLC access with retry/backoff and structured event reporting."""

    def __init__(self, low, *, retries: int = 3, backoff_s: float = 0.1, on_event: EventSink | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.low = low
        self.retries = retries
        self.backoff_s = backoff_s
        self.on_event = on_event or (lambda e: None)
        self._sleep = sleep

    # -- events ------------------------------------------------------------
    def _emit(self, type_: str, ok: bool, detail: str, started: float | None = None, **extra) -> None:
        ev = {"type": type_, "ok": ok, "detail": detail,
              "duration_ms": round((time.perf_counter() - started) * 1000, 2) if started else None, **extra}
        (log.info if ok else log.warning)("PLC %s ok=%s %s", type_, ok, detail)
        try:
            self.on_event(ev)
        except Exception:  # noqa: BLE001 - event sinks must never break control flow
            log.exception("event sink failed")

    # -- connection --------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.low.connected

    def connect(self) -> None:
        started = time.perf_counter()
        try:
            self.low.connect()
        except PlcError as exc:
            self._emit("connect", False, str(exc), started)
            raise
        self._emit("connect", True, "connected", started)

    def close(self) -> None:
        self.low.close()
        self._emit("disconnect", True, "connection closed")

    def _call(self, name: str, fn, *args):
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                if not self.low.connected:
                    self.low.connect()
                result = fn(*args)
                if attempt:
                    self._emit(name, True, f"succeeded after {attempt} retr{'y' if attempt == 1 else 'ies'}", started)
                return result
            except PlcProtocolError as exc:
                self._emit(name, False, str(exc), started)
                raise
            except PlcCommunicationError as exc:
                last = exc
                self._emit(name, False, f"attempt {attempt + 1}/{self.retries + 1} failed: {exc}", started)
                self.low.close()
                if attempt < self.retries:
                    self._sleep(self.backoff_s * (2 ** attempt))
        assert last is not None
        raise (PlcTimeoutError if isinstance(last, PlcTimeoutError) else PlcCommunicationError)(
            f"{name} failed after {self.retries + 1} attempts: {last}"
        ) from last

    # -- raw access --------------------------------------------------------
    def read_coils(self, address: int, count: int) -> list[bool]:
        return self._call("read_coils", self.low.read_coils, address, count)

    def read_registers(self, address: int, count: int) -> list[int]:
        return self._call("read_registers", self.low.read_holding_registers, address, count)

    def write_coil(self, address: int, value: bool) -> None:
        self._call("write_coil", self.low.write_coil, address, value)

    def write_registers(self, address: int, values: list[int]) -> None:
        self._call("write_registers", self.low.write_registers, address, values)

    # -- station semantics -------------------------------------------------
    def snapshot(self) -> PlcSnapshot:
        coils = self.read_coils(0, len(Coil))
        regs = self.read_registers(0, len(Reg))
        return PlcSnapshot({c.name: bool(coils[c]) for c in Coil}, {r.name: int(regs[r]) for r in Reg})

    def pulse_part_sensor(self) -> None:
        """SIMULATION ONLY: raise the simulated photo-eye input."""
        self.write_coil(Coil.PART_SENSOR_SIM, True)

    def write_result(self, result: str, defect_class_id: int | None, defect_count: int, confidence: float) -> None:
        code = ResultCode.PASS if result == "PASS" else ResultCode.REJECT
        conf = max(0, min(1000, int(round(confidence * 1000))))
        cls = NO_DEFECT_CLASS if defect_class_id is None else defect_class_id & 0xFFFF
        self.write_registers(Reg.INSPECTION_RESULT, [int(code), cls, min(defect_count, 0xFFFF), conf])
        self.write_coil(Coil.REJECT_SIGNAL if code == ResultCode.REJECT else Coil.PASS_SIGNAL, True)
        self._emit("result_sent", True, f"{result} (defects={defect_count}, confidence={conf / 1000:.3f})", result=result)

    def set_estop(self, pressed: bool) -> None:
        self.write_coil(Coil.ESTOP, pressed)
        self._emit("estop", True, "emergency stop PRESSED" if pressed else "emergency stop RELEASED", pressed=pressed)
