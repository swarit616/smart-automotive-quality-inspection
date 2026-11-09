"""Modbus register map of the SIMULATED inspection station PLC.

Addresses are zero-based protocol addresses (as sent on the wire). Documented in
docs/PLC_INTEGRATION.md. A real PLC would publish its own map; only this file would change.
"""
from __future__ import annotations

from enum import IntEnum

NUM_COILS = 16
NUM_REGISTERS = 32


class Coil(IntEnum):
    TRIGGER = 0            # PLC -> PC : part at inspection station, start inspection
    PASS_SIGNAL = 1        # PC  -> PLC: inspection passed
    REJECT_SIGNAL = 2      # PC  -> PLC: inspection failed, reject the part
    REJECT_ACTUATOR = 3    # PLC output: diverter / pusher energised (read-only for the PC)
    ESTOP = 4              # emergency-stop input (simulated mushroom button); 1 = pressed
    CONVEYOR_RUN = 5       # PLC output: conveyor motor running
    PART_SENSOR_SIM = 6    # SIMULATION ONLY: stands in for the photo-eye; self-resets


class Reg(IntEnum):
    MACHINE_STATE = 0       # MachineState
    INSPECTION_RESULT = 1   # ResultCode (written by PC)
    DEFECT_CLASS_ID = 2     # class id of top defect, 0xFFFF when none (written by PC)
    DEFECT_COUNT = 3        # number of reject-triggering defects (written by PC)
    CONFIDENCE_X1000 = 4    # top confidence * 1000 (written by PC)
    COMPONENT_STATUS = 5    # ComponentStatus (maintained by PLC)
    COMPONENT_COUNTER = 6   # parts presented, wraps at 65535
    PASS_COUNTER = 7
    REJECT_COUNTER = 8
    HEARTBEAT = 9           # incremented by the PLC scan
    CYCLE_ID = 10           # id of current/last inspection cycle


class MachineState(IntEnum):
    IDLE = 0
    RUNNING = 1
    INSPECTING = 2
    ESTOP = 3
    FAULT = 4


class ResultCode(IntEnum):
    NONE = 0
    PASS = 1
    REJECT = 2


class ComponentStatus(IntEnum):
    NONE = 0
    PRESENT = 1
    INSPECTED_OK = 2
    REJECTED = 3


NO_DEFECT_CLASS = 0xFFFF

REGISTER_DOC = [
    {"type": "coil", "address": int(c), "name": c.name, "access": acc, "description": desc}
    for c, acc, desc in [
        (Coil.TRIGGER, "PLC writes, PC reads", "Part present at inspection station; PC should inspect. Cleared by PLC when a result arrives."),
        (Coil.PASS_SIGNAL, "PC writes", "Set by PC when the part passed."),
        (Coil.REJECT_SIGNAL, "PC writes", "Set by PC when the part must be rejected."),
        (Coil.REJECT_ACTUATOR, "PLC writes, PC reads", "Reject pusher energised for a short pulse."),
        (Coil.ESTOP, "operator/PC writes (simulated)", "Emergency stop pressed. Conveyor stops, triggers are ignored."),
        (Coil.CONVEYOR_RUN, "PLC writes, PC reads", "Conveyor motor running."),
        (Coil.PART_SENSOR_SIM, "simulation only", "Simulated photo-eye input; the PLC logic consumes it and resets it."),
    ]
] + [
    {"type": "holding_register", "address": int(r), "name": r.name, "access": acc, "description": desc}
    for r, acc, desc in [
        (Reg.MACHINE_STATE, "PLC", "0=IDLE 1=RUNNING 2=INSPECTING 3=ESTOP 4=FAULT (uint16)"),
        (Reg.INSPECTION_RESULT, "PC", "0=none 1=PASS 2=REJECT (uint16)"),
        (Reg.DEFECT_CLASS_ID, "PC", "Class id of the most confident reject-triggering defect; 65535 = none (uint16)"),
        (Reg.DEFECT_COUNT, "PC", "Number of reject-triggering defects (uint16)"),
        (Reg.CONFIDENCE_X1000, "PC", "Top confidence/score x 1000 (uint16, 0-1000)"),
        (Reg.COMPONENT_STATUS, "PLC", "0=none 1=present 2=inspected OK 3=rejected (uint16)"),
        (Reg.COMPONENT_COUNTER, "PLC", "Parts presented (uint16, wraps)"),
        (Reg.PASS_COUNTER, "PLC", "Parts passed (uint16, wraps)"),
        (Reg.REJECT_COUNTER, "PLC", "Parts rejected (uint16, wraps)"),
        (Reg.HEARTBEAT, "PLC", "Scan heartbeat (uint16, wraps)"),
        (Reg.CYCLE_ID, "PLC", "Inspection cycle id (uint16, wraps)"),
    ]
]
