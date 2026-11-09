"""In-memory Repository. Used by the offline unit tests and for quick experiments; not persistent."""
from __future__ import annotations

import copy
import threading
from datetime import datetime

from .common import as_utc, compute_stats, is_demo_row, new_id, utcnow


class MemoryRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.uploads: dict[str, dict] = {}
        self.inspections: dict[str, dict] = {}
        self.plc_events: list[dict] = []
        self.machine: list[dict] = []
        self.system: list[dict] = []
        self.model_configs: list[dict] = []

    def init(self) -> None:
        return None

    def ping(self) -> bool:
        return True

    def add_upload(self, rec: dict) -> dict:
        with self._lock:
            rec = {**rec, "created_at": rec.get("created_at") or utcnow()}
            self.uploads[rec["id"]] = rec
            return copy.deepcopy(rec)

    def get_upload(self, upload_id: str) -> dict | None:
        return copy.deepcopy(self.uploads.get(upload_id))

    def add_inspection(self, rec: dict) -> dict:
        with self._lock:
            rec = copy.deepcopy(rec)
            rec.setdefault("created_at", utcnow())
            self.inspections[rec["id"]] = rec
            return copy.deepcopy(rec)

    def get_inspection(self, inspection_id: str) -> dict | None:
        return copy.deepcopy(self.inspections.get(inspection_id))

    def list_inspections(self, *, decision=None, class_name=None, q=None, mode=None, source=None, date_from=None,
                         date_to=None, include_demo=True, limit=50, offset=0):
        with self._lock:
            items = list(self.inspections.values())
        out = []
        for r in items:
            if not include_demo and is_demo_row(r["model_mode"], r["source"]):
                continue
            if decision and r["decision"] != decision:
                continue
            if mode and r["model_mode"] != mode:
                continue
            if source and r["source"] != source:
                continue
            if class_name and not any(d["class_name"] == class_name for d in r["defects"]):
                continue
            if q:
                ql = q.lower()
                if ql not in r["id"].lower() and ql not in (r.get("original_filename") or "").lower() and ql not in (r.get("top_class") or "").lower():
                    continue
            ts = as_utc(r["created_at"])
            if date_from and ts < as_utc(date_from):
                continue
            if date_to and ts > as_utc(date_to):
                continue
            out.append(r)
        out.sort(key=lambda r: as_utc(r["created_at"]), reverse=True)
        total = len(out)
        return [copy.deepcopy(r) for r in out[offset : offset + limit]], total

    def stats(self, *, include_demo=True, days=14):
        with self._lock:
            rows = list(self.inspections.values())
        defects = [{"inspection_id": r["id"], "class_name": d["class_name"], "triggered": d.get("triggered", True)}
                   for r in rows for d in r["defects"]]
        return compute_stats(rows, defects, include_demo=include_demo, days=days)

    def add_plc_event(self, rec: dict) -> dict:
        with self._lock:
            rec = {"id": new_id("EVT"), "created_at": utcnow(), **rec}
            self.plc_events.append(rec)
            return copy.deepcopy(rec)

    def list_plc_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return copy.deepcopy(sorted(self.plc_events, key=lambda e: e["created_at"], reverse=True)[:limit])

    def save_machine_status(self, rec: dict) -> dict:
        with self._lock:
            rec = {"created_at": utcnow(), **rec}
            self.machine.append(rec)
            return copy.deepcopy(rec)

    def latest_machine_status(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self.machine[-1]) if self.machine else None

    def add_system_event(self, level: str, message: str, detail: dict | None = None) -> dict:
        with self._lock:
            rec = {"id": new_id("SYS"), "created_at": utcnow(), "level": level, "message": message, "detail": detail or {}}
            self.system.append(rec)
            return copy.deepcopy(rec)

    def list_system_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(reversed(self.system))[:limit])

    def save_model_config(self, rec: dict) -> dict:
        with self._lock:
            rec = {"created_at": utcnow(), **rec}
            self.model_configs.append(rec)
            return copy.deepcopy(rec)

    def latest_model_config(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self.model_configs[-1]) if self.model_configs else None
