#!/usr/bin/env bash
# Local run without Docker:  ./scripts/run_local.sh   ->  http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet -r backend/requirements.txt

if [ -f .env ]; then set -a; . ./.env; set +a; fi

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm install --no-audit --no-fund && npm run build)
  else
    echo "frontend/dist is missing and npm is not installed: the API will run but the dashboard will not be served." >&2
  fi
fi

export FRONTEND_DIST="${FRONTEND_DIST:-frontend/dist}"
export DATA_DIR="${DATA_DIR:-./data}"
export MODEL_WEIGHTS_PATH="${MODEL_WEIGHTS_PATH:-./models/best.onnx}"
cd backend
# --app-dir is implicit (cwd=backend). Relative paths below are resolved against the repo root.
export DATA_DIR="$(cd .. && realpath -m "$DATA_DIR")"
export MODEL_DIR="$(cd .. && realpath -m "${MODEL_DIR:-./models}")"
export MODEL_WEIGHTS_PATH="$(cd .. && realpath -m "$MODEL_WEIGHTS_PATH")"
export FRONTEND_DIST="$(cd .. && realpath -m "$FRONTEND_DIST")"
echo "Dashboard: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
