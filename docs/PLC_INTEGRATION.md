# PLC integration (Modbus TCP)

> **The PLC in this project is a software simulator.** It demonstrates the communication pattern; it is not certified, not safety-rated and not connected to hardware. The Automation screen, API responses and logs label it `SIMULATED PLC`.

## Components
| File | Role |
|---|---|
| `app/plc/registers.py` | register/coil map, enums, documentation table (served by `GET /plc/registers`) |
| `app/plc/modbus_protocol.py` | MBAP framing, function codes 01/02/03/04/05/06/0F/10, exception responses |
| `app/plc/simulator.py` | threaded Modbus TCP server + PLC scan logic + scan thread; CLI `python -m app.plc.simulator` |
| `app/plc/client.py` | `SocketModbus` (built-in transport), `PyModbusAdapter` (optional), `PlcClient` (retry/back-off/events) |
| `app/plc/controller.py` | one inspection cycle (PC side of the handshake) |
| `app/services/plc_service.py` | connection management, event persistence, API-facing cycle runner |

## Register map (zero-based protocol addresses, unit id 1, default port 5020)
Coils (FC 01/05/0F):

| Addr | Name | Direction | Meaning |
|---|---|---|---|
| 0 | TRIGGER | PLC→PC | part at station, start inspection; PLC clears it when a result arrives |
| 1 | PASS_SIGNAL | PC→PLC | part passed |
| 2 | REJECT_SIGNAL | PC→PLC | part must be rejected (wins if both set) |
| 3 | REJECT_ACTUATOR | PLC out | pusher energised for a 0.5 s pulse |
| 4 | ESTOP | input | emergency stop pressed (simulated button) |
| 5 | CONVEYOR_RUN | PLC out | conveyor motor |
| 6 | PART_SENSOR_SIM | simulation | stands in for the photo-eye; self-resets |

Holding registers (FC 03/06/10), all `uint16`:

| Addr | Name | Writer | Meaning |
|---|---|---|---|
| 0 | MACHINE_STATE | PLC | 0 IDLE, 1 RUNNING, 2 INSPECTING, 3 ESTOP, 4 FAULT |
| 1 | INSPECTION_RESULT | PC | 0 none, 1 PASS, 2 REJECT |
| 2 | DEFECT_CLASS_ID | PC | class id of top defect, 65535 = none |
| 3 | DEFECT_COUNT | PC | reject-triggering defects |
| 4 | CONFIDENCE_X1000 | PC | top score × 1000 (0-1000) |
| 5 | COMPONENT_STATUS | PLC | 0 none, 1 present, 2 inspected OK, 3 rejected |
| 6 | COMPONENT_COUNTER | PLC | parts presented (wraps at 65535) |
| 7 | PASS_COUNTER | PLC | wraps |
| 8 | REJECT_COUNTER | PLC | wraps |
| 9 | HEARTBEAT | PLC | scan counter |
| 10 | CYCLE_ID | PLC | cycle id |

FC 02 (discrete inputs) and FC 04 (input registers) are served from the same tables for client compatibility.

## Cycle handshake
1. PC reads status; if `ESTOP` is set the cycle is blocked (`blocked_estop`).
2. (simulation) PC pulses `PART_SENSOR_SIM`; PLC increments counters, sets `TRIGGER`, stops the conveyor, state `INSPECTING`.
3. PC polls `TRIGGER`, fetches the image, runs the **shared** detection engine, stores the inspection record.
4. PC writes registers 1-4 in one FC16 request, then sets `PASS_SIGNAL` or `REJECT_SIGNAL`.
5. PLC (rising edge, only while `TRIGGER` is set): counters, component status, reject pusher pulse for REJECT, clears `TRIGGER`, conveyor runs.
6. PC polls until `TRIGGER` clears and reports a timeline with timestamps; every Modbus operation also lands in `plc_events`.

## Failure handling
* **Timeouts/refused/reset:** `PlcClient` retries (`PLC_RETRIES`, exponential back-off 0.1 s, 0.2 s, …), reconnects transparently and raises `PlcTimeoutError`/`PlcCommunicationError` afterwards. Modbus exception responses (e.g. illegal address) are not retried. Verified by tests, including a simulated PLC restart.
* **Inspection failure:** any exception (model missing, crash) → controller sends a **fail-safe REJECT** and records `inspection_error`.
* **PC silent:** PLC watchdog (`inspection_timeout_s`, default 10 s) rejects the part and sets `FAULT`.
* **E-stop:** conveyor off, trigger cleared, triggers ignored until released.

## Safety rules enforced in code
* The client refuses any non-loopback host unless `PLC_ALLOW_NON_LOCAL_HOST=true`; Compose sets it only for the simulator container. Nothing scans or auto-connects to networks.
* The simulator refuses non-loopback binds without `--allow-non-local`.
* PLC endpoints that change state require `X-API-Key` (or a loopback caller).

## How a real PLC integration would differ
* **Map:** use the PLC vendor's actual addresses, byte/word order (Modbus word order for 32-bit values varies), scaling and data types; many PLCs use 1-based "4xxxx" addressing in documentation.
* **Who triggers:** a real photo-eye wires to a PLC input; `PART_SENSOR_SIM` would not exist. The PLC owns timing, encoders and reject-tracking (shift register synchronised to belt position), not the PC.
* **Safety:** emergency stop and guarding are **hard-wired safety circuits** with safety-rated devices (IEC 60204-1 / ISO 13849). A PC-side flag is never a safety function. Do not use this code for personnel or machine protection.
* **Security:** Modbus TCP has no authentication or encryption. Put it on an isolated OT network segment, use a firewall/VPN gateway, allow-list the PC, never expose port 502 to a public network. Consider OPC UA or a vendor gateway for secure transport.
* **Real-time:** a PC with Python and an ML model cannot guarantee deterministic latency; production lines usually need the PLC to make the reject decision within a fixed window and treat "no answer" as reject (as the simulator's watchdog does).
* **Commissioning:** test with the actuator disabled first, log every write, and get sign-off from the controls engineer.
* **Transport:** PyModbus (`requirements-optional.txt`) can replace the built-in transport via `PyModbusAdapter`; that adapter is written against `pymodbus==3.7.4` but was not executed in this build.
