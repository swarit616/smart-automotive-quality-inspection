
"""SQLAlchemy implementation of the Repository contract (SQLite default, PostgreSQL supported).

Initialisation strategy: Base.metadata.create_all plus a schema_version row.
If the stored version differs from SCHEMA_VERSION the app refuses to start.
Alembic can be adopted later without changing the repository interface.

NOTE: not executed in the offline build environment; covered by tests/test_db_sqlalchemy.py in CI.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from .common import as_utc, compute_stats, new_id, utcnow
from .models import (
    SCHEMA_VERSION,
    Base,
    Defect,
    Inspection,
    MachineStatusRecord,
    ModelConfigRecord,
    PlcEvent,
    SchemaVersion,
    SystemEvent,
    Upload,
)


def make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}

        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool

        engine = create_engine(url, **kwargs)
        return engine

    return create_engine(url, pool_pre_ping=True)


def _insp_dict(i: Inspection, with_defects: bool = True) -> dict:
    d = {
        c: getattr(i, c)
        for c in (
            "id",
            "created_at",
            "original_ref",
            "annotated_ref",
            "original_filename",
            "decision",
            "reasons",
            "top_class",
            "top_confidence",
            "top_bbox",
            "defect_count",
            "model_mode",
            "model_name",
            "model_version",
            "confidence_threshold",
            "iou_threshold",
            "duration_ms",
            "width",
            "height",
            "source",
            "plc_event_id",
        )
    }

    if with_defects:
        d["defects"] = [
            {
                "class_id": x.class_id,
                "class_name": x.class_name,
                "confidence": x.confidence,
                "bbox": x.bbox,
                "triggered": x.triggered,
            }
            for x in i.defects
        ]

    return d


class SqlRepository:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self._Session = sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    def close(self) -> None:
        """Release database connections and dispose of the connection pool."""
        self.engine.dispose()

    def init(self) -> None:
        Base.metadata.create_all(self.engine)

        with self._Session() as s:
            row = s.get(SchemaVersion, 1)

            if row is None:
                s.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
                s.commit()

            elif row.version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {row.version} != expected "
                    f"{SCHEMA_VERSION}; migrate or recreate the database"
                )

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))

            return True

        except Exception:  # noqa: BLE001
            return False

    # -- uploads -------------------------------------------------------------

    def add_upload(self, rec: dict) -> dict:
        with self._Session() as s:
            u = Upload(
                **{
                    k: v
                    for k, v in rec.items()
                    if k in Upload.__table__.columns.keys()
                }
            )

            s.add(u)
            s.commit()

            return {
                c: getattr(u, c)
                for c in Upload.__table__.columns.keys()
            }

    def get_upload(self, upload_id: str) -> dict | None:
        with self._Session() as s:
            u = s.get(Upload, upload_id)

            return (
                None
                if u is None
                else {
                    c: getattr(u, c)
                    for c in Upload.__table__.columns.keys()
                }
            )

    # -- inspections ---------------------------------------------------------

    def add_inspection(self, rec: dict) -> dict:
        with self._Session() as s:
            data = {
                k: v
                for k, v in rec.items()
                if k != "defects"
            }

            insp = Inspection(**data)

            insp.defects = [
                Defect(**d)
                for d in rec.get("defects", [])
            ]

            s.add(insp)
            s.commit()
            s.refresh(insp)

            return _insp_dict(insp)

    def get_inspection(self, inspection_id: str) -> dict | None:
        with self._Session() as s:
            i = s.execute(
                select(Inspection)
                .options(selectinload(Inspection.defects))
                .where(Inspection.id == inspection_id)
            ).scalar_one_or_none()

            return None if i is None else _insp_dict(i)

    def list_inspections(
        self,
        *,
        decision=None,
        class_name=None,
        q=None,
        mode=None,
        source=None,
        date_from=None,
        date_to=None,
        include_demo=True,
        limit=50,
        offset=0,
    ):
        stmt = select(Inspection).options(
            selectinload(Inspection.defects)
        )

        if not include_demo:
            stmt = stmt.where(
                Inspection.model_mode != "demo",
                Inspection.source != "demo_seed",
            )

        if decision:
            stmt = stmt.where(Inspection.decision == decision)

        if mode:
            stmt = stmt.where(Inspection.model_mode == mode)

        if source:
            stmt = stmt.where(Inspection.source == source)

        if class_name:
            stmt = stmt.where(
                Inspection.defects.any(
                    Defect.class_name == class_name
                )
            )

        if q:
            like = f"%{q.lower()}%"

            stmt = stmt.where(
                or_(
                    func.lower(Inspection.id).like(like),
                    func.lower(
                        func.coalesce(
                            Inspection.original_filename,
                            "",
                        )
                    ).like(like),
                    func.lower(
                        func.coalesce(
                            Inspection.top_class,
                            "",
                        )
                    ).like(like),
                )
            )

        if date_from:
            stmt = stmt.where(
                Inspection.created_at >= as_utc(date_from)
            )

        if date_to:
            stmt = stmt.where(
                Inspection.created_at <= as_utc(date_to)
            )

        with self._Session() as s:
            total = s.execute(
                select(func.count())
                .select_from(stmt.order_by(None).subquery())
            ).scalar_one()

            rows = s.execute(
                stmt.order_by(Inspection.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).scalars().all()

            return [_insp_dict(r) for r in rows], int(total)

    def stats(self, *, include_demo=True, days=14):
        with self._Session() as s:
            rows = [
                dict(
                    id=r.id,
                    created_at=r.created_at,
                    decision=r.decision,
                    top_class=r.top_class,
                    model_mode=r.model_mode,
                    source=r.source,
                    duration_ms=r.duration_ms,
                )
                for r in s.execute(
                    select(
                        Inspection.id,
                        Inspection.created_at,
                        Inspection.decision,
                        Inspection.top_class,
                        Inspection.model_mode,
                        Inspection.source,
                        Inspection.duration_ms,
                    )
                ).all()
            ]

            defects = [
                dict(
                    inspection_id=r.inspection_id,
                    class_name=r.class_name,
                    triggered=r.triggered,
                )
                for r in s.execute(
                    select(
                        Defect.inspection_id,
                        Defect.class_name,
                        Defect.triggered,
                    )
                ).all()
            ]

        return compute_stats(
            rows,
            defects,
            include_demo=include_demo,
            days=days,
        )

    # -- events / status / config --------------------------------------------

    def add_plc_event(self, rec: dict) -> dict:
        with self._Session() as s:
            e = PlcEvent(
                id=new_id("EVT"),
                **{
                    k: v
                    for k, v in rec.items()
                    if k in PlcEvent.__table__.columns.keys()
                    and k != "id"
                },
            )

            s.add(e)
            s.commit()

            return {
                c: getattr(e, c)
                for c in PlcEvent.__table__.columns.keys()
            }

    def list_plc_events(self, limit: int = 50) -> list[dict]:
        with self._Session() as s:
            rows = s.execute(
                select(PlcEvent)
                .order_by(PlcEvent.created_at.desc())
                .limit(limit)
            ).scalars().all()

            return [
                {
                    c: getattr(e, c)
                    for c in PlcEvent.__table__.columns.keys()
                }
                for e in rows
            ]

    def save_machine_status(self, rec: dict) -> dict:
        with self._Session() as s:
            m = MachineStatusRecord(
                **{
                    k: v
                    for k, v in rec.items()
                    if k in MachineStatusRecord.__table__.columns.keys()
                    and k != "id"
                }
            )

            s.add(m)
            s.commit()

            return {
                c: getattr(m, c)
                for c in MachineStatusRecord.__table__.columns.keys()
            }

    def latest_machine_status(self) -> dict | None:
        with self._Session() as s:
            m = s.execute(
                select(MachineStatusRecord)
                .order_by(MachineStatusRecord.id.desc())
                .limit(1)
            ).scalar_one_or_none()

            return (
                None
                if m is None
                else {
                    c: getattr(m, c)
                    for c in MachineStatusRecord.__table__.columns.keys()
                }
            )

    def add_system_event(
        self,
        level: str,
        message: str,
        detail: dict | None = None,
    ) -> dict:
        with self._Session() as s:
            e = SystemEvent(
                id=new_id("SYS"),
                level=level,
                message=message,
                detail=detail or {},
            )

            s.add(e)
            s.commit()

            return {
                c: getattr(e, c)
                for c in SystemEvent.__table__.columns.keys()
            }

    def list_system_events(self, limit: int = 50) -> list[dict]:
        with self._Session() as s:
            rows = s.execute(
                select(SystemEvent)
                .order_by(SystemEvent.created_at.desc())
                .limit(limit)
            ).scalars().all()

            return [
                {
                    c: getattr(e, c)
                    for c in SystemEvent.__table__.columns.keys()
                }
                for e in rows
            ]

    def save_model_config(self, rec: dict) -> dict:
        with self._Session() as s:
            r = ModelConfigRecord(config=rec)

            s.add(r)
            s.commit()

            return {
                "created_at": r.created_at,
                **r.config,
            }

    def latest_model_config(self) -> dict | None:
        with self._Session() as s:
            r = s.execute(
                select(ModelConfigRecord)
                .order_by(ModelConfigRecord.id.desc())
                .limit(1)
            ).scalar_one_or_none()

            return (
                None
                if r is None
                else {
                    "created_at": r.created_at,
                    **r.config,
                }
            )
