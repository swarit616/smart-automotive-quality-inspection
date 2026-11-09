import socket
import threading
import unittest
from dataclasses import dataclass

from app.plc.client import (PlcClient, PlcCommunicationError, PlcProtocolError, PlcTimeoutError, SocketModbus,
                            validate_plc_target)
from app.plc.controller import InspectionController
from app.plc.modbus_protocol import ModbusException, pack_bits, process_pdu, unpack_bits
from app.plc.registers import NO_DEFECT_CLASS, Coil, ComponentStatus, MachineState, Reg, ResultCode
from app.plc.simulator import PlcDataStore, PlcLogic, PlcSimulator


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.store = PlcDataStore()

    def test_bit_packing_roundtrip(self):
        bits = [True, False, True, True, False, False, False, False, True]
        self.assertEqual(unpack_bits(pack_bits(bits), 9), bits)

    def test_write_then_read_registers(self):
        process_pdu(bytes([0x10, 0, 20, 0, 2, 4, 0, 1, 0, 2]), self.store)
        rsp = process_pdu(bytes([0x03, 0, 20, 0, 2]), self.store)
        self.assertEqual(rsp, bytes([0x03, 4, 0, 1, 0, 2]))

    def test_write_single_coil_values(self):
        process_pdu(bytes([0x05, 0, 3, 0xFF, 0]), self.store)
        self.assertTrue(self.store.coils[3])
        with self.assertRaises(ModbusException) as cm:
            process_pdu(bytes([0x05, 0, 3, 0x12, 0x34]), self.store)
        self.assertEqual(cm.exception.code, 3)

    def test_illegal_function_address_and_quantity(self):
        for pdu, code in ((bytes([0x2B]), 1), (bytes([0x03, 0, 31, 0, 5]), 2), (bytes([0x03, 0, 0, 0, 0]), 3),
                          (bytes([0x03, 0, 0]), 3), (bytes([0x01, 0xFF, 0xFF, 0, 1]), 2)):
            with self.assertRaises(ModbusException) as cm:
                process_pdu(pdu, self.store)
            self.assertEqual(cm.exception.code, code, pdu)


class LogicTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = PlcDataStore()
        self.logic = PlcLogic(self.store, actuator_pulse_s=0.5, inspection_timeout_s=5.0, clock=self.clock)

    def part(self):
        self.store.write_coils(Coil.PART_SENSOR_SIM, [True])

    def test_part_arrival_sets_trigger_and_stops_conveyor(self):
        self.part()
        self.assertTrue(self.store.coils[Coil.TRIGGER])
        self.assertFalse(self.store.coils[Coil.CONVEYOR_RUN])
        self.assertEqual(self.store.regs[Reg.MACHINE_STATE], MachineState.INSPECTING)
        self.assertEqual(self.store.regs[Reg.COMPONENT_STATUS], ComponentStatus.PRESENT)
        self.assertEqual(self.store.regs[Reg.COMPONENT_COUNTER], 1)

    def test_pass_cycle(self):
        self.part()
        self.store.write_coils(Coil.PASS_SIGNAL, [True])
        r = self.store.regs
        self.assertEqual((r[Reg.PASS_COUNTER], r[Reg.REJECT_COUNTER], r[Reg.COMPONENT_STATUS]), (1, 0, ComponentStatus.INSPECTED_OK))
        self.assertFalse(self.store.coils[Coil.TRIGGER])
        self.assertTrue(self.store.coils[Coil.CONVEYOR_RUN])
        self.assertFalse(self.store.coils[Coil.REJECT_ACTUATOR])

    def test_reject_cycle_pulses_actuator(self):
        self.part()
        self.store.write_coils(Coil.REJECT_SIGNAL, [True])
        self.assertTrue(self.store.coils[Coil.REJECT_ACTUATOR])
        self.assertEqual(self.store.regs[Reg.COMPONENT_STATUS], ComponentStatus.REJECTED)
        self.clock.t = 0.6
        self.logic.scan()
        self.assertFalse(self.store.coils[Coil.REJECT_ACTUATOR])

    def test_signal_without_trigger_is_ignored(self):
        self.store.write_coils(Coil.REJECT_SIGNAL, [True])
        self.assertEqual(self.store.regs[Reg.REJECT_COUNTER], 0)
        self.assertFalse(self.store.coils[Coil.REJECT_ACTUATOR])

    def test_estop_blocks_and_releases(self):
        self.store.write_coils(Coil.ESTOP, [True])
        self.assertEqual(self.store.regs[Reg.MACHINE_STATE], MachineState.ESTOP)
        self.assertFalse(self.store.coils[Coil.CONVEYOR_RUN])
        self.part()
        self.assertFalse(self.store.coils[Coil.TRIGGER])
        self.store.write_coils(Coil.ESTOP, [False])
        self.assertEqual(self.store.regs[Reg.MACHINE_STATE], MachineState.RUNNING)
        self.assertTrue(self.store.coils[Coil.CONVEYOR_RUN])

    def test_estop_mid_cycle_clears_trigger(self):
        self.part()
        self.store.write_coils(Coil.ESTOP, [True])
        self.assertFalse(self.store.coils[Coil.TRIGGER])

    def test_watchdog_rejects_part_failsafe(self):
        self.part()
        self.clock.t = 6.0
        self.logic.scan()
        r = self.store.regs
        self.assertEqual((r[Reg.REJECT_COUNTER], r[Reg.MACHINE_STATE], r[Reg.INSPECTION_RESULT]), (1, MachineState.FAULT, ResultCode.REJECT))
        self.assertFalse(self.store.coils[Coil.TRIGGER])

    def test_counters_wrap(self):
        self.store.regs[Reg.COMPONENT_COUNTER] = 0xFFFF
        self.part()
        self.assertEqual(self.store.regs[Reg.COMPONENT_COUNTER], 0)


