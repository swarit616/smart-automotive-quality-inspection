"""Backend-independent repository contract helpers (stats computation, id generation)."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Protocol


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8]}"


class Repository(Protocol):
    def init(self) -> None: ...
    def ping(self) -> bool: ...
    def add_upload(self, rec: dict) -> dict: ...
    def get_upload(self, upload_id: str) -> dict | None: ...
    def add_inspection(self, rec: dict) -> dict: ...
    def get_inspection(self, inspection_id: str) -> dict | None: ...
    def list_inspections(self, *, decision: str | None = None, class_name: str | None = None, q: str | None = None,
                         mode: str | None = None, source: str | None = None, date_from: datetime | None = None,
                         date_to: datetime | None = None, include_demo: bool = True, limit: int = 50,
                         offset: int = 0) -> tuple[list[dict], int]: ...
    def stats(self, *, include_demo: bool = True, days: int = 14) -> dict: ...
    def add_plc_event(self, rec: dict) -> dict: ...
    def list_plc_events(self, limit: int = 50) -> list[dict]: ...
    def save_machine_status(self, rec: dict) -> dict: ...
    def latest_machine_status(self) -> dict | None: ...
    def add_system_event(self, level: str, message: str, detail: dict | None = None) -> dict: ...
    def list_system_events(self, limit: int = 50) -> list[dict]: ...
    def save_model_config(self, rec: dict) -> dict: ...
    def latest_model_config(self) -> dict | None: ...


def is_demo_row(model_mode: str | None, source: str | None) -> bool:
    return model_mode == "demo" or source == "demo_seed"


def compute_stats(rows: Iterable[dict], defect_rows: Iterable[dict], *, include_demo: bool, days: int, now: datetime | None = None) -> dict:
    """rows: inspection summaries; defect_rows: {inspection_id, class_name, triggered}."""
    now = now or utcnow()
    rows = [r for r in rows if include_demo or not is_demo_row(r["model_mode"], r["source"])]
    ids = {r["id"] for r in rows}
    total = len(rows)
    passed = sum(1 for r in rows if r["decision"] == "PASS")
    rejected = total - passed
    dist = Counter(d["class_name"] for d in defect_rows if d["inspection_id"] in ids and d["triggered"])
    start = (now - timedelta(days=days - 1)).date()
    per_day: dict = defaultdict(lambda: {"total": 0, "passed": 0, "rejected": 0})
    for r in rows:
        day = as_utc(r["created_at"]).date()
        if day >= start:
            b = per_day[day]
            b["total"] += 1
            b["passed" if r["decision"] == "PASS" else "rejected"] += 1
    trend = []
    for i in range(days):
        day = start + timedelta(days=i)
        trend.append({"date": day.isoformat(), **per_day.get(day, {"total": 0, "passed": 0, "rejected": 0})})
    durations = [r["duration_ms"] for r in rows if r.get("duration_ms") is not None]
    recent = sorted(rows, key=lambda r: as_utc(r["created_at"]), reverse=True)[:8]
    return {
        "total": total, "passed": passed, "rejected": rejected,
        "reject_rate": round(rejected / total, 4) if total else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "defect_distribution": [{"class_name": k, "count": v} for k, v in dist.most_common()],
        "trend": trend,
        "recent": [{"id": r["id"], "created_at": as_utc(r["created_at"]).isoformat(), "decision": r["decision"],
                    "top_class": r.get("top_class"), "model_mode": r["model_mode"], "source": r["source"]} for r in recent],
        "demo_records": sum(1 for r in rows if is_demo_row(r["model_mode"], r["source"])),
        "include_demo": include_demo,
    }
