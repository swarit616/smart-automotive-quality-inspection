# Deployment checklist

Tick each item only after you have actually done it. Items marked ★ were **never executed** during the build.

## Before first run
- [ ] ★ `cd backend && pip install -r requirements-dev.txt && python -m pytest -ra` → all tests pass, **0 skipped** (the 11 skipped tests need FastAPI/SQLAlchemy/httpx).
- [ ] ★ `cd frontend && npm install && npm run typecheck && npm run build`; commit `package-lock.json`.
- [ ] Generate and commit Python lock files after a clean install.
- [ ] `cp .env.example .env`; set `API_KEY` (32+ random bytes); confirm `.env` is git-ignored.
- [ ] Decide `DETECTION_MODE`: `auto` (demo fallback) for demos, `real` for anything claiming real inference.

## Model and data (only if you want REAL MODEL MODE)
- [ ] Dataset obtained, its **licence read and recorded** in `data/datasets/<name>/README.md`.
- [ ] `python -m ml.dataset_tools validate` → `ok: true`, no leakage.
- [ ] Trained; `python -m ml.evaluate` run on the held-out **test** split; metrics reviewed per class.
- [ ] Exported `best.onnx` + `class_names.json` into `models/`; `python -m ml.infer <image> --mode real` returns sensible boxes.
- [ ] Dashboard Model screen shows REAL MODEL and the measured metrics (and no "synthetic" warning).

## Docker Compose
- [ ] ★ `docker compose config -q` and `docker compose build` succeed.
- [ ] ★ `docker compose up` → all three containers healthy.
- [ ] ★ `http://localhost:8080` loads; Model screen shows the expected mode; `GET /ready` is 200 (or an intentional 503 in `real` mode without weights).
- [ ] ★ Upload an image; PASS/REJECT, annotated image and history record appear; files persist after `docker compose restart`.
- [ ] ★ Automation → Connect → run both cycles; register values and events update; e-stop blocks cycles.
- [ ] ★ A control call without the key directly to the backend returns 401/403.

## Security
- [ ] TLS terminates in front of the frontend; only 80/443 exposed.
- [ ] Backend port 8000 not reachable from outside the host; simulator port not published.
- [ ] `PLC_ALLOW_NON_LOCAL_HOST` is `true` **only** for the simulator container.
- [ ] No real PLC address is configured anywhere. (If you ever test against a real device: isolated network, actuators disabled, controls engineer present.)

## Operations
- [ ] Backups for `inspection_data` volume / database.
- [ ] Log retention; `/ready` monitored.
- [ ] If on a managed platform: persistent volume, min-instances ≥ 1, ≥ 1 GB RAM (see `docs/DEPLOYMENT.md`).

## Before presenting the project
- [ ] README claims match what you verified (no accuracy numbers unless measured).
- [ ] Screenshots re-captured from the final stack (optional).
- [ ] `LICENSE` added; AGPL (Ultralytics) implications reviewed.