@dataclass
class FakeOutcome:
    decision: str
    defect_count: int = 0
    top_class_id: int | None = None
    top_confidence: float = 0.0
    inspection_id: str | None = "insp-1"


class ModbusOverTcpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = PlcSimulator("127.0.0.1", 0, scan_interval_s=0.02, actuator_pulse_s=0.2, inspection_timeout_s=30).start()

    @classmethod
    def tearDownClass(cls):
        cls.sim.stop()

    def setUp(self):
        self.events = []
        self.client = PlcClient(SocketModbus("127.0.0.1", self.sim.port, timeout_s=1.0), retries=1, backoff_s=0.01, on_event=self.events.append)
        self.client.connect()
        with self.sim.store.lock:  # return the simulator to a clean state between tests
            self.sim.store.coils[:] = [False] * len(self.sim.store.coils)
            self.sim.store.coils[Coil.CONVEYOR_RUN] = True
            self.sim.store.regs[Reg.MACHINE_STATE] = MachineState.RUNNING
        self.sim.logic._prev_pass = self.sim.logic._prev_reject = False

    def tearDown(self):
        self.client.close()

    def test_snapshot_over_tcp(self):
        snap = self.client.snapshot()
        self.assertEqual(snap.machine_state, "RUNNING")
        self.assertTrue(snap.to_dict()["conveyor_running"])

    def test_protocol_exception_is_raised_not_retried(self):
        with self.assertRaises(PlcProtocolError) as cm:
            self.client.read_registers(500, 2)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(sum(1 for e in self.events if e["type"] == "read_registers" and not e["ok"]), 1)

    def test_full_controller_cycle_pass_and_reject(self):
        for decision, status in (("PASS", "INSPECTED_OK"), ("REJECT", "REJECTED")):
            ctl = InspectionController(self.client, lambda b, d=decision: FakeOutcome(d, 1 if d == "REJECT" else 0, 0 if d == "REJECT" else None, 0.91 if d == "REJECT" else 0.0),
                                       trigger_timeout_s=2, ack_timeout_s=2, poll_s=0.01)
            res = ctl.run_cycle(lambda: b"img")
            self.assertEqual((res.status, res.decision, res.failsafe), ("completed", decision, False), res.events)
            self.assertEqual(res.after["component_status"], status)
            self.assertEqual([e["event"] for e in res.events][:3], ["part_presented", "trigger_received", "inspection_done"])
        snap = self.client.snapshot()
        self.assertEqual((snap.registers["PASS_COUNTER"] >= 1, snap.registers["REJECT_COUNTER"] >= 1), (True, True))
        self.assertEqual(snap.registers["CONFIDENCE_X1000"], 910)
        self.assertEqual(snap.registers["DEFECT_COUNT"], 1)

    def test_pass_result_registers(self):
        ctl = InspectionController(self.client, lambda b: FakeOutcome("PASS"), trigger_timeout_s=2, ack_timeout_s=2, poll_s=0.01)
        ctl.run_cycle(lambda: b"img")
        r = self.client.snapshot().registers
        self.assertEqual((r["INSPECTION_RESULT"], r["DEFECT_CLASS_ID"]), (ResultCode.PASS, NO_DEFECT_CLASS))

    def test_inspection_failure_sends_failsafe_reject(self):
        def boom(_):
            raise RuntimeError("model crashed")
        res = InspectionController(self.client, boom, trigger_timeout_s=2, ack_timeout_s=2, poll_s=0.01).run_cycle(lambda: b"img")
        self.assertEqual((res.status, res.decision, res.failsafe), ("completed", "REJECT", True))
        self.assertEqual(res.after["component_status"], "REJECTED")
        self.assertTrue(any(e["event"] == "inspection_error" for e in res.events))

    def test_cycle_blocked_by_estop_and_recovers(self):
        self.client.set_estop(True)
        called = []
        ctl = InspectionController(self.client, lambda b: called.append(1) or FakeOutcome("PASS"), trigger_timeout_s=1, ack_timeout_s=1, poll_s=0.01)
        res = ctl.run_cycle(lambda: b"img")
        self.assertEqual((res.status, called), ("blocked_estop", []))
        self.client.set_estop(False)
        self.assertEqual(ctl.run_cycle(lambda: b"img").status, "completed")

    def test_trigger_timeout_when_no_part(self):
        ctl = InspectionController(self.client, lambda b: FakeOutcome("PASS"), trigger_timeout_s=0.2, ack_timeout_s=0.2, poll_s=0.01)
        self.assertEqual(ctl.run_cycle(lambda: b"img", simulate_part=False).status, "trigger_timeout")


