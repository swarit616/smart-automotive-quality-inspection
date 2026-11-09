# Deployment guide

> The Docker images, Compose file and CI workflow were **written but not built or run** in the offline build sandbox (no Docker, no network). Follow the checklist in `DEPLOYMENT_CHECKLIST.md` for the first deployment and expect to fix small issues.

## 1. Local Docker Compose (recommended first target)
```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"     # paste into API_KEY in .env
mkdir -p models                                                  # optional: put best.onnx + class_names.json here
docker compose up --build
```
* Dashboard: `http://localhost:8080` (nginx → backend; the proxy injects `X-API-Key`).
* API: `http://127.0.0.1:8000` (published on localhost only).
* `plc-simulator` has no published port; the backend reaches it by service name.
* Persistent data: named volume `inspection_data` (SQLite database, originals, annotated images). Models: `./models` mounted read-only.
* Health: `docker compose ps` shows health of all three containers (`/health`, nginx `/health`, simulator socket).
* Without weights the dashboard shows **DEMO MODE**; set `DETECTION_MODE=real` to make a missing model a hard "not ready" error instead.

## 2. Single VM / VPS (Docker)
Any small VM (2 vCPU, 4 GB RAM is comfortable for `yolov8n` on CPU). Install Docker, copy the project, set `.env`, run Compose, and put a TLS-terminating reverse proxy in front (Caddy or nginx + Let's Encrypt) forwarding to port 8080. Open only 80/443. Back up the `inspection_data` volume. This is the simplest option that supports persistent storage and background processes.

## 3. PostgreSQL
Install the driver (`pip install -r backend/requirements-optional.txt`, or add it to the image) and set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/inspection`. Tables are created on first start; a schema-version row guards against incompatible upgrades. Images still live on the `DATA_DIR` volume (use object storage if you scale to several replicas – not implemented).

## 4. Managed container platforms (Render, Fly.io, Railway, Azure Container Apps, Google Cloud Run, AWS App Runner/ECS)
Deploy the `backend` and `frontend` images as two services (or serve `frontend/dist` from the backend by setting `FRONTEND_DIST`). Constraints to check *before* choosing a tier:
* **Persistent disk:** free tiers usually have an ephemeral filesystem. Uploaded images and the SQLite file disappear on restart. Use a paid persistent volume, or PostgreSQL plus object storage (code change required for images).
* **Long-running processes:** the embedded PLC simulator and Modbus sockets need an always-on instance; scale-to-zero platforms (Cloud Run default) will drop connections. Set min instances ≥ 1.
* **Cold starts / memory:** ONNX Runtime + OpenCV need roughly 300-600 MB RAM; tiny free instances (256-512 MB) may be OOM-killed.
* **GPU:** free tiers have none. CPU inference of `yolov8n` at 640 px is typically tens to a few hundred ms per image; a GPU is a separate, paid configuration and PyTorch GPU images are large.
* **Training:** do not train on free hosting. Train locally/Colab/Kaggle, export ONNX, deploy only the weights.
* **PLC networking:** a cloud instance cannot reach a plant PLC without a VPN; and you should not expose Modbus to the internet. For the portfolio the PLC is simulated, so this does not arise.
* **Secrets:** set `API_KEY` as a platform secret; never bake it into images.

## 5. Production hardening checklist
TLS everywhere; strong `API_KEY` rotated regularly (or replace with OIDC auth); restrict CORS; run containers as non-root (already done for the backend); log shipping; backups of DB and image volume; limit upload size at the proxy (already 12 MB in nginx); rate limiting at the proxy; pin and scan images; monitor `/ready`.

## Commands reference
| Task | Command |
|---|---|
| Start | `docker compose up -d --build` |
| Logs | `docker compose logs -f backend` |
| Stop | `docker compose down` (add `-v` to delete data) |
| Tests in container | `docker compose run --rm backend python -m unittest discover -s tests -t .` *(tests are excluded from the image by `.dockerignore`; run them from source instead)* |
