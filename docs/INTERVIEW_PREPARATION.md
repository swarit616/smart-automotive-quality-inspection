# Interview preparation

Use this to explain the project honestly: a **simulated** line, a **shared engine**, a **demo mode** when there is no model, and verified-versus-unverified parts listed in `BUILD_REPORT.md`.

## 30-second pitch
"I built an inspection platform where one detection engine serves two workflows: uploading images for defect detection, and a simulated PLC line over Modbus TCP that triggers inspections and receives PASS/REJECT signals. Detections feed configurable acceptance rules and are stored in SQL with the model version and thresholds, so each decision is traceable. When no trained model is available it runs in an explicitly labelled demo mode, and I only show metrics that were measured on a held-out split."

## End-to-end workflow
Upload → validate (magic bytes, size, pixel count) → decode with OpenCV → letterbox to 640 → detector → boxes mapped back to the original image → class-aware NMS → decision rules → annotated PNG + DB record → dashboard. For the line: simulated photo-eye → PLC sets TRIGGER → controller reads it → same engine → result registers + PASS/REJECT coil → PLC counts and pulses the pusher → event log + dashboard.

## Key concepts (be ready to explain and compute)
**YOLO / YOLOv8.** Single-stage detector: one forward pass predicts boxes and class scores on a grid of anchors-free points at three scales. v8 is anchor-free with a decoupled head; the raw output here is `(4+nc) × N` – box `(cx, cy, w, h)` plus class scores, no separate objectness. Trade-off versus two-stage detectors: speed over some accuracy on tiny objects.

**IoU.** Area of overlap ÷ area of union of two boxes (0-1). Used to match predictions to ground truth (TP if IoU ≥ threshold, same class) and inside NMS. Example: boxes `[0,0,10,10]` and `[5,0,15,10]` → intersection 50, union 150 → IoU 1/3. (Tested in `test_boxes_and_preprocessing.py`.)

**NMS.** The detector emits many overlapping boxes per object. Sort by score, keep the best, drop remaining boxes whose IoU with it exceeds the threshold, repeat. Class-aware NMS runs per class so a "scratch" never suppresses a "pit". The IoU threshold is a trade-off: too low merges adjacent defects, too high leaves duplicates.

**Precision / recall / F1.** Precision = TP/(TP+FP) – of flagged defects, how many were real (false rejects hurt yield). Recall = TP/(TP+FN) – of real defects, how many were caught (escapes hurt quality). F1 = harmonic mean. They depend on the confidence threshold, which is why the decision rules expose it.

**AP / mAP.** Rank predictions by confidence, sweep the threshold to get a precision-recall curve, AP = area under the (monotone-envelope) curve – here COCO-style with 101 recall points. mAP@0.5 averages AP across classes at IoU 0.5; mAP@0.5:0.95 averages over IoU 0.50…0.95 and rewards tight boxes. I implemented it (`app/core/metrics.py`) and verified it on hand-computed cases (e.g. ranking TP, FP, TP over 2 ground truths gives (51·1 + 50·⅔)/101).

**Image preprocessing.** Validation first (never trust file extensions), then letterbox: scale to fit while keeping aspect ratio and pad to 640×640 with grey (114) so defects are not distorted; BGR→RGB, /255, HWC→NCHW. Boxes must be mapped back by subtracting padding and dividing by the scale, then clipped. Optional CLAHE helps low-contrast metal.

**FastAPI.** ASGI framework; type hints + Pydantic give validation and OpenAPI docs. Blocking work (inference, Modbus sockets) lives in sync `def` endpoints so FastAPI runs them in a thread pool instead of blocking the event loop. Dependencies (`Depends`) implement the control-endpoint guard. I kept routes thin and put logic in framework-independent services so it is testable without HTTP.

**SQL.** Normalised: `inspections` 1—N `defects` (cascade delete), indexes on timestamp/decision, JSON columns for boxes. SQLAlchemy 2 ORM; SQLite by default, PostgreSQL via URL. The repository pattern lets the same contract test run on an in-memory fake and the SQL implementation. Aggregations for the dashboard use a pure function shared by both.

**Docker.** One image per service, non-root user, health checks, a named volume for state, secrets via environment, multi-stage build for the frontend (Node build → nginx). Compose wires backend, simulator and proxy; only the proxy is public.

**Modbus TCP.** Request/response protocol on TCP port 502 (5020 here). MBAP header = transaction id, protocol id (0), length, unit id; then PDU = function code + data. Coils are 1-bit read/write; holding registers are 16-bit read/write. Functions used: 01 read coils, 03 read holding registers, 05 write single coil, 06 write single register, 15 write multiple coils, 16 write multiple registers. Errors come back as function|0x80 + exception code (01 illegal function, 02 illegal address, 03 illegal value). No authentication or encryption – that is why it must live on an isolated network.

**PLC registers in this project.** Coils: TRIGGER, PASS/REJECT signals, actuator, e-stop, conveyor. Holding registers: machine state, result code, defect class/count, confidence×1000, component status, counters, heartbeat, cycle id. Scaling confidence to an integer ×1000 is the usual way to ship floats over 16-bit registers.

**Why a handshake with a trigger bit?** The PLC owns the process; the PC is a service. The trigger/ack pattern prevents double-processing, and the watchdog guarantees a decision even if the PC dies (fail-safe reject).

## Design decisions worth explaining
* **Shared engine** → both projects test the same code; no duplicated decision logic.
* **Demo mode** → the product is demonstrable without weights but cannot be mistaken for AI: banner in UI, label burned into annotated images, `is_demo` on records, metrics hidden.
* **Fail-safe on error** → inspection exceptions become REJECT, not silence.
* **Leak-free splits** → identical images are grouped by hash before splitting, and validation reports cross-split duplicates; leakage inflates metrics.
* **Own metric implementation** → I can explain every number and test it; Ultralytics' numbers differ slightly by interpolation.
* **Built-in Modbus transport** → dependency-free and testable offline; PyModbus adapter provided as an option.

## Likely questions (with honest answers)
* *"What accuracy does it get?"* — None is claimed. No real dataset/weights were available in the build environment; the pipeline, metrics and evaluation script are ready and tested, and the dashboard shows metrics only after a real evaluation.
* *"Is the PLC real?"* — No, a software Modbus TCP simulator. Real integration differences are listed in `PLC_INTEGRATION.md` (addressing, hard-wired safety, network isolation, determinism).
* *"What would you do with a real line?"* — Move reject decisions/timing into the PLC, add encoder-based reject tracking, calibrate lighting/camera, collect production data, set thresholds from the cost of false rejects vs escapes, validate with an MSA/gauge study, monitor drift.
* *"What are the limits of YOLO here?"* — Tiny/low-contrast defects, domain shift (lighting, new parts), rare classes; segmentation or anomaly detection may suit unlabeled defects better.
* *"How do you prevent unsafe file handling?"* — Content sniffing, limits, generated names, resolved-path check against `DATA_DIR`.
* *"What did you not verify?"* — See `BUILD_REPORT.md`: FastAPI/SQLAlchemy/Docker/CI and real-model paths were not executed in the build sandbox.

## Numbers to be able to compute by hand
IoU of two boxes; P/R/F1 from TP/FP/FN (e.g. TP 8, FP 2, FN 4 → P 0.8, R 0.667, F1 0.727); mAP from a small ranked list; how letterbox scale/padding map a box back.