class FailureHandlingTests(unittest.TestCase):
    def test_connection_refused_retries_then_raises(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()  # a port with no listener
        sleeps, events = [], []
        c = PlcClient(SocketModbus("127.0.0.1", port, timeout_s=0.3), retries=2, backoff_s=0.05, on_event=events.append, sleep=sleeps.append)
        with self.assertRaises(PlcCommunicationError):
            c.read_coils(0, 1)
        self.assertEqual(sleeps, [0.05, 0.1])  # exponential backoff
        self.assertEqual(len([e for e in events if not e["ok"]]), 3)

    def test_timeout_is_reported_as_timeout(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        held = []
        threading.Thread(target=lambda: held.append(srv.accept()), daemon=True).start()  # accepts but never answers
        c = PlcClient(SocketModbus("127.0.0.1", srv.getsockname()[1], timeout_s=0.2), retries=0)
        with self.assertRaises(PlcTimeoutError):
            c.read_coils(0, 1)
        srv.close()

    def test_recovers_after_plc_restart(self):
        sim = PlcSimulator("127.0.0.1", 0).start()
        port = sim.port
        c = PlcClient(SocketModbus("127.0.0.1", port, timeout_s=0.5), retries=2, backoff_s=0.01)
        c.connect()
        self.assertEqual(c.snapshot().machine_state, "RUNNING")
        sim.stop()
        with self.assertRaises(PlcCommunicationError):
            c.snapshot()
        sim2 = PlcSimulator("127.0.0.1", port).start()
        try:
            self.assertEqual(c.snapshot().machine_state, "RUNNING")  # transparent reconnect
        finally:
            sim2.stop()

    def test_target_validation(self):
        validate_plc_target("127.0.0.1", False)
        validate_plc_target("localhost", False)
        validate_plc_target("::1", False)
        for host in ("192.168.1.10", "plc.factory.local", "10.0.0.5"):
            with self.assertRaises(ValueError):
                validate_plc_target(host, False)
        validate_plc_target("plc-simulator", True)

    def test_simulator_refuses_public_bind(self):
        with self.assertRaises(ValueError):
            PlcSimulator("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
