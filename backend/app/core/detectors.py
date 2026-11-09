"""Detector back-ends behind one interface.

* UltralyticsDetector - YOLOv8 .pt weights (needs the optional `ultralytics` package).
* OnnxYoloDetector    - YOLOv8 exported to ONNX, run with onnxruntime (CPU friendly).
* DemoDetector        - classical OpenCV anomaly finder used ONLY in DEMO MODE. It is NOT a
                        trained defect model; its output must always be labelled as demo.
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np

from .boxes import BBox, class_aware_nms, nms, validate_box, BoxError
from .preprocessing import to_model_input, undo_letterbox

log = logging.getLogger(__name__)


class DetectorUnavailable(RuntimeError):
    """The requested back-end cannot be used (missing weights or optional dependency)."""


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: BBox

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "bbox": self.bbox.as_list(),
        }


class Detector(Protocol):
    name: str
    version: str
    class_names: list[str]

    def detect(self, image_bgr: np.ndarray, conf: float, iou: float) -> list[Detection]: ...


def file_version(path: Path) -> str:
    """Short content hash used as the model version identifier."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def load_class_names(weights: Path, explicit: str = "") -> list[str] | None:
    """Class names from an explicit JSON/TXT file or a sidecar `<weights>.names.json`."""
    candidates = [Path(explicit)] if explicit else []
    candidates += [weights.with_suffix(".names.json"), weights.parent / "class_names.json"]
    for c in candidates:
        if c.is_file():
            try:
                data = json.loads(c.read_text())
                if isinstance(data, dict):
                    return [data[k] for k in sorted(data, key=lambda x: int(x))]
                if isinstance(data, list):
                    return [str(x) for x in data]
            except (ValueError, KeyError) as exc:
                log.warning("could not parse class names file %s: %s", c, exc)
    return None


# --------------------------------------------------------------------------- YOLOv8 ONNX
def postprocess_yolov8(
    output: np.ndarray,
    class_names: Sequence[str],
    conf: float,
    iou: float,
    lb,
    orig_w: int,
    orig_h: int,
) -> list[Detection]:
    """Decode a raw YOLOv8 detection head of shape (1, 4+nc, N) or (1, N, 4+nc).

    Box format in the raw tensor is (cx, cy, w, h) in letterboxed pixels; there is no
    objectness channel in YOLOv8, the class scores are used directly.
    """
    pred = np.asarray(output)
    if pred.ndim == 3:
        pred = pred[0]
    nc = len(class_names)
    if pred.shape[0] == 4 + nc and pred.shape[1] != 4 + nc:
        pred = pred.T
    if pred.shape[1] != 4 + nc:
        raise ValueError(f"unexpected output shape {output.shape} for {nc} classes")
    scores_all = pred[:, 4:]
    cls_ids = scores_all.argmax(axis=1)
    scores = scores_all[np.arange(len(pred)), cls_ids]
    mask = scores >= conf
    if not mask.any():
        return []
    pred, cls_ids, scores = pred[mask], cls_ids[mask], scores[mask]
    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    keep = class_aware_nms(xyxy, scores, cls_ids, iou)
    xyxy = undo_letterbox(xyxy[keep], lb, orig_w, orig_h)
    out: list[Detection] = []
    for box, cid, sc in zip(xyxy, cls_ids[keep], scores[keep]):
        try:
            b = validate_box(BBox(*map(float, box)), orig_w, orig_h, clip=True)
        except BoxError:
            continue
        out.append(Detection(int(cid), class_names[int(cid)], float(sc), b))
    return out


