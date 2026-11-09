# Architecture

## Layers (dependencies point downwards)
```
frontend (React/TS)  ──HTTP──▶  app/api (FastAPI routes, validation, auth guard)
                                     │
                              app/services  (InspectionService, ModelService, PlcService, container)
                       ┌─────────────┼───────────────┬───────────────┐
                  app/core       app/plc          app/db        filesystem
          (engine, detectors,   (registers, Modbus  (Repository   (originals/,
           preprocessing,        protocol, client,   contract,      annotated/)
           decision, metrics)    simulator, ctl)     SQLAlchemy)
```
* `app/core` has no web or database dependency (NumPy + OpenCV only; onnxruntime/ultralytics are lazy imports). All detection logic is unit-testable offline.
* `app/plc` has no dependency on the rest of the app. The simulator, the client and the cycle controller can be run and tested alone.
* `app/services/container.py` wires everything and is framework independent; FastAPI routes are thin adapters over it.
* `app/db.Repository` is a Protocol with two implementations: `SqlRepository` (SQLAlchemy) and `MemoryRepository` (tests). A shared contract test (`tests/repo_contract.py`) runs against both.

## Shared detection engine
`DetectionEngine.analyze_bytes()` is used by the upload workflow and by the PLC controller:
1. `validate_and_decode` – magic-byte sniffing, byte-size limit, header-based pixel-count limit (decompression-bomb guard), decode check, minimum side.
2. `Detector.detect` – Ultralytics, ONNX Runtime (letterbox → NCHW float32 → raw head → confidence filter → class-aware NMS → undo letterbox → clip) or the demo heuristic.
3. `decide` – configurable PASS/REJECT rules.
4. `annotate` – boxes and verdict banner (demo mode adds a visible "DEMO MODE" label to the image).

### Modes
| Mode | When | What it means |
|---|---|---|
| `real` | weights loaded | genuine inference; metrics shown if `metrics.json` matches the weights |
| `demo` | `DETECTION_MODE=demo`, or `auto` without usable weights | classical heuristic, labelled everywhere (UI banner, image banner, `is_demo` on records) |
| not ready | `DETECTION_MODE=real` without weights | `/ready` returns 503, analysis returns 503 with instructions |

## Persistence
Tables: `inspections`, `defects`, `uploads`, `model_configs`, `plc_events`, `machine_status`, `system_events`, `schema_version`.
Initialisation: `create_all` + a `schema_version` row; a mismatch makes start-up fail loudly instead of corrupting data. (Alembic can be added without touching the repository interface.)
Each inspection stores id, timestamp, original/annotated file references (relative to `DATA_DIR`), top defect class/confidence/box, decision, model mode/name/version, thresholds, duration and (for PLC cycles) a link to the PLC event.

## Security design
* Uploads: type by content, size/pixel limits, server-generated file names; the client file name is only a sanitised display label.
* Files are served only through `/inspection/{id}/image/{kind}`; the stored reference is re-resolved and must stay inside `DATA_DIR`.
* All state-changing endpoints require `X-API-Key` when `API_KEY` is set, otherwise a loopback client. Read-only endpoints are open.
* The PLC client refuses non-loopback hosts unless `PLC_ALLOW_NON_LOCAL_HOST=true`; the simulator refuses non-loopback binds unless explicitly allowed.

## PLC workflow
See `docs/PLC_INTEGRATION.md`. In short: photo-eye (simulated coil) → PLC sets `TRIGGER`, stops the conveyor → controller reads `TRIGGER`, runs the engine, writes result registers + `PASS_SIGNAL`/`REJECT_SIGNAL` → PLC counts, pulses `REJECT_ACTUATOR`, clears `TRIGGER`, restarts the conveyor. Any exception during inspection becomes a **fail-safe REJECT**. If the PC never answers, the PLC watchdog rejects the part and flags FAULT.
