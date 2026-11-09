"""SOFTWARE-BASED PLC SIMULATOR (Modbus TCP server + simple inspection-station logic).

This is a simulator. It is not a physical PLC and has no safety certification. See
docs/PLC_INTEGRATION.md for how a real PLC differs.

Run standalone:   python -m app.plc.simulator --host 127.0.0.1 --port 5020
"""
from __future__ import annotations

import argparse
import logging
import socket
import socketserver
import threading
import time
from typing import Callable

from .modbus_protocol import ILLEGAL_ADDRESS, ModbusException, exception_pdu, mbap, process_pdu
from .registers import (NO_DEFECT_CLASS, NUM_COILS, NUM_REGISTERS, Coil, ComponentStatus, MachineState, Reg,
                        ResultCode)

log = logging.getLogger("plc.simulator")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class PlcDataStore:
    """Thread-safe coil/register tables. `after_write` is invoked after every write (PLC scan hook)."""

    def __init__(self) -> None:
        self.coils = [False] * NUM_COILS
        self.regs = [0] * NUM_REGISTERS
        self.lock = threading.RLock()
        self.after_write: Callable[[], None] | None = None

    def read_coils(self, address: int, count: int) -> list[bool]:
        with self.lock:
            self._check(address, count, NUM_COILS)
            return self.coils[address : address + count]

    def write_coils(self, address: int, values: list[bool]) -> None:
        with self.lock:
            self._check(address, len(values), NUM_COILS)
            self.coils[address : address + len(values)] = list(values)
            if self.after_write:
                self.after_write()

    def read_registers(self, address: int, count: int) -> list[int]:
        with self.lock:
            self._check(address, count, NUM_REGISTERS)
            return self.regs[address : address + count]

    def write_registers(self, address: int, values: list[int]) -> None:
        with self.lock:
            self._check(address, len(values), NUM_REGISTERS)
            self.regs[address : address + len(values)] = [v & 0xFFFF for v in values]
            if self.after_write:
                self.after_write()

    @staticmethod
    def _check(address: int, count: int, size: int) -> None:
        if address < 0 or count < 1 or address + count > size:
            raise ModbusException(ILLEGAL_ADDRESS, f"address {address}+{count} out of range")