class OnnxYoloDetector:
    name = "yolov8-onnx"

    def __init__(self, weights: Path, class_names: list[str] | None = None, image_size: int = 640):
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise DetectorUnavailable("onnxruntime is not installed") from exc
        if not weights.is_file():
            raise DetectorUnavailable(f"weights not found: {weights}")
        self._session = ort.InferenceSession(str(weights), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        shape = self._session.get_inputs()[0].shape
        self.image_size = int(shape[2]) if isinstance(shape[2], int) else image_size
        names = class_names
        if names is None:
            meta = self._session.get_modelmeta().custom_metadata_map.get("names")
            if meta:
                d = ast.literal_eval(meta)
                names = [d[k] for k in sorted(d)]
        if not names:
            raise DetectorUnavailable("class names unavailable: provide a *.names.json file next to the weights")
        self.class_names = list(names)
        self.version = file_version(weights)

    def detect(self, image_bgr: np.ndarray, conf: float, iou: float) -> list[Detection]:
        h, w = image_bgr.shape[:2]
        tensor, lb = to_model_input(image_bgr, self.image_size)
        out = self._session.run(None, {self._input: tensor})[0]
        return postprocess_yolov8(out, self.class_names, conf, iou, lb, w, h)


# --------------------------------------------------------------------------- Ultralytics
class UltralyticsDetector:
    name = "yolov8-ultralytics"

    def __init__(self, weights: Path, image_size: int = 640):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorUnavailable("ultralytics is not installed (pip install -r backend/requirements-train.txt)") from exc
        if not weights.is_file():
            raise DetectorUnavailable(f"weights not found: {weights}")
        self._model = YOLO(str(weights))
        self.image_size = image_size
        names = self._model.names
        self.class_names = [names[i] for i in sorted(names)]
        self.version = file_version(weights)
        try:
            import torch

            self._device = 0 if torch.cuda.is_available() else "cpu"
        except ImportError:  # pragma: no cover
            self._device = "cpu"

    def detect(self, image_bgr: np.ndarray, conf: float, iou: float) -> list[Detection]:
        h, w = image_bgr.shape[:2]
        res = self._model.predict(image_bgr, conf=conf, iou=iou, imgsz=self.image_size, device=self._device, verbose=False)[0]
        out: list[Detection] = []
        if res.boxes is None:
            return out
        for xyxy, sc, cid in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()):
            try:
                b = validate_box(BBox(*map(float, xyxy)), w, h, clip=True)
            except BoxError:
                continue
            out.append(Detection(int(cid), self.class_names[int(cid)], float(sc), b))
        return out


# --------------------------------------------------------------------------- Demo
class DemoDetector:
    """Classical-CV surface anomaly finder for DEMO MODE.

    It looks for local deviations from a heavily blurred background. It has never been
    validated against real defect data, so the "confidence" it reports is only a normalised
    contrast score (0-1), not a model probability.
    """

    name = "demo-anomaly-heuristic"
    version = "demo-1"
    class_names = ["scratch", "blemish"]

    def __init__(self, min_area_ratio: float = 0.0003, max_detections: int = 20):
        self.min_area_ratio = min_area_ratio
        self.max_detections = max_detections

    def detect(self, image_bgr: np.ndarray, conf: float, iou: float) -> list[Detection]:
        h, w = image_bgr.shape[:2]
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        scale = 512 / max(h, w) if max(h, w) > 512 else 1.0
        small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale != 1.0 else gray
        small = cv2.GaussianBlur(small, (3, 3), 0)
        bg = cv2.GaussianBlur(small, (0, 0), sigmaX=max(small.shape) / 12)
        diff = cv2.absdiff(small, bg).astype(np.float32)
        thr = max(float(diff.mean() + 4.0 * diff.std()), 22.0)
        mask = (diff > thr).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        min_area = self.min_area_ratio * small.shape[0] * small.shape[1]
        dets: list[Detection] = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < max(min_area, 6):
                continue
            contrast = float(diff[labels == i].mean())
            score = float(min(1.0, contrast / 90.0))
            if score < conf:
                continue
            aspect = max(bw, bh) / max(1, min(bw, bh))
            cid = 0 if aspect >= 3.0 else 1
            box = BBox(x / scale, y / scale, (x + bw) / scale, (y + bh) / scale)
            try:
                box = validate_box(box, w, h, clip=True)
            except BoxError:
                continue
            dets.append(Detection(cid, self.class_names[cid], score, box))
        if not dets:
            return []
        arr = np.array([[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2] for d in dets])
        keep = nms(arr, np.array([d.confidence for d in dets]), iou)
        return [dets[k] for k in keep][: self.max_detections]
