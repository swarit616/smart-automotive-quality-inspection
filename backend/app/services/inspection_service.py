"""Orchestrates: upload storage -> detection engine -> persistence. Shared by the upload workflow
(Project A) and the PLC cycle workflow (Project B)."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..core import synthetic
from ..core.detectors import Detection
from ..core.engine import AnalysisResult, DetectionEngine
from ..core.preprocessing import validate_and_decode
from ..db.common import new_id, utcnow

log = logging.getLogger(__name__)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


class NotFound(LookupError):
    pass


def display_name(filename: str | None) -> str:
    """Sanitised display name only; it is never used to build a filesystem path."""
    base = (filename or "image").replace("\\", "/").split("/")[-1]
    return _SAFE_NAME.sub("_", base)[:120] or "image"


@dataclass
class InspectionOutcome:
    """What the PLC controller needs from an inspection."""
    decision: str
    defect_count: int
    top_class_id: int | None
    top_confidence: float
    inspection_id: str | None


class InspectionService:
    def __init__(self, settings: Settings, engine: DetectionEngine, repo):
        self.settings, self.engine, self.repo = settings, engine, repo
        settings.ensure_dirs()

    # -- storage ---------------------------------------------------------
    def _write(self, directory: Path, stem: str, ext: str, data: bytes) -> str:
        path = directory / f"{stem}{ext}"
        path.write_bytes(data)
        return str(path.relative_to(self.settings.data_dir))

    def resolve(self, ref: str) -> Path:
        """Resolve a stored relative reference, refusing anything outside DATA_DIR."""
        base = self.settings.data_dir.resolve()
        p = (base / ref).resolve()
        if base not in p.parents:
            raise NotFound("invalid file reference")
        return p

    # -- upload ------------------------------------------------------------
    def save_upload(self, filename: str | None, data: bytes) -> dict:
        v = validate_and_decode(data, max_bytes=self.settings.max_upload_bytes, max_pixels=self.settings.max_image_pixels,
                                min_side=self.settings.min_image_side)
        uid = new_id("UPL")
        ref = self._write(self.settings.upload_dir, uid, v.extension, data)
        rec = self.repo.add_upload({
            "id": uid, "original_filename": display_name(filename), "stored_ref": ref, "fmt": v.fmt, "width": v.width,
            "height": v.height, "size_bytes": v.size_bytes, "sha256": hashlib.sha256(data).hexdigest(),
        })
        return _public_upload(rec)

    def upload_bytes(self, upload_id: str) -> tuple[bytes, dict]:
        up = self.repo.get_upload(upload_id)
        if not up:
            raise NotFound(f"upload {upload_id} not found")
        return self.resolve(up["stored_ref"]).read_bytes(), up

    # -- analysis ------------------------------------------------------------
    def analyze_upload(self, upload_id: str, *, conf: float | None = None, iou: float | None = None) -> dict:
        data, up = self.upload_bytes(upload_id)
        return self.analyze_bytes(data, up["original_filename"], conf=conf, iou=iou, source="upload")

    def analyze_bytes(self, data: bytes, filename: str | None, *, conf: float | None = None, iou: float | None = None,
                      source: str = "upload", plc_event_id: str | None = None) -> dict:
        result = self.engine.analyze_bytes(data, conf=conf, iou=iou)
        return self._persist(result, data, filename, source, plc_event_id)

    def _persist(self, result: AnalysisResult, original: bytes, filename: str | None, source: str, plc_event_id: str | None) -> dict:
        iid = new_id("INS")
        orig_ref = self._write(self.settings.original_dir, iid, result.original_extension, original)
        ann_ref = self._write(self.settings.annotated_dir, iid, ".png", result.annotated_png)
        trig = {id(d) for d in result.decision.triggering}
        top = max(result.decision.triggering or result.detections, key=lambda d: d.confidence, default=None)
        rec = {
            "id": iid, "created_at": utcnow(), "original_ref": orig_ref, "annotated_ref": ann_ref,
            "original_filename": display_name(filename), "decision": result.decision.result,
            "reasons": "; ".join(result.decision.reasons), "top_class": top.class_name if top else None,
            "top_confidence": round(top.confidence, 4) if top else None, "top_bbox": top.bbox.as_list() if top else None,
            "defect_count": len(result.decision.triggering), "model_mode": result.mode, "model_name": result.model_name,
            "model_version": result.model_version, "confidence_threshold": result.confidence_threshold,
            "iou_threshold": result.iou_threshold, "duration_ms": result.duration_ms, "width": result.width,
            "height": result.height, "source": source, "plc_event_id": plc_event_id,
            "defects": [{"class_id": d.class_id, "class_name": d.class_name, "confidence": round(d.confidence, 4),
                         "bbox": d.bbox.as_list(), "triggered": id(d) in trig} for d in result.detections],
        }
        saved = self.repo.add_inspection(rec)
        return self.public(saved)

    def outcome_for_plc(self, data: bytes, plc_event_id: str | None) -> InspectionOutcome:
        rec = self.analyze_bytes(data, "plc-cycle", source="plc_cycle", plc_event_id=plc_event_id)
        trig = [d for d in rec["defects"] if d["triggered"]]
        top = max(trig, key=lambda d: d["confidence"], default=None)
        return InspectionOutcome(rec["decision"], rec["defect_count"], top["class_id"] if top else None,
                                 top["confidence"] if top else 0.0, rec["id"])

    # -- queries ---------------------------------------------------------------
    def get(self, inspection_id: str) -> dict:
        rec = self.repo.get_inspection(inspection_id)
        if not rec:
            raise NotFound(f"inspection {inspection_id} not found")
        return self.public(rec)

    def list(self, **filters) -> dict:
        items, total = self.repo.list_inspections(**filters)
        return {"items": [self.public(i) for i in items], "total": total, "limit": filters.get("limit", 50),
                "offset": filters.get("offset", 0)}

    def image_path(self, inspection_id: str, kind: str) -> Path:
        rec = self.repo.get_inspection(inspection_id)
        if not rec or kind not in ("original", "annotated"):
            raise NotFound("image not found")
        p = self.resolve(rec["original_ref"] if kind == "original" else rec["annotated_ref"])
        if not p.is_file():
            raise NotFound("image file missing on disk")
        return p

    @staticmethod
    def public(rec: dict) -> dict:
        out = dict(rec)
        out["created_at"] = out["created_at"].isoformat() if hasattr(out["created_at"], "isoformat") else out["created_at"]
        out.pop("original_ref", None)
        out.pop("annotated_ref", None)
        out["is_demo"] = rec["model_mode"] == "demo" or rec["source"] == "demo_seed"
        out["original_url"] = f"/api/v1/inspection/{rec['id']}/image/original"
        out["annotated_url"] = f"/api/v1/inspection/{rec['id']}/image/annotated"
        return out

    # -- demo data -----------------------------------------------------------------
    def seed_demo(self, count: int = 24) -> dict:
        """Create clearly labelled DEMO records (synthetic images, demo heuristic detector)."""
        from dataclasses import replace

        demo_settings = replace(self.settings, detection_mode="demo")
        demo_engine = DetectionEngine(demo_settings, self.engine.rules)
        created = 0
        for i in range(count):
            img, _ = synthetic.make_sample(5000 + i, defective=(i % 3 != 0))
            result = demo_engine.analyze_bytes(synthetic.encode_png(img))
            self._persist(result, synthetic.encode_png(img), f"demo-seed-{i:03d}.png", "demo_seed", None)
            created += 1
        self.repo.add_system_event("INFO", f"seeded {created} DEMO inspection records (synthetic images)", {"count": created})
        return {"created": created, "label": "demo_seed"}


def _public_upload(rec: dict) -> dict:
    return {"upload_id": rec["id"], "filename": rec["original_filename"], "width": rec["width"], "height": rec["height"],
            "size_bytes": rec["size_bytes"], "format": rec["fmt"]}
