# Build report

Build date: 2026-11-08. Environment: offline Linux sandbox, 1 CPU, no GPU, Python 3.12, Node 22 (see `TEST_REPORT.md`). This report separates what was verified from what was not.

## 1. Fully implemented and tested (executed in the sandbox)
| Area | Evidence |
|---|---|
| Image validation + OpenCV preprocessing (magic-byte sniffing, limits, decompression-bomb guard, letterbox, CLAHE helper) | 13 tests |
| Bounding-box geometry: validation, IoU, NMS, class-aware NMS | tests |
| YOLOv8 output decoding (confidence filter, NMS, letterbox inversion) | tests on synthetic tensors |
| PASS/REJECT decision rules, configuration validation | tests |
| Detection engine with REAL / DEMO / NOT-READY modes, status & readiness, config | tests |
| Metrics: P/R/F1, AP (101-pt), mAP50, mAP50-95, confusion matrix | hand-computed cases; one bug (AP sentinel) found and fixed by tests |
| Dataset tooling: YOLO validation, leakage detection, leak-free split, VOC→YOLO, synthetic dataset, evaluation loop | 7 tests + CLI smoke |
| Modbus TCP protocol, PLC simulator logic, TCP server, client (retry/back-off/timeout/reconnect), controller cycle, fail-safe & watchdog, e-stop, target safety rules | 24 tests incl. real sockets |
| Inspection service (upload→engine→files→repository), model-config service, PLC service, end-to-end Project A and Project B at service level | 15 tests |
| In-memory repository + shared repository contract | 4 tests |
| Frontend bundle, own-code type check (stub typings), full browser walkthrough on all five screens | see test report |
| `scripts/demo.py`, dataset/inference/simulator CLIs | executed |

## 2. Implemented but not fully tested
| Area | What is missing |
|---|---|
| FastAPI app (`app/api`), incl. auth guard, error mapping, multipart upload, static serving | syntax-checked only; 6 API tests skipped (FastAPI not installable offline). The logic behind each route is in services that **are** tested. |
| SQLAlchemy models/repository (SQLite + PostgreSQL) | syntax-checked only; contract tests exist and are skipped until SQLAlchemy is installed |
| Docker/Compose/nginx, GitHub Actions CI | written, never run |
| `PyModbusAdapter` (optional transport) | never run |
| Ultralytics/ONNX detectors with real weights; `ml.train`, `ml.export_onnx`, `ml.evaluate` CLIs | logic around them is tested; the model-dependent calls are not |
| Frontend type check with real React typings | only a stub-typed check was possible |

## 3. Requires external dataset or model weights
* A defect dataset (NEU-DET recommended, or your own). No network was available; none was downloaded and no licence was verified. See `docs/DATASET_GUIDE.md`.
* Trained weights (`models/best.onnx` + `class_names.json`, or `best.pt`). None exist. Without them the app runs in DEMO MODE, which is clearly labelled and carries no accuracy claim.
* Evaluation metrics: produced only by `python -m ml.evaluate` on your held-out test split.

## 4. Requires your action
1. `pip install -r backend/requirements-dev.txt` and run the full suite (`python -m pytest`) – this executes the 11 skipped tests for the first time; fix anything they surface.
2. Install the frontend dependencies (`cd frontend && npm install`), commit the generated `package-lock.json`, run `npm run typecheck` with real `@types/react`.
3. Generate Python lock files after a successful install (`pip freeze > backend/requirements.lock`, or use `pip-tools`/`uv`); the pins in `requirements*.txt` are known-compatible choices but were not resolved here.
4. `cp .env.example .env`, set a real `API_KEY`, `docker compose up --build`, work through `DEPLOYMENT_CHECKLIST.md`.
5. Obtain a dataset, train, evaluate, export ONNX (`docs/MODEL_TRAINING.md`).
6. Add a `LICENSE` file; review Ultralytics AGPL-3.0 obligations.
7. Re-capture README screenshots from the real FastAPI stack if you want them to show the final deployment (current ones came from the verification harness, see test report).

## 5. Design decisions and deviations from the brief (and why)
* **Modbus transport:** a dependency-free implementation is the default (testable offline); PyModbus is supported through an optional adapter rather than the default.
* **Tests use `unittest`** (pytest could not be installed); pytest collects them unchanged and CI runs pytest.
* **Frontend build uses esbuild** (the only bundler available/verified offline) instead of Vite; `npm run dev` rebuilds on change and the backend serves `dist/`.
* **No video input** – marked optional in the brief; not implemented.
* **No lock files** – cannot be generated without network (see action 2-3).
* **Inference defaults to ONNX Runtime**; `.pt` weights need `requirements-train.txt`.
* **Authentication** is a shared API key on state-changing endpoints (loopback exempt when no key is set).
* **Prebuilt `frontend/dist`** is included so the local run works without Node.

## 6. Defects found and fixed during the build
Fixed after tests failed: AP interpolation sentinel (inflated AP when recall stayed 0); simulator `stop()` left established connections alive (a stopped "PLC" kept answering); NumPy float64 values leaking into box JSON. Frontend: esbuild/tsc found a missing CSS module declaration; Playwright found a selector issue in the *test script* only (not an app defect).

## 7. Known limitations that can affect a live demo
* In DEMO MODE detections are heuristic, class names are `scratch`/`blemish`, and "scores" are contrast values – say so when presenting.
* With a real model, the synthetic images used by "Cycle with clean/defective synthetic part" are out-of-domain and may not trigger rejects; use the `upload` scenario via the API or upload real part images.
* First run of Docker, FastAPI and SQLAlchemy code is on you (see section 2); allow time to debug small issues.
* Single-process, single-user design; no authentication beyond the API key.
