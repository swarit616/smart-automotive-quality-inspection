"""FastAPI application factory.

NOTE: this module could not be executed in the offline build environment (FastAPI is not installed
there). tests/test_api.py exercises it with FastAPI's TestClient when the web stack is installed.
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..core.engine import DetectionEngine, ModelNotReadyError
from ..core.preprocessing import ImageValidationError
from ..logging_config import configure_logging
from ..plc.client import PlcError, PlcProtocolError
from ..services.inspection_service import NotFound
from ..services.container import Services, build_services
from ..services.plc_service import PlcNotConnected
from .schemas import (AnalyzeRequest, EstopRequest, ModelConfigRequest, PlcConnectRequest, SeedRequest,
                      SimulateCycleRequest)

log = logging.getLogger("api")
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def svc(request: Request) -> Services:
    return request.app.state.services


def require_control(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Guard for every state-changing endpoint.

    * API_KEY configured -> the X-API-Key header must match.
    * otherwise            -> only loopback clients are accepted (safe local default).
    """
    settings: Settings = request.app.state.settings
    if settings.api_key:
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
        return
    host = request.client.host if request.client else ""
    if host not in LOCAL_CLIENTS:
        raise HTTPException(status_code=403, detail="control endpoints are limited to localhost unless API_KEY is configured")


