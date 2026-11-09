"""Conveyor inspection cycle orchestration (PC side of the handshake).

part arrives -> PLC sets TRIGGER -> PC inspects with the shared DetectionEngine ->
PC writes result registers and PASS/REJECT coil -> PLC actuates reject pusher / restarts conveyor.
Any failure of the inspection itself results in a fail-safe REJECT.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .client import PlcClient, PlcSnapshot

log = logging.getLogger("plc.controller")


class Outcome(Protocol):
    decision: str
    defect_count: int
    top_class_id: int | None
    top_confidence: float
    inspection_id: str | None


@dataclass
class CycleResult:
    status: str  # completed | blocked_estop | trigger_timeout | ack_timeout | estop_during_cycle
    decision: str | None = None
    failsafe: bool = False
    inspection_id: str | None = None
    plc_cycle_id: int | None = None
    events: list[dict] = field(default_factory=list)
    before: dict | None = None
    after: dict | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status, "decision": self.decision, "failsafe_reject": self.failsafe,
            "inspection_id": self.inspection_id, "plc_cycle_id": self.plc_cycle_id, "events": self.events,
            "plc_before": self.before, "plc_after": self.after, "duration_ms": round(self.duration_ms, 1),
        }


class InspectionController:
    def __init__(self, client: PlcClient, analyze: Callable[[bytes], Outcome], *, trigger_timeout_s: float = 3.0,
                 ack_timeout_s: float = 3.0, poll_s: float = 0.02, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.analyze = analyze
        self.trigger_timeout_s = trigger_timeout_s
        self.ack_timeout_s = ack_timeout_s
        self.poll_s = poll_s
        self._sleep = sleep

    def _wait(self, predicate: Callable[[PlcSnapshot], bool], timeout_s: float) -> PlcSnapshot | None:
        deadline = time.monotonic() + timeout_s
        while True:
            snap = self.client.snapshot()
            if predicate(snap):
                return snap
            if time.monotonic() >= deadline:
                return None
            self._sleep(self.poll_s)

    def run_cycle(self, image_provider: Callable[[], bytes], *, simulate_part: bool = True) -> CycleResult:
        t0 = time.perf_counter()
        res = CycleResult(status="completed")

        def ev(name: str, detail: str = "") -> None:
            res.events.append({"t_ms": round((time.perf_counter() - t0) * 1000, 1), "event": name, "detail": detail})

        before = self.client.snapshot()
        res.before = before.to_dict()
        if before.estop:
            ev("blocked", "emergency stop is active; no cycle started")
            res.status = "blocked_estop"
            res.duration_ms = (time.perf_counter() - t0) * 1000
            return res
        if simulate_part:
            self.client.pulse_part_sensor()
            ev("part_presented", "simulated photo-eye triggered")
        snap = self._wait(lambda s: s.trigger or s.estop, self.trigger_timeout_s)
        if snap is None or not snap.trigger:
            res.status = "estop_during_cycle" if snap and snap.estop else "trigger_timeout"
            ev("no_trigger", "PLC did not raise the inspection trigger" if snap is None else "emergency stop pressed")
            res.after = (snap or self.client.snapshot()).to_dict()
            res.duration_ms = (time.perf_counter() - t0) * 1000
            return res
        res.plc_cycle_id = snap.registers["CYCLE_ID"]
        ev("trigger_received", f"PLC cycle {res.plc_cycle_id}")

        try:
            outcome = self.analyze(image_provider())
            decision, count, cls, conf = outcome.decision, outcome.defect_count, outcome.top_class_id, outcome.top_confidence
            res.inspection_id = outcome.inspection_id
            ev("inspection_done", f"{decision}; defects={count}")
        except Exception as exc:  # noqa: BLE001 - any failure -> fail-safe reject
            log.exception("inspection failed; sending fail-safe REJECT")
            decision, count, cls, conf = "REJECT", 0, None, 0.0
            res.failsafe = True
            ev("inspection_error", f"{type(exc).__name__}: {exc}; fail-safe REJECT")
        res.decision = decision

        self.client.write_result(decision, cls, count, conf)
        ev("result_written", decision)
        done = self._wait(lambda s: (not s.trigger) or s.estop, self.ack_timeout_s)
        if done is None:
            res.status = "ack_timeout"
            ev("ack_timeout", "PLC did not acknowledge the result")
        elif done.estop and done.trigger is False and done.registers["COMPONENT_STATUS"] not in (2, 3):
            res.status = "estop_during_cycle"
            ev("estop", "emergency stop pressed before acknowledgement")
        else:
            ev("plc_ack", f"component status {done.to_dict()['component_status']}")
        res.after = (done or self.client.snapshot()).to_dict()
        res.duration_ms = (time.perf_counter() - t0) * 1000
        return res
