"""Service container (framework-independent): wires settings, repository, engine and services."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..core.engine import DetectionEngine
from ..db import make_repository
from .inspection_service import InspectionService
from .model_service import ModelService
from .plc_service import PlcService


@dataclass
class Services:
    settings: Settings
    repo: object
    engine: DetectionEngine
    inspections: InspectionService
    model: ModelService
    plc: PlcService


def build_services(settings: Settings, repo=None, engine: DetectionEngine | None = None) -> Services:
    settings.ensure_dirs()
    repo = repo or make_repository(settings.database_url)
    repo.init()
    engine = engine or DetectionEngine(settings)
    inspections = InspectionService(settings, engine, repo)
    model = ModelService(engine, repo)
    model.restore_saved_config()
    return Services(settings, repo, engine, inspections, model, PlcService(settings, inspections, repo))