def create_app(settings: Settings | None = None, repo=None, engine: DetectionEngine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = build_services(settings, repo, engine)
        s = app.state.services
        s.repo.add_system_event("INFO", "application started", {"mode": s.engine.status()["mode"]})
        try:
            yield
        finally:
            try:
                s.plc.shutdown()
            finally:
                close_repo = getattr(s.repo, "close", None)
                if callable(close_repo):
                    close_repo()

    app = FastAPI(
        title="Smart Automotive Quality Inspection Platform",
        version="1.0.0",
        description="YOLOv8 defect detection (Project A) and simulated-PLC Modbus TCP inspection cycles (Project B). "
                    "State-changing endpoints require X-API-Key (or a loopback client).",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-API-Key"])

    # ---------------------------------------------------------------- errors
    def err(status: int, kind: str, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": kind, "detail": str(exc)})

    app.add_exception_handler(ImageValidationError, lambda r, e: err(422, "invalid_image", e))
    app.add_exception_handler(NotFound, lambda r, e: err(404, "not_found", e))
    app.add_exception_handler(ModelNotReadyError, lambda r, e: err(503, "model_not_ready", e))
    app.add_exception_handler(PlcNotConnected, lambda r, e: err(409, "plc_not_connected", e))
    app.add_exception_handler(PlcProtocolError, lambda r, e: err(502, "plc_protocol_error", e))
    app.add_exception_handler(PlcError, lambda r, e: err(503, "plc_unavailable", e))
    app.add_exception_handler(ValueError, lambda r, e: err(422, "invalid_request", e))
    app.add_exception_handler(RuntimeError, lambda r, e: err(409, "conflict", e))

    # ---------------------------------------------------------------- health
    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    def ready(request: Request):
        s = svc(request)
        db_ok = s.repo.ping()
        st = s.engine.status()
        ok = db_ok and st["ready"]
        body = {"ready": ok, "database": db_ok, "model_ready": st["ready"], "mode": st["mode"], "reason": st["reason"]}
        return JSONResponse(status_code=200 if ok else 503, content=body)

    api = APIRouter(prefix="/api/v1")

    # ---------------------------------------------------------------- inspection
    @api.post("/inspection/upload", tags=["inspection"], dependencies=[Depends(require_control)])
    def upload(request: Request, files: list[UploadFile] = File(...)) -> dict:
        s = svc(request)
        if len(files) > 20:
            raise HTTPException(413, "at most 20 files per request")
        results = []
        limit = s.settings.max_upload_bytes
        for f in files:
            data = f.file.read(limit + 1)
            try:
                if len(data) > limit:
                    raise ImageValidationError(f"file too large (limit {limit // (1024 * 1024)} MB)")
                results.append({"ok": True, **s.inspections.save_upload(f.filename, data)})
            except ImageValidationError as exc:
                results.append({"ok": False, "filename": f.filename, "error": str(exc)})
        return {"results": results}

    @api.post("/inspection/analyze", tags=["inspection"], dependencies=[Depends(require_control)])
    def analyze(request: Request, body: AnalyzeRequest) -> dict:
        s = svc(request)
        if not s.engine.is_ready():
            raise ModelNotReadyError(s.engine.status()["reason"])
        results = []
        for uid in body.upload_ids:
            try:
                results.append({"upload_id": uid, "ok": True, "inspection": s.inspections.analyze_upload(uid, conf=body.confidence, iou=body.iou)})
            except (NotFound, ImageValidationError) as exc:
                results.append({"upload_id": uid, "ok": False, "error": str(exc)})
        return {"results": results, "mode": s.engine.status()["mode"]}

    @api.get("/inspection/{inspection_id}", tags=["inspection"])
    def get_inspection(request: Request, inspection_id: str) -> dict:
        return svc(request).inspections.get(inspection_id)

    @api.get("/inspection/{inspection_id}/image/{kind}", tags=["inspection"])
    def get_image(request: Request, inspection_id: str, kind: Literal["original", "annotated"]):
        path = svc(request).inspections.image_path(inspection_id, kind)
        return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

    @api.get("/inspections", tags=["inspection"])
    def list_inspections(request: Request, decision: Literal["PASS", "REJECT"] | None = None, class_name: str | None = None,
                         q: str | None = Query(default=None, max_length=100), mode: Literal["real", "demo"] | None = None,
                         source: Literal["upload", "plc_cycle", "demo_seed"] | None = None, date_from: datetime | None = None,
                         date_to: datetime | None = None, include_demo: bool = True, limit: int = Query(50, ge=1, le=200),
                         offset: int = Query(0, ge=0)) -> dict:
        return svc(request).inspections.list(decision=decision, class_name=class_name, q=q, mode=mode, source=source,
                                             date_from=date_from, date_to=date_to, include_demo=include_demo, limit=limit, offset=offset)

    @api.get("/dashboard/stats", tags=["dashboard"])
    def dashboard(request: Request, include_demo: bool = True, days: int = Query(14, ge=1, le=90)) -> dict:
        s = svc(request)
        return {**s.repo.stats(include_demo=include_demo, days=days), "model": {"mode": s.engine.status()["mode"], "ready": s.engine.is_ready()}}

    @api.post("/demo/seed", tags=["demo"], dependencies=[Depends(require_control)])
    def seed(request: Request, body: SeedRequest) -> dict:
        return svc(request).inspections.seed_demo(body.count)

    @api.get("/system/events", tags=["system"])
    def system_events(request: Request, limit: int = Query(50, ge=1, le=200)) -> dict:
        return {"items": [{**e, "created_at": e["created_at"].isoformat()} for e in svc(request).repo.list_system_events(limit)]}

    # ---------------------------------------------------------------- model
    @api.get("/model/status", tags=["model"])
    def model_status(request: Request) -> dict:
        return svc(request).model.status()

    @api.post("/model/config", tags=["model"], dependencies=[Depends(require_control)])
    def model_config(request: Request, body: ModelConfigRequest) -> dict:
        m = svc(request).model
        st = m.configure(confidence=body.confidence_threshold, iou=body.iou_threshold, mode=body.mode, decision_rules=body.decision_rules)
        return m.reload() if body.reload else st

    # ---------------------------------------------------------------- PLC
    @api.get("/plc/status", tags=["plc"])
    def plc_status(request: Request) -> dict:
        return svc(request).plc.status()

    @api.post("/plc/connect", tags=["plc"], dependencies=[Depends(require_control)])
    def plc_connect(request: Request, body: PlcConnectRequest | None = None) -> dict:
        body = body or PlcConnectRequest()
        return svc(request).plc.connect(body.host, body.port)

    @api.post("/plc/disconnect", tags=["plc"], dependencies=[Depends(require_control)])
    def plc_disconnect(request: Request) -> dict:
        return svc(request).plc.disconnect()

    @api.get("/plc/registers", tags=["plc"])
    def plc_registers(request: Request) -> dict:
        return svc(request).plc.registers()

    @api.get("/plc/events", tags=["plc"])
    def plc_events(request: Request, limit: int = Query(50, ge=1, le=200)) -> dict:
        return {"items": svc(request).plc.events(limit)}

    @api.post("/plc/simulate-cycle", tags=["plc"], dependencies=[Depends(require_control)])
    def plc_cycle(request: Request, body: SimulateCycleRequest) -> dict:
        return svc(request).plc.simulate_cycle(body.scenario, body.upload_id)

    @api.post("/plc/emergency-stop", tags=["plc"], dependencies=[Depends(require_control)])
    def plc_estop(request: Request, body: EstopRequest) -> dict:
        return svc(request).plc.emergency_stop(body.active)

    app.include_router(api)

    dist = Path(settings.frontend_dist) if settings.frontend_dist else None
    if dist and dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app