class PlcLogic:
    """The 'ladder logic' of the simulated inspection station.

    * photo-eye rising edge (PART_SENSOR_SIM) -> part stops at station, TRIGGER set, state INSPECTING
    * PASS_SIGNAL / REJECT_SIGNAL (from the PC) -> counters, component status, reject pusher pulse,
      TRIGGER cleared, conveyor restarts
    * ESTOP -> conveyor off, triggers ignored, state ESTOP; released -> state IDLE/RUNNING
    * watchdog: if the PC does not answer within `inspection_timeout_s`, the part is rejected
      (fail-safe), state FAULT is flagged until the next good cycle.
    """

    def __init__(self, store: PlcDataStore, *, actuator_pulse_s: float = 0.5, inspection_timeout_s: float = 10.0,
                 clock: Callable[[], float] = time.monotonic):
        self.s = store
        self.actuator_pulse_s = actuator_pulse_s
        self.inspection_timeout_s = inspection_timeout_s
        self.clock = clock
        self._trigger_at: float | None = None
        self._actuator_off_at: float | None = None
        self._prev_pass = False
        self._prev_reject = False
        with store.lock:
            store.coils[Coil.CONVEYOR_RUN] = True
            store.regs[Reg.MACHINE_STATE] = MachineState.RUNNING
        store.after_write = self.scan

    def _c(self, c: Coil) -> bool:
        return self.s.coils[c]

    def _set(self, c: Coil, v: bool) -> None:
        self.s.coils[c] = v

    def scan(self) -> None:
        """One PLC scan; safe to call from any thread."""
        with self.s.lock:
            regs = self.s.regs
            now = self.clock()
            regs[Reg.HEARTBEAT] = (regs[Reg.HEARTBEAT] + 1) & 0xFFFF
            if self._actuator_off_at is not None and now >= self._actuator_off_at:
                self._set(Coil.REJECT_ACTUATOR, False)
                self._actuator_off_at = None
            # --- emergency stop (highest priority)
            if self._c(Coil.ESTOP):
                self._set(Coil.CONVEYOR_RUN, False)
                self._set(Coil.TRIGGER, False)
                self._set(Coil.PART_SENSOR_SIM, False)
                self._set(Coil.REJECT_ACTUATOR, False)
                self._trigger_at = None
                regs[Reg.MACHINE_STATE] = MachineState.ESTOP
                self._prev_pass, self._prev_reject = self._c(Coil.PASS_SIGNAL), self._c(Coil.REJECT_SIGNAL)
                return
            if regs[Reg.MACHINE_STATE] == MachineState.ESTOP:  # released
                self._set(Coil.CONVEYOR_RUN, True)
                regs[Reg.MACHINE_STATE] = MachineState.RUNNING
            # --- part arrives
            if self._c(Coil.PART_SENSOR_SIM):
                self._set(Coil.PART_SENSOR_SIM, False)
                if self._c(Coil.CONVEYOR_RUN) and not self._c(Coil.TRIGGER):
                    regs[Reg.COMPONENT_COUNTER] = (regs[Reg.COMPONENT_COUNTER] + 1) & 0xFFFF
                    regs[Reg.CYCLE_ID] = (regs[Reg.CYCLE_ID] + 1) & 0xFFFF
                    regs[Reg.COMPONENT_STATUS] = ComponentStatus.PRESENT
                    regs[Reg.INSPECTION_RESULT] = ResultCode.NONE
                    regs[Reg.DEFECT_CLASS_ID] = NO_DEFECT_CLASS
                    regs[Reg.DEFECT_COUNT] = 0
                    regs[Reg.CONFIDENCE_X1000] = 0
                    self._set(Coil.PASS_SIGNAL, False)
                    self._set(Coil.REJECT_SIGNAL, False)
                    self._prev_pass = self._prev_reject = False
                    self._set(Coil.TRIGGER, True)
                    self._set(Coil.CONVEYOR_RUN, False)  # part stops at the station
                    regs[Reg.MACHINE_STATE] = MachineState.INSPECTING
                    self._trigger_at = now
            # --- result signals from the PC (rising edges)
            rising_pass = self._c(Coil.PASS_SIGNAL) and not self._prev_pass
            rising_reject = self._c(Coil.REJECT_SIGNAL) and not self._prev_reject
            self._prev_pass, self._prev_reject = self._c(Coil.PASS_SIGNAL), self._c(Coil.REJECT_SIGNAL)
            if (rising_pass or rising_reject) and self._c(Coil.TRIGGER):
                if rising_reject:  # reject wins if both are set
                    self._reject_part(regs, now)
                else:
                    regs[Reg.PASS_COUNTER] = (regs[Reg.PASS_COUNTER] + 1) & 0xFFFF
                    regs[Reg.COMPONENT_STATUS] = ComponentStatus.INSPECTED_OK
                self._finish_cycle(regs)
            elif self._c(Coil.TRIGGER) and self._trigger_at is not None and now - self._trigger_at > self.inspection_timeout_s:
                log.warning("PLC watchdog: no inspection result within %.1fs; rejecting part (fail-safe)", self.inspection_timeout_s)
                self._reject_part(regs, now)
                regs[Reg.INSPECTION_RESULT] = ResultCode.REJECT
                self._finish_cycle(regs)
                regs[Reg.MACHINE_STATE] = MachineState.FAULT

    def _reject_part(self, regs: list[int], now: float) -> None:
        regs[Reg.REJECT_COUNTER] = (regs[Reg.REJECT_COUNTER] + 1) & 0xFFFF
        regs[Reg.COMPONENT_STATUS] = ComponentStatus.REJECTED
        self._set(Coil.REJECT_ACTUATOR, True)
        self._actuator_off_at = now + self.actuator_pulse_s

    def _finish_cycle(self, regs: list[int]) -> None:
        self._set(Coil.TRIGGER, False)
        self._trigger_at = None
        self._set(Coil.CONVEYOR_RUN, True)
        regs[Reg.MACHINE_STATE] = MachineState.RUNNING


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # one connection, many requests
        srv: "ModbusTcpServer" = self.server  # type: ignore[assignment]
        self.request.settimeout(30)
        srv.connections.add(self.request)
        try:
            self._serve(srv)
        finally:
            srv.connections.discard(self.request)

    def _serve(self, srv: "ModbusTcpServer") -> None:
        while True:
            try:
                header = self._recv(7)
                if header is None:
                    return
                tid, proto, length, unit = int.from_bytes(header[0:2], "big"), int.from_bytes(header[2:4], "big"), int.from_bytes(header[4:6], "big"), header[6]
                if proto != 0 or not 2 <= length <= 254:
                    return  # malformed framing: drop the connection
                pdu = self._recv(length - 1)
                if pdu is None:
                    return
                if unit not in (srv.unit_id, 0):
                    continue  # not addressed to us: stay silent like a real slave
                try:
                    resp = process_pdu(pdu, srv.store)
                except ModbusException as exc:
                    resp = exception_pdu(pdu[0] if pdu else 0, exc.code)
                self.request.sendall(mbap(tid, unit, resp))
            except (OSError, TimeoutError):
                return

    def _recv(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf


class ModbusTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int, store: PlcDataStore, unit_id: int = 1):
        super().__init__((host, port), _Handler)
        self.store = store
        self.unit_id = unit_id
        self.connections: set = set()

    def drop_connections(self) -> None:
        for c in list(self.connections):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass


