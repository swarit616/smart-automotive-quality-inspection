# Test report

Generated during the build, in the sandbox described below. Only results of commands that were actually executed are listed.

## Environment
| Item | Value |
|---|---|
| OS / Python | Linux (Ubuntu 24 container), Python 3.12 |
| Compute | 1 CPU core, no GPU |
| Network | **none** (package installation and dataset/model downloads impossible) |
| Installed | numpy, opencv-python, onnxruntime, Flask, Playwright/Chromium, Node 22 with react 19.2.8, react-dom, typescript 6.0.3, esbuild 0.28.2 |
| **Not installable** | fastapi, pydantic, sqlalchemy, httpx, python-multipart, pymodbus, pytest, torch, ultralytics, docker |

Because pytest was not available, the suite is written with `unittest` (also collected by pytest) and run with `python -m unittest discover`.

## Backend tests – `cd backend && python -m unittest discover -s tests -t . -v`
**Result: 93 collected · 82 passed · 0 failed · 0 errors · 11 skipped** (≈10 s).

| Module | Collected | Passed | Skipped | Covers |
|---|---:|---:|---:|---|
| `test_boxes_and_preprocessing` | 13 | 13 | 0 | IoU, box validation/clipping, YOLO-box validation, NMS (incl. class-aware), image type/size/pixel/corruption validation, letterbox round-trip, model input layout |
| `test_detection_engine` | 19 | 19 | 0 | PASS/REJECT rules, YOLOv8 head decoding (synthetic tensors), demo detector sanity on synthetic images, **demo mode** and **real-model-not-ready** engine behaviour, config validation, metrics (P/R/F1/AP/mAP/confusion matrix, hand-computed values) |
| `test_ml_tools` | 7 | 7 | 0 | synthetic dataset validity, validation error detection (bad class id, bad coords, orphan labels, unreadable image, cross-split leakage), leak-free deterministic split with duplicate images, VOC→YOLO conversion, `data.yaml` names, evaluation loop on synthetic split, held-out split requirement |
| `test_plc` | 24 | 24 | 0 | Modbus PDU encode/decode and exceptions, PLC logic (trigger, pass, reject + actuator pulse, e-stop, mid-cycle e-stop, watchdog fail-safe, counter wrap), **Modbus over real TCP sockets** (client↔simulator), full controller cycles PASS/REJECT, fail-safe REJECT on inspection error, e-stop blocking and recovery, trigger timeout, connection refused with exponential back-off, response timeout, transparent reconnect after PLC restart, target validation (loopback-only), public-bind refusal |
| `test_services` | 15 | 15 | 0 | **End-to-end Project A** (upload → engine → files → repository → query/filter/stats), upload validation leaves nothing stored, path-traversal and display-name safety, real-mode-without-model errors, demo seeding labelled, model config persistence/restore, **end-to-end Project B** (connect → cycles → PLC counters → DB inspection with PLC event link → events/machine status), e-stop through the service, fail-safe REJECT when the model is missing, upload scenario |
| `test_repositories` | 9 | 4 | 5 | repository contract on `MemoryRepository` ✔; same contract on `SqlRepository` and schema-version guard **skipped** |
| `test_api` | 6 | 0 | 6 | FastAPI route tests (upload/analyze/history/images, validation errors, PLC workflow, API-key enforcement, real-mode 503) **skipped** |

Skip reason for all 11: `fastapi/httpx/sqlalchemy/python-multipart not installed in this environment`. They are expected to run in CI and in any environment with `requirements-dev.txt` installed; they have **never been executed**, so their outcome is unknown.

## Frontend checks
| Check | Command | Result |
|---|---|---|
| Production bundle | `node build.mjs` (esbuild 0.28.2) | ✔ `app.js` 226 KB, `app.css` 12 KB, no errors |
| Type check | `tsc --noEmit` against **stub** React typings (real `@types/react` unavailable offline; `noImplicitAny` relaxed because of the stub) | ✔ exit 0 – validates the project's own types (API types, props, hooks) only, not JSX/event typing. Re-run `npm run typecheck` with real types. |
| Browser walkthrough | Playwright + Chromium against the real service layer behind a stand-in stdlib HTTP server (see below) | ✔ see list |

Walkthrough (all executed): demo banner visible; empty-state; load demo records → KPIs (24 inspected); upload of two PNGs + one `.txt` → REJECT and PASS verdicts rendered, invalid file reported; "Original + live boxes" SVG overlay drawn; history filter by decision, row detail panel; Automation: connect, defective cycle → REJECT, clean cycle → PASS, e-stop pressed → cycle `blocked_estop`, released; Model screen shows no metrics in demo mode; mobile (390 px) has no horizontal overflow. **0 console errors, 0 page errors, 0 HTTP 5xx.**

> **Limitation:** the browser was pointed at `/tmp/harness/server.py`, a throw-away stdlib HTTP server that calls the same `build_services()` container the FastAPI routes call. It validated the frontend↔JSON contract and the UI, **not** the FastAPI route code, CORS, multipart handling by FastAPI, or the API-key guard. The harness is not part of the deliverable. Screenshots in `docs/screenshots/` were taken this way.

## Scripts executed
`python scripts/demo.py` (both workflows, in-process) ✔ · `python -m ml.dataset_tools synthetic/validate` ✔ · `python -m ml.infer --mode demo` ✔ · `python -m app.plc.simulator` starts and logs ✔.

## Not executed / not verified
* FastAPI application, schemas, exception handlers, static serving, auth guard (syntax-checked only).
* SQLAlchemy models/repository, SQLite/PostgreSQL behaviour, schema-version guard.
* `ml.train`, `ml.export_onnx`, `ml.evaluate` CLI with real weights, `UltralyticsDetector`, `OnnxYoloDetector` against a real exported model.
* `PyModbusAdapter`.
* Docker images, Compose stack, nginx proxy header injection, GitHub Actions workflow.
* Pinned dependency versions resolving together; `npm install` from a lockfile (none could be generated).
* Real-model mode with real weights; any accuracy/performance figure. **No metrics exist and none are claimed.**
* Video input (not implemented). Load/performance testing. Accessibility audit beyond semantic markup/focus styles.
