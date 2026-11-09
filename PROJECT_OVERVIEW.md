# Project overview

**Smart Automotive Quality Inspection Platform** – a portfolio-grade applied-AI and industrial-automation project.

| | Project A – AI defect detection | Project B – PLC-integrated inspection |
|---|---|---|
| Goal | detect surface defects in uploaded images and decide PASS/REJECT | run inspection cycles triggered by a (simulated) PLC and send PASS/REJECT back |
| Entry points | Inspect, History, Overview screens; `/api/v1/inspection/*` | Automation screen; `/api/v1/plc/*`; `python -m app.plc.simulator` |
| Needs PLC simulator? | **No** | yes (embedded on loopback, or the compose service) |
| Shared | `DetectionEngine`, decision rules, database, backend, dashboard | same |

## Repository map
```
backend/app/core      detection engine, detectors, preprocessing, decision, metrics, synthetic data
backend/app/plc       register map, Modbus TCP protocol/simulator/client, cycle controller
backend/app/db        repository contract, SQLAlchemy + in-memory implementations
backend/app/services  inspection / model / PLC services and the container
backend/app/api       FastAPI routes and schemas
backend/ml            dataset tools, train, evaluate, infer, ONNX export
backend/tests         93 tests (82 passed, 11 skipped offline)
frontend/             React + TypeScript dashboard (esbuild)
docs/                 architecture, dataset, training, PLC, API, deployment, interview guide, screenshots
scripts/              run_local, demo.py, package.py
```

## Status in one table
| Capability | State |
|---|---|
| Detection pipeline, rules, metrics, dataset tools | implemented and unit-tested |
| PLC simulator + Modbus client/controller | implemented and tested over real TCP sockets |
| Services, end-to-end workflows (service level) | implemented and tested |
| Dashboard | implemented; bundle, type check (stub), browser walkthrough done |
| FastAPI layer, SQLAlchemy layer, Docker, CI | implemented, **not executed** (offline sandbox) |
| Trained model, real dataset, accuracy figures | **not provided** – DEMO MODE until you add them |
| Physical PLC | **never** – simulator only |

## Fast demo (≈3 minutes)
1. `python scripts/demo.py` – prints both workflows with timings.
2. `./scripts/run_local.sh` → open `http://127.0.0.1:8000`.
3. Overview → *Load demo records* (labelled DEMO) → Inspect → upload images → History → Automation → *Connect* → run cycles → press e-stop → Model screen (explains demo/real status).

Documentation: `README.md`, `docs/*`, `BUILD_REPORT.md`, `TEST_REPORT.md`, `DEPLOYMENT_CHECKLIST.md`.
