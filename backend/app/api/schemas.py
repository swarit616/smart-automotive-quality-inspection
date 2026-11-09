"""Pydantic request models (validation happens before any service code runs)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    upload_ids: list[str] = Field(min_length=1, max_length=50, description="ids returned by the upload endpoint")
    confidence: float | None = Field(default=None, gt=0.0, lt=1.0)
    iou: float | None = Field(default=None, gt=0.0, lt=1.0)


class ModelConfigRequest(BaseModel):
    confidence_threshold: float | None = Field(default=None, gt=0.0, lt=1.0)
    iou_threshold: float | None = Field(default=None, gt=0.0, lt=1.0)
    mode: Literal["auto", "real", "demo"] | None = None
    decision_rules: dict | None = Field(default=None, description="partial DecisionRules; see docs/API_GUIDE.md")
    reload: bool = False


class PlcConnectRequest(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)


class SimulateCycleRequest(BaseModel):
    scenario: Literal["normal", "defective", "upload"] = "normal"
    upload_id: str | None = None


class EstopRequest(BaseModel):
    active: bool = True


class SeedRequest(BaseModel):
    count: int = Field(default=24, ge=1, le=200)
