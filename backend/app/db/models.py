"""SQLAlchemy 2.0 ORM models.

NOTE: not executed in the offline build environment (SQLAlchemy could not be installed there);
tests/test_db_sqlalchemy.py runs the shared repository contract against this implementation
when SQLAlchemy is available (CI does).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .common import utcnow

SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_ref: Mapped[str] = mapped_column(String(255))
    fmt: Mapped[str] = mapped_column(String(8))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    original_ref: Mapped[str] = mapped_column(String(255))
    annotated_ref: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision: Mapped[str] = mapped_column(String(8), index=True)
    reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    top_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    defect_count: Mapped[int] = mapped_column(Integer, default=0)
    model_mode: Mapped[str] = mapped_column(String(8))
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(64))
    confidence_threshold: Mapped[float] = mapped_column(Float)
    iou_threshold: Mapped[float] = mapped_column(Float)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload | plc_cycle | demo_seed
    plc_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    defects: Mapped[list["Defect"]] = relationship(back_populates="inspection", cascade="all, delete-orphan", order_by="Defect.id")


class Defect(Base):
    __tablename__ = "defects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[int] = mapped_column(Integer)
    class_name: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    bbox: Mapped[list] = mapped_column(JSON)
    triggered: Mapped[bool] = mapped_column(Boolean, default=True)
    inspection: Mapped[Inspection] = relationship(back_populates="defects")


class ModelConfigRecord(Base):
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    config: Mapped[dict] = mapped_column(JSON)


class PlcEvent(Base):
    __tablename__ = "plc_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(32))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    inspection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MachineStatusRecord(Base):
    __tablename__ = "machine_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    machine_state: Mapped[str] = mapped_column(String(16))
    conveyor_running: Mapped[bool] = mapped_column(Boolean)
    estop: Mapped[bool] = mapped_column(Boolean)
    components: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    rejected: Mapped[int] = mapped_column(Integer)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class SystemEvent(Base):
    __tablename__ = "system_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


Index("ix_inspections_mode_source", Inspection.model_mode, Inspection.source)