class PlcSimulator:
    """Datastore + logic + TCP server + background scan thread."""

    IS_SIMULATOR = True

    def __init__(self, host: str = "127.0.0.1", port: int = 5020, unit_id: int = 1, *, allow_non_local: bool = False,
                 scan_interval_s: float = 0.1, actuator_pulse_s: float = 0.5, inspection_timeout_s: float = 10.0,
                 clock: Callable[[], float] = time.monotonic):
        if host not in LOOPBACK and not allow_non_local:
            raise ValueError("refusing to bind the PLC simulator to a non-loopback address without allow_non_local=True")
        self.store = PlcDataStore()
        self.logic = PlcLogic(self.store, actuator_pulse_s=actuator_pulse_s, inspection_timeout_s=inspection_timeout_s, clock=clock)
        self.server = ModbusTcpServer(host, port, self.store, unit_id)
        self.scan_interval_s = scan_interval_s
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    @property
    def host(self) -> str:
        return self.server.server_address[0]

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def start(self) -> "PlcSimulator":
        t1 = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True, name="plc-sim-server")
        t2 = threading.Thread(target=self._scan_loop, daemon=True, name="plc-sim-scan")
        for t in (t1, t2):
            t.start()
            self._threads.append(t)
        log.info("PLC SIMULATOR (not a real PLC) listening on %s:%s", self.host, self.port)
        return self

    def _scan_loop(self) -> None:
        while not self._stop.wait(self.scan_interval_s):
            self.logic.scan()

    def stop(self) -> None:
        self._stop.set()
        self.server.shutdown()
        self.server.drop_connections()  # like a powered-off PLC: established connections are lost
        self.server.server_close()

    def snapshot(self) -> dict:
        with self.store.lock:
            return {"coils": list(self.store.coils), "registers": list(self.store.regs)}


def main() -> None:  # pragma: no cover - CLI wrapper
    ap = argparse.ArgumentParser(description="Modbus TCP PLC simulator (NOT a real PLC)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--unit-id", type=int, default=1)
    ap.add_argument("--allow-non-local", action="store_true", help="allow binding to non-loopback addresses (e.g. inside Docker)")
    ap.add_argument("--auto-interval", type=float, default=0.0, help="simulate a part arriving every N seconds (0 = off)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sim = PlcSimulator(args.host, args.port, args.unit_id, allow_non_local=args.allow_non_local).start()
    print(f"PLC SIMULATOR running on {sim.host}:{sim.port} (unit {args.unit_id}). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.auto_interval if args.auto_interval > 0 else 1.0)
            if args.auto_interval > 0:
                with sim.store.lock:
                    sim.store.coils[Coil.PART_SENSOR_SIM] = True
                sim.logic.scan()
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()
